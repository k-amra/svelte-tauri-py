//! Python sidecar lifecycle: spawn → READY handshake → managed state → shutdown.
//!
//! Contract with `src-python/app/main.py`:
//! - Rust spawns the backend with `SIDECAR_TOKEN=<t> --data-dir <dir> --port 0`.
//! - Python binds 127.0.0.1:0, prints exactly `READY <port>` (flush=True).
//! - Rust polls `GET /health`, stores `{port, token}`, emits `backend-ready`.
//! - Frontend calls `invoke("get_backend")` then talks HTTP directly.
//! - Shutdown: `POST /shutdown` (primary) + kill fallback.
//!   (PyInstaller onefile/one-dir bootloader PID games make kill unreliable alone.)
//!
//! Dev mode: `SIDECAR_DEV=1` spawns `uv run python -m app.main ...` via
//! `std::process` (hot reload, no PyInstaller cycle, no capability needed).

use std::{
    io::{BufRead, BufReader},
    sync::Mutex,
    time::{Duration, Instant},
};

use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

pub struct Backend {
    pub port: u16,
    pub token: String,
}

/// None until the READY line + /health succeed.
pub struct BackendState(pub Mutex<Option<Backend>>);

/// Kept so we can kill on exit as a fallback after POST /shutdown.
pub struct SidecarChild(pub Mutex<Option<CommandChild>>);

/// Holds the std::process::Child for dev-mode so we can kill it on exit.
pub struct DevChild(pub Mutex<Option<std::process::Child>>);

fn app_data_dir(app: &AppHandle) -> String {
    let dir = app
        .path()
        .app_data_dir()
        .unwrap_or_else(|_| std::env::temp_dir().join("api-server"));
    let _ = std::fs::create_dir_all(&dir);
    dir.to_string_lossy().to_string()
}

/// Minimal blocking GET http://127.0.0.1:port/health (no extra deps).
fn health_ok(port: u16) -> bool {
    let Ok(mut stream) = std::net::TcpStream::connect_timeout(
        &format!("127.0.0.1:{port}").parse().unwrap(),
        Duration::from_millis(500),
    ) else {
        return false;
    };
    stream
        .set_read_timeout(Some(Duration::from_millis(1000)))
        .ok();
    let req =
        format!("GET /health HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n");
    if std::io::Write::write_all(&mut stream, req.as_bytes()).is_err() {
        return false;
    }
    let mut reader = BufReader::new(&stream);
    let mut status = String::new();
    if reader.read_line(&mut status).is_err() {
        return false;
    }
    status.contains("200")
}

