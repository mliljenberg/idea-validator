#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod backend;
mod commands;
mod keyring_store;
mod session_store;
mod stream;
mod types;

use commands::AppState;
use tauri::{Manager, RunEvent};

fn main() {
    tauri::Builder::default()
        .manage(AppState::new())
        .invoke_handler(tauri::generate_handler![
            commands::backend_start,
            commands::backend_stop,
            commands::backend_status,
            commands::backend_list_apps,
            commands::session_create,
            commands::session_list,
            commands::session_delete,
            commands::session_messages_get,
            commands::session_messages_append,
            commands::session_phase_get,
            commands::session_phase_set,
            commands::stream_run,
            commands::stream_cancel,
            commands::keys_set,
            commands::keys_get_masked,
            commands::keys_clear,
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if matches!(event, RunEvent::Exit | RunEvent::ExitRequested { .. }) {
                let state = app_handle.state::<AppState>();
                let backend = state.backend.clone();
                tauri::async_runtime::block_on(async move {
                    let mut manager = backend.lock().await;
                    let _ = manager.stop().await;
                });
            }
        });
}
