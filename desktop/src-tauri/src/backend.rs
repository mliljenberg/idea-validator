use std::collections::VecDeque;
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::{Arc, Mutex};

use reqwest::Client;
use serde::Deserialize;
use serde_json::json;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::{Child, Command};
use tokio::time::{sleep, Duration};

use crate::keyring_store::KeyEnv;
use crate::types::{BackendStartConfig, BackendStatus, SessionMeta};

const DEFAULT_HOST: &str = "127.0.0.1";
const DEFAULT_PORT: u16 = 8765;
const STARTUP_RETRIES: u16 = 16;
const MAX_LOG_LINES: usize = 200;
const LOG_TAIL_LINES: usize = 40;

#[derive(Debug)]
pub struct BackendManager {
    child: Option<Child>,
    host: String,
    port: u16,
    repo_root: PathBuf,
    app_name: Option<String>,
    log_lines: Arc<Mutex<VecDeque<String>>>,
    last_error: Option<String>,
}

impl Default for BackendManager {
    fn default() -> Self {
        Self {
            child: None,
            host: DEFAULT_HOST.to_string(),
            port: DEFAULT_PORT,
            repo_root: discover_repo_root(),
            app_name: None,
            log_lines: Arc::new(Mutex::new(VecDeque::with_capacity(MAX_LOG_LINES))),
            last_error: None,
        }
    }
}

impl BackendManager {
    pub async fn start(
        &mut self,
        config: Option<BackendStartConfig>,
        keys: &KeyEnv,
    ) -> Result<BackendStatus, String> {
        let mut force_restart = false;
        if let Some(cfg) = config {
            if let Some(host) = cfg.host {
                self.host = host;
            }
            if let Some(port) = cfg.port {
                self.port = port;
            }
            if let Some(repo_root) = cfg.repo_root {
                self.repo_root = PathBuf::from(repo_root);
            }
            force_restart = cfg.force_restart.unwrap_or(false);
        }

        let (current, _) = self.status().await?;
        if current.running && current.health && !force_restart {
            return Ok(current);
        }

        self.stop().await?;
        self.last_error = None;
        self.clear_logs();

        let start_port = self.port;
        let mut startup_error: Option<String> = None;

        for offset in 0..STARTUP_RETRIES {
            let candidate_port = start_port + offset;
            if !is_port_available(&self.host, candidate_port) {
                startup_error = Some(format!(
                    "Port {} is already in use on host {}. Trying next port.",
                    candidate_port, self.host
                ));
                continue;
            }

            let child = match spawn_backend(
                &self.host,
                candidate_port,
                &self.repo_root,
                keys,
                self.log_lines.clone(),
            )
            .await
            {
                Ok(child) => child,
                Err(err) => {
                    if err.contains("No such file or directory") {
                        return Err(
                            "`uv` not found. Install uv and ensure it is on PATH before starting desktop backend."
                                .to_string(),
                        );
                    }
                    startup_error = Some(err);
                    continue;
                }
            };

            if await_health(&self.host, candidate_port).await {
                self.child = Some(child);
                self.port = candidate_port;

                let apps = self.list_apps().await.unwrap_or_default();
                self.app_name = choose_default_app(&apps);

                let (status, _) = self.status().await?;
                return Ok(status);
            }

            let mut child = child;
            let startup_failure = match child.try_wait() {
                Ok(Some(exit_status)) => {
                    format!("Backend exited during startup (status: {exit_status}).")
                }
                Ok(None) => format!(
                    "Backend did not become healthy at http://{}:{} within startup timeout.",
                    self.host, candidate_port
                ),
                Err(err) => format!("Failed to inspect backend process during startup: {err}"),
            };

            let detailed = self.compose_error_with_log_tail(startup_failure);
            self.last_error = Some(detailed.clone());
            startup_error = Some(detailed);

            let _ = child.kill().await;
            let _ = child.wait().await;
        }

        Err(startup_error.unwrap_or_else(|| {
            "Failed to start ADK web backend after retries. Check logs and API keys.".to_string()
        }))
    }

    pub async fn stop(&mut self) -> Result<(), String> {
        if let Some(mut child) = self.child.take() {
            let _ = child.kill().await;
            let _ = child.wait().await;
        }
        self.app_name = None;
        self.last_error = None;
        self.clear_logs();
        Ok(())
    }