fn wait_for_health(port: u16, timeout: Duration) -> bool {
    let start = Instant::now();
    while start.elapsed() < timeout {
        if health_ok(port) {
            return true;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    false
}

/// Minimal blocking POST http://127.0.0.1:port/shutdown with bearer token.
fn post_shutdown(port: u16, token: &str) {
    let addr: std::net::SocketAddr = match format!("127.0.0.1:{port}").parse() {
        Ok(a) => a,
        Err(_) => return,
    };
    let Ok(mut stream) = std::net::TcpStream::connect_timeout(&addr, Duration::from_millis(800))
    else {
        return;
    };
    stream
        .set_read_timeout(Some(Duration::from_millis(1500)))
        .ok();
    stream
        .set_write_timeout(Some(Duration::from_millis(1500)))
        .ok();
    let req = format!(
        "POST /shutdown HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\nAuthorization: Bearer {token}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
    );
    let _ = std::io::Write::write_all(&mut stream, req.as_bytes());
    // Best effort: read (and discard) the response so the server can close gracefully.
    let mut buf = [0u8; 512];
    use std::io::Read as _;
    let _ = stream.read(&mut buf);
}

/// Minimal blocking GET, returns the response status line (e.g. "HTTP/1.0 200 OK").
/// Used by `probe_backend` diagnostics: answers the question "is the server
/// alive as seen from Rust?" independent of the WebView's fetch().
fn http_get(port: u16, token: Option<&str>, path: &str) -> Result<String, String> {
    let addr: std::net::SocketAddr = format!("127.0.0.1:{port}")
        .parse()
        .map_err(|e| format!("bad addr: {e}"))?;
    let mut stream = std::net::TcpStream::connect_timeout(&addr, Duration::from_millis(1500))
        .map_err(|e| format!("connect failed: {e}"))?;
    stream
        .set_read_timeout(Some(Duration::from_millis(3000)))
        .ok();
    stream
        .set_write_timeout(Some(Duration::from_millis(3000)))
        .ok();
    let auth = token
        .map(|t| format!("Authorization: Bearer {t}\r\n"))
        .unwrap_or_default();
    let req =
        format!("GET {path} HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\n{auth}Connection: close\r\n\r\n");
    std::io::Write::write_all(&mut stream, req.as_bytes())
        .map_err(|e| format!("write failed: {e}"))?;
    let mut reader = BufReader::new(&stream);
    let mut status = String::new();
    reader
        .read_line(&mut status)
        .map_err(|e| format!("read failed: {e}"))?;
    Ok(status.trim().to_string())
}

/// Diagnostics probe for the in-app Diagnostics panel: checks the sidecar
/// from the Rust side (raw TCP, no WebView involved). If this is green but the
/// UI's fetch() fails, the problem is between WebView and localhost
/// (proxy, antivirus loopback filter, firewall) — not the Python server.
#[tauri::command]
pub fn probe_backend(state: tauri::State<'_, BackendState>) -> serde_json::Value {
    let guard = state.0.lock().unwrap_or_else(|e| e.into_inner());
    let Some(b) = guard.as_ref() else {
        return serde_json::json!({ "configured": false, "hint": "READY not received yet" });
    };
    let port = b.port;
    let token = b.token.clone();
    drop(guard);
    serde_json::json!({
        "configured": true,
        "port": port,
        "rust_health": http_get(port, None, "/health").unwrap_or_else(|e| format!("ERROR {e}")),
        "rust_scripts": http_get(port, Some(&token), "/api/scripts").unwrap_or_else(|e| format!("ERROR {e}")),
    })
}

fn on_ready(app: &AppHandle, port: u16, token: String) {
    log::info!("sidecar READY on port {port}");
    if !wait_for_health(port, Duration::from_secs(10)) {
        log::error!("sidecar on port {port} never passed /health");
        return;
    }
    if let Some(state) = app.try_state::<BackendState>() {
        *state.0.lock().unwrap_or_else(|e| e.into_inner()) = Some(Backend {
            port,
            token: token.clone(),
        });
    }
    let _ = app.emit("backend-ready", port);
}

fn parse_ready_line(line: &str) -> Option<u16> {
    line.strip_prefix("READY ")
        .and_then(|p| p.trim().parse().ok())
}

/// Spawn via std::process for `SIDECAR_DEV=1` (uv + hot reload).
fn spawn_dev(app: &AppHandle, token: &str, data_dir: &str) {
    let mut cmd = std::process::Command::new("uv");
    cmd.args([
        "run",
        "--project",
        "src-python",
        "python",
        "-m",
        "app.main",
        "--data-dir",
        data_dir,
        "--port",
        "0",
    ]);
    cmd.env("SIDECAR_TOKEN", token);
    cmd.stdout(std::process::Stdio::piped());
    cmd.stderr(std::process::Stdio::inherit());
    // Run from the project root (one above src-tauri) when in `tauri dev`.
    if let Ok(cwd) = std::env::current_dir() {
        // cwd is usually src-tauri when spawned by the CLI; go up one.
        let root = if cwd.file_name().is_some_and(|n| n == "src-tauri") {
            cwd.join("..")
        } else {
            cwd
        };
        cmd.current_dir(root);
    }
    let Ok(mut child) = cmd.spawn() else {
        log::error!(
            "SIDECAR_DEV: failed to spawn `uv run python -m app.main` (is uv installed?)"
        );
        return;
    };

    // Take stdout out BEFORE storing the child handle.
    let stdout = child.stdout.take().expect("piped stdout");

    // Store the child so shutdown() can kill it as a fallback.
    if let Some(state) = app.try_state::<DevChild>() {
        *state.0.lock().unwrap_or_else(|e| e.into_inner()) = Some(child);
    }

    let handle = app.clone();
    let token = token.to_string();
    std::thread::spawn(move || {
        let reader = BufReader::new(stdout);
        for line in reader.lines().map_while(Result::ok) {
            let line = line.trim().to_string();
            log::debug!("[sidecar-dev] {line}");
            if let Some(port) = parse_ready_line(&line) {
                on_ready(&handle, port, token.clone());
            }
        }
        log::info!("sidecar-dev stdout closed (process likely exited)");
    });
}

/// Spawn the bundled PyInstaller binary via the shell plugin.
fn spawn_bundled(app: &AppHandle, token: &str, data_dir: &str) {
    let (mut rx, child) = match app.shell().sidecar("api-server").and_then(|c| {
        c.env("SIDECAR_TOKEN", token)
            .args(["--data-dir", data_dir, "--port", "0"])
            .spawn()
    }) {
        Ok(v) => v,
        Err(e) => {
            log::error!("failed to spawn sidecar `api-server`: {e} (did you run build:sidecar? check the target-triple suffix)");
            return;
        }
    };
    if let Some(state) = app.try_state::<SidecarChild>() {
        *state.0.lock().unwrap_or_else(|e| e.into_inner()) = Some(child);
    }
    let handle = app.clone();
    let token = token.to_string();
    tauri::async_runtime::spawn(async move {
        let start = Instant::now();
        let timeout = Duration::from_secs(30);
        let mut ready_sent = false;

        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(bytes) => {
                    let line = String::from_utf8_lossy(&bytes);
                    for l in line.lines() {
                        let trimmed = l.trim();
                        if !ready_sent {
                            if let Some(port) = parse_ready_line(trimmed) {
                                let ready_handle = handle.clone();
                                let ready_token = token.clone();
                                std::mem::drop(tauri::async_runtime::spawn_blocking(
                                    move || {
                                        on_ready(&ready_handle, port, ready_token);
                                    },
                                ));
                                ready_sent = true;
                                continue;
                            }
                        }
                        // Keep draining after READY so the pipe never fills up.
                        log::debug!("[sidecar] {trimmed}");
                    }
                }
                CommandEvent::Stderr(bytes) => {
                    log::debug!("[sidecar] {}", String::from_utf8_lossy(&bytes).trim());
                }
                CommandEvent::Terminated(payload) => {
                    log::warn!("sidecar terminated: {:?}", payload.code);
                    if let Some(state) = handle.try_state::<BackendState>() {
                        *state.0.lock().unwrap_or_else(|e| e.into_inner()) = None;
                    }
                    let _ = handle.emit("backend-gone", ());
                    return;
                }
                CommandEvent::Error(e) => {
                    log::error!("sidecar error: {e}");
                    return;
                }
                _ => {}
            }
            if !ready_sent && start.elapsed() > timeout {
                log::error!("timed out waiting for READY from sidecar");
                return;
            }
        }
    });
}

