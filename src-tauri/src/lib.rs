mod commands;
mod sidecar;
use commands::default::{read, write};
use sidecar::{BackendState, DevChild, SidecarChild};
use std::sync::Mutex;

#[allow(clippy::missing_panics_doc)]
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(BackendState(Mutex::new(None)))
        .manage(SidecarChild(Mutex::new(None)))
        .manage(DevChild(Mutex::new(None)))
        .setup(|app| {
            // Always on, including release builds: sidecar spawn/health/
            // shutdown diagnostics must be visible in production too.
            // Default targets: stdout + a rotating file in the OS log dir.
            app.handle().plugin(
                tauri_plugin_log::Builder::default()
                    .level(log::LevelFilter::Info)
                    .build(),
            )?;
            sidecar::spawn(app.handle())?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            read,
            write,
            sidecar::get_backend,
            sidecar::shutdown_backend
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit = event {
                sidecar::shutdown(app);
            }
        });
}