    pub async fn status(&mut self) -> Result<(BackendStatus, bool), String> {
        let mut exited = false;

        if let Some(child) = self.child.as_mut() {
            match child.try_wait() {
                Ok(Some(exit_status)) => {
                    self.child = None;
                    self.app_name = None;
                    self.last_error = Some(self.compose_error_with_log_tail(format!(
                        "Local backend process exited unexpectedly (status: {exit_status})."
                    )));
                    exited = true;
                }
                Ok(None) => {}
                Err(err) => return Err(format!("Failed to check backend process status: {err}")),
            }
        }

        let running = self.child.is_some();
        let health = if running {
            health_check(&self.base_url()).await
        } else {
            false
        };

        Ok((
            BackendStatus {
                running,
                port: self.port,
                health,
                app_name: self.app_name.clone(),
                host: self.host.clone(),
                base_url: self.base_url(),
                last_error: self.last_error.clone(),
            },
            exited,
        ))
    }

    pub fn base_url(&self) -> String {
        format!("http://{}:{}", self.host, self.port)
    }

    pub fn app_name(&self) -> Option<String> {
        self.app_name.clone()
    }

    pub fn set_app_name(&mut self, app_name: Option<String>) {
        self.app_name = app_name;
    }

    fn clear_logs(&self) {
        if let Ok(mut logs) = self.log_lines.lock() {
            logs.clear();
        }
    }

    fn log_tail(&self, limit: usize) -> String {
        if let Ok(logs) = self.log_lines.lock() {
            if logs.is_empty() {
                return String::new();
            }
            let lines: Vec<&str> = logs
                .iter()
                .rev()
                .take(limit)
                .collect::<Vec<_>>()
                .into_iter()
                .rev()
                .map(String::as_str)
                .collect();
            return lines.join("\n");
        }
        String::new()
    }

    fn compose_error_with_log_tail(&self, base_message: String) -> String {
        let tail = self.log_tail(LOG_TAIL_LINES);
        if tail.is_empty() {
            return base_message;
        }

        format!("{base_message}\nRecent backend logs:\n{tail}")
    }

    pub async fn list_apps(&self) -> Result<Vec<String>, String> {
        let url = format!("{}/list-apps", self.base_url());
        let response = client()
            .get(url)
            .send()
            .await
            .map_err(|e| format!("Failed to call /list-apps: {e}"))?;

        if !response.status().is_success() {
            return Err(format!("/list-apps returned HTTP {}", response.status()));
        }

        response
            .json::<Vec<String>>()
            .await
            .map_err(|e| format!("Failed to parse /list-apps response: {e}"))
    }

    pub async fn create_session(
        &self,
        app_name: &str,
        user_id: &str,
        session_id: Option<&str>,
    ) -> Result<SessionMeta, String> {
        let url = format!(
            "{}/apps/{}/users/{}/sessions",
            self.base_url(),
            app_name,
            user_id
        );

        let body = if let Some(session_id) = session_id {
            json!({ "sessionId": session_id })
        } else {
            json!({})
        };

        let response = client()
            .post(url)
            .json(&body)
            .send()
            .await
            .map_err(|e| format!("Failed to create session: {e}"))?;

        if !response.status().is_success() {
            return Err(format!("Session create failed with HTTP {}", response.status()));
        }

        let session: SessionResponse = response
            .json()
            .await
            .map_err(|e| format!("Invalid session response: {e}"))?;

        Ok(session.into())
    }

    pub async fn list_sessions(&self, app_name: &str, user_id: &str) -> Result<Vec<SessionMeta>, String> {
        let url = format!(
            "{}/apps/{}/users/{}/sessions",
            self.base_url(),
            app_name,
            user_id
        );

        let response = client()
            .get(url)
            .send()
            .await
            .map_err(|e| format!("Failed to list sessions: {e}"))?;

        if !response.status().is_success() {
            return Err(format!("Session list failed with HTTP {}", response.status()));
        }

        let sessions: Vec<SessionResponse> = response
            .json()
            .await
            .map_err(|e| format!("Invalid session list response: {e}"))?;

        Ok(sessions.into_iter().map(Into::into).collect())
    }
}

fn client() -> Client {
    Client::builder()
        .timeout(Duration::from_secs(30))
        .build()
        .expect("reqwest client should build")
}

async fn spawn_backend(
    host: &str,
    port: u16,
    repo_root: &Path,
    keys: &KeyEnv,
    log_lines: Arc<Mutex<VecDeque<String>>>,
) -> Result<Child, String> {
    let mut cmd = Command::new("uv");
    cmd.args([
        "run",
        "adk",
        "web",
        ".",
        "--host",
        host,
        "--port",
        &port.to_string(),
    ])
    .current_dir(repo_root)
    .stdin(Stdio::null())
    .stdout(Stdio::piped())
    .stderr(Stdio::piped());

    if let Some(v) = &keys.google_api_key {
        cmd.env("GOOGLE_API_KEY", v);
    }
    if let Some(v) = &keys.brave_api_key {
        cmd.env("BRAVE_SEARCH_API_KEY", v);
    }
    if let Some(v) = &keys.gemini_api_key {
        cmd.env("GEMINI_API_KEY", v);
    }

    let mut child = cmd
        .spawn()
        .map_err(|e| format!("Failed to spawn backend process: {e}"))?;

    if let Some(stdout) = child.stdout.take() {
        spawn_log_reader(stdout, log_lines.clone(), "stdout");
    }
    if let Some(stderr) = child.stderr.take() {
        spawn_log_reader(stderr, log_lines, "stderr");
    }

    Ok(child)
}