pub fn spawn(app: &AppHandle) -> tauri::Result<()> {
    let token = uuid::Uuid::new_v4().to_string();
    let data_dir = app_data_dir(app);

    if std::env::var("SIDECAR_DEV").is_ok_and(|v| v == "1") {
        log::info!("SIDECAR_DEV=1: spawning python via uv (hot reload)");
        spawn_dev(app, &token, &data_dir);
    } else {
        spawn_bundled(app, &token, &data_dir);
    }
    Ok(())
}

pub fn shutdown(app: &AppHandle) {
    // 1) Graceful: HTTP /shutdown is the PRIMARY mechanism.
    //    (Tauri only knows the bootloader PID for PyInstaller binaries,
    //    so kill() alone orphans the real child.)
    let backend = app.try_state::<BackendState>().and_then(|state| {
        state
            .0
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .as_ref()
            .map(|b| (b.port, b.token.clone()))
    });
    if let Some((port, token)) = backend {
        post_shutdown(port, &token);
    }
    // Give it a beat to exit cleanly, then fallback to kill.
    std::thread::sleep(Duration::from_millis(400));
    if let Some(child_state) = app.try_state::<SidecarChild>() {
        if let Some(child) = child_state
            .0
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .take()
        {
            let _ = child.kill();
        }
    }

    // Kill dev-mode sidecar (std::process::Child) as a fallback.
    if let Some(dev_state) = app.try_state::<DevChild>() {
        if let Some(mut child) = dev_state
            .0
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .take()
        {
            let _ = child.kill();
            let _ = child.wait(); // reap
        }
    }
}

#[tauri::command]
pub fn get_backend(state: tauri::State<'_, BackendState>) -> Result<(u16, String), String> {
    let guard = state.0.lock().unwrap_or_else(|e| e.into_inner());
    guard
        .as_ref()
        .map(|b| (b.port, b.token.clone()))
        .ok_or_else(|| "backend not ready yet".to_string())
}

#[tauri::command]
pub fn shutdown_backend(app: AppHandle) -> Result<(), String> {
    shutdown(&app);
    Ok(())
}
