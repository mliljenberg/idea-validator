use std::collections::HashMap;
use std::sync::Arc;

use tauri::{AppHandle, Emitter, State};
use tokio::sync::Mutex;
use tokio_util::sync::CancellationToken;

use crate::backend::{choose_default_app, BackendManager};
use crate::keyring_store::KeyStore;
use crate::stream;
use crate::types::{
    Ack, BackendStartConfig, BackendStatus, KeyPresence, KeysInput, SessionCreateInput,
    SessionListInput, SessionMeta, StreamRunInput,
};

#[derive(Clone)]
pub struct AppState {
    pub backend: Arc<Mutex<BackendManager>>,
    pub stream_tokens: Arc<Mutex<HashMap<String, CancellationToken>>>,
    pub key_store: KeyStore,
}

impl AppState {
    pub fn new() -> Self {
        Self {
            backend: Arc::new(Mutex::new(BackendManager::default())),
            stream_tokens: Arc::new(Mutex::new(HashMap::new())),
            key_store: KeyStore::default(),
        }
    }
}

#[tauri::command]
pub async fn backend_start(
    app: AppHandle,
    state: State<'_, AppState>,
    config: Option<BackendStartConfig>,
) -> Result<BackendStatus, String> {
    let keys = state.key_store.read_env_values()?;
    let mut backend = state.backend.lock().await;
    let status = backend.start(config, &keys).await?;
    app.emit("backend-status", &status)
        .map_err(|e| format!("failed to emit backend-status: {e}"))?;
    Ok(status)
}

#[tauri::command]
pub async fn backend_stop(
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<BackendStatus, String> {
    let mut backend = state.backend.lock().await;
    backend.stop().await?;
    let (status, _) = backend.status().await?;
    app.emit("backend-status", &status)
        .map_err(|e| format!("failed to emit backend-status: {e}"))?;
    Ok(status)
}

#[tauri::command]
pub async fn backend_status(
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<BackendStatus, String> {
    let mut backend = state.backend.lock().await;
    let (status, exited) = backend.status().await?;

    if exited {
        let message = status
            .last_error
            .clone()
            .unwrap_or_else(|| "Local backend process exited unexpectedly.".to_string());
        app.emit("backend-exited", serde_json::json!({ "message": message }))
            .map_err(|e| format!("failed to emit backend-exited: {e}"))?;
    }

    Ok(status)
}

#[tauri::command]
pub async fn backend_list_apps(state: State<'_, AppState>) -> Result<Vec<String>, String> {
    let mut backend = state.backend.lock().await;
    let (status, _) = backend.status().await?;
    if !status.running || !status.health {
        let keys = state.key_store.read_env_values()?;
        let restarted = backend
            .start(
                Some(BackendStartConfig {
                    host: Some(status.host),
                    port: Some(status.port),
                    repo_root: None,
                    force_restart: Some(true),
                }),
                &keys,
            )
            .await?;

        if !restarted.running || !restarted.health {
            return Err("Backend is unavailable; failed to recover before listing apps.".to_string());
        }
    }

    let apps = backend.list_apps().await?;

    if backend.app_name().is_none() {
        backend.set_app_name(choose_default_app(&apps));
    }

    Ok(apps)
}

#[tauri::command]
pub async fn session_create(
    state: State<'_, AppState>,
    input: SessionCreateInput,
) -> Result<SessionMeta, String> {
    let mut backend = state.backend.lock().await;
    let (status, _) = backend.status().await?;
    if !status.running {
        return Err("Backend is not running. Start backend before creating sessions.".to_string());
    }

    let session = backend
        .create_session(
            &input.app_name,
            &input.user_id,
            input.session_id.as_deref(),
        )
        .await?;

    backend.set_app_name(Some(input.app_name));
    Ok(session)
}

#[tauri::command]
pub async fn session_list(
    state: State<'_, AppState>,
    input: SessionListInput,
) -> Result<Vec<SessionMeta>, String> {
    let mut backend = state.backend.lock().await;
    let (status, _) = backend.status().await?;
    if !status.running {
        return Err("Backend is not running. Start backend before listing sessions.".to_string());
    }

    backend.list_sessions(&input.app_name, &input.user_id).await
}

#[tauri::command]
pub async fn stream_run(
    app: AppHandle,
    state: State<'_, AppState>,
    input: StreamRunInput,
) -> Result<Ack, String> {
    if input.text.trim().is_empty() {
        return Err("Message text is required.".to_string());
    }

    let base_url = {
        let mut backend = state.backend.lock().await;
        let (status, _) = backend.status().await?;
        if !status.running {
            return Err("Backend is not running. Start backend before streaming.".to_string());
        }

        if status.health {
            status.base_url
        } else {
            let keys = state.key_store.read_env_values()?;
            let restarted = backend
                .start(
                    Some(BackendStartConfig {
                        host: Some(status.host),
                        port: Some(status.port),
                        repo_root: None,
                        force_restart: Some(true),
                    }),
                    &keys,
                )
                .await?;

            if !restarted.health {
                return Err("Backend is unhealthy and restart failed. Please restart the desktop app.".to_string());
            }
            restarted.base_url
        }
    };

    let token = CancellationToken::new();
    {
        let mut map = state.stream_tokens.lock().await;
        if let Some(existing) = map.insert(input.request_id.clone(), token.clone()) {
            existing.cancel();
        }
    }

    let app_handle = app.clone();
    let request_id = input.request_id.clone();
    let stream_map = state.stream_tokens.clone();

    tokio::spawn(async move {
        if let Err(err) = stream::run_stream_task(app_handle.clone(), base_url, input, token).await {
            let event_name = format!("agent-stream:{}", request_id);
            let _ = app_handle.emit(
                &event_name,
                serde_json::json!({
                    "kind": "stream_error",
                    "requestId": request_id,
                    "message": err,
                    "retryable": true
                }),
            );
        }

        let mut map = stream_map.lock().await;
        map.remove(&request_id);
    });

    Ok(Ack {
        ok: true,
        message: Some("Stream started".to_string()),
    })
}

#[tauri::command]
pub async fn stream_cancel(
    state: State<'_, AppState>,
    request_id: String,
) -> Result<Ack, String> {
    let mut map = state.stream_tokens.lock().await;
    if let Some(token) = map.remove(&request_id) {
        token.cancel();
        return Ok(Ack {
            ok: true,
            message: Some("Cancelled stream".to_string()),
        });
    }

    Ok(Ack {
        ok: true,
        message: Some("No active stream for request".to_string()),
    })
}

#[tauri::command]
pub async fn keys_set(state: State<'_, AppState>, keys: KeysInput) -> Result<Ack, String> {
    state.key_store.set_keys(keys)?;
    Ok(Ack {
        ok: true,
        message: Some("Keys saved to OS keychain".to_string()),
    })
}

#[tauri::command]
pub async fn keys_get_masked(state: State<'_, AppState>) -> Result<KeyPresence, String> {
    state.key_store.key_presence()
}

#[tauri::command]
pub async fn keys_clear(state: State<'_, AppState>) -> Result<Ack, String> {
    state.key_store.clear_keys()?;
    Ok(Ack {
        ok: true,
        message: Some("Keys cleared".to_string()),
    })
}