fn spawn_log_reader<R>(reader: R, log_lines: Arc<Mutex<VecDeque<String>>>, stream: &'static str)
where
    R: tokio::io::AsyncRead + Unpin + Send + 'static,
{
    tokio::spawn(async move {
        let mut lines = BufReader::new(reader).lines();
        loop {
            match lines.next_line().await {
                Ok(Some(line)) => push_log_line(&log_lines, format!("[{stream}] {line}")),
                Ok(None) => break,
                Err(err) => {
                    push_log_line(&log_lines, format!("[{stream}] <read error: {err}>"));
                    break;
                }
            }
        }
    });
}

fn push_log_line(log_lines: &Arc<Mutex<VecDeque<String>>>, line: String) {
    if passthrough_backend_logs_enabled() {
        eprintln!("[backend] {line}");
    }

    if let Ok(mut logs) = log_lines.lock() {
        if logs.len() >= MAX_LOG_LINES {
            let _ = logs.pop_front();
        }
        logs.push_back(line);
    }
}

fn passthrough_backend_logs_enabled() -> bool {
    matches!(
        std::env::var("PV_DESKTOP_BACKEND_STDIO")
            .unwrap_or_default()
            .to_ascii_lowercase()
            .as_str(),
        "1" | "true" | "yes" | "on"
    )
}

fn is_port_available(host: &str, port: u16) -> bool {
    TcpListener::bind((host, port)).is_ok()
}

async fn await_health(host: &str, port: u16) -> bool {
    let base_url = format!("http://{}:{}", host, port);
    for _ in 0..48u8 {
        if health_check(&base_url).await {
            return true;
        }
        sleep(Duration::from_millis(250)).await;
    }
    false
}

async fn health_check(base_url: &str) -> bool {
    let url = format!("{base_url}/health");
    match client().get(url).send().await {
        Ok(response) => response.status().is_success(),
        Err(_) => false,
    }
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct SessionResponse {
    id: String,
    app_name: String,
    user_id: String,
    last_update_time: Option<f64>,
}

impl From<SessionResponse> for SessionMeta {
    fn from(value: SessionResponse) -> Self {
        Self {
            id: value.id,
            app_name: value.app_name,
            user_id: value.user_id,
            last_update_time: value.last_update_time,
        }
    }
}

pub fn choose_default_app(apps: &[String]) -> Option<String> {
    if apps.is_empty() {
        return None;
    }

    if apps.iter().any(|name| name == "product_validator_search") {
        return Some("product_validator_search".to_string());
    }

    let filtered = apps
        .iter()
        .find(|name| !matches!(name.as_str(), "reports" | "tests" | "desktop"));

    filtered
        .map(|name| name.to_string())
        .or_else(|| apps.first().cloned())
}

fn discover_repo_root() -> PathBuf {
    let current = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));

    if current.join("product_validator_search").exists() {
        return current;
    }

    let mut cursor = current.clone();
    for _ in 0..6 {
        if cursor.join("product_validator_search").exists() {
            return cursor;
        }
        if !cursor.pop() {
            break;
        }
    }

    current
}

pub fn run_fallback_url(base_url: &str) -> String {
    format!("{base_url}/run")
}

pub fn run_sse_url(base_url: &str) -> String {
    format!("{base_url}/run_sse")
}

#[cfg(test)]
mod tests {
    use super::choose_default_app;

    #[test]
    fn picks_product_validator_search_if_present() {
        let apps = vec!["reports".to_string(), "product_validator_search".to_string()];
        assert_eq!(choose_default_app(&apps).as_deref(), Some("product_validator_search"));
    }

    #[test]
    fn falls_back_to_non_auxiliary_app() {
        let apps = vec!["reports".to_string(), "tests".to_string(), "demo_agent".to_string()];
        assert_eq!(choose_default_app(&apps).as_deref(), Some("demo_agent"));
    }

    #[test]
    fn falls_back_to_first_when_only_aux_apps_exist() {
        let apps = vec!["reports".to_string(), "tests".to_string()];
        assert_eq!(choose_default_app(&apps).as_deref(), Some("reports"));
    }
}
