//! InstaClip Tauri shell.
//!
//! Responsibilities:
//!   1. Spawn the Python FastAPI backend on app start (sidecar).
//!   2. Expose `start_backend` / `restart_backend` / `stop_backend` / `backend_status`
//!      commands so the React UI can control the sidecar from the status bar.
//!   3. Kill the backend cleanly when the main window closes.

use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

use serde::Serialize;
use tauri::{Manager, RunEvent, State};

/// Holds the backend child handle so we can kill / restart it on demand.
struct BackendProcess(Mutex<Option<Child>>);

const BACKEND_PORT: u16 = 8765;

fn backend_port_open() -> bool {
    let address = std::net::SocketAddr::from(([127, 0, 0, 1], BACKEND_PORT));
    std::net::TcpStream::connect_timeout(&address, Duration::from_millis(150)).is_ok()
}

#[cfg(windows)]
fn listening_pids() -> Vec<u32> {
    use std::os::windows::process::CommandExt;

    let output = Command::new("netstat")
        .args(["-ano", "-p", "tcp"])
        .creation_flags(0x08000000)
        .output();
    let Ok(output) = output else {
        return Vec::new();
    };

    String::from_utf8_lossy(&output.stdout)
        .lines()
        .filter_map(|line| {
            let columns: Vec<_> = line.split_whitespace().collect();
            if columns.len() < 5
                || !columns[1].ends_with(&format!(":{BACKEND_PORT}"))
                || !columns[3].eq_ignore_ascii_case("LISTENING")
            {
                return None;
            }
            columns.last()?.parse::<u32>().ok()
        })
        .collect()
}

#[cfg(not(windows))]
fn listening_pids() -> Vec<u32> {
    Vec::new()
}

fn listening_pid() -> Option<u32> {
    listening_pids().into_iter().next()
}

#[cfg(windows)]
fn kill_port_owners() -> Result<(), String> {
    use std::os::windows::process::CommandExt;

    for pid in listening_pids() {
        log::info!("Killing process pid={pid} listening on port {BACKEND_PORT}");
        let _ = Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .creation_flags(0x08000000)
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }
    // taskkill can return before Windows removes the listening socket. Wait for
    // the actual port state so restart cannot race the old backend's shutdown.
    for _ in 0..30 {
        if !backend_port_open() {
            return Ok(());
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    Err(format!(
        "Port {BACKEND_PORT} is still occupied. Close the process using it and retry."
    ))
}

#[cfg(not(windows))]
fn kill_port_owners() -> Result<(), String> {
    Ok(())
}

fn locate_python() -> PathBuf {
    // 1. Honour INSTACLIP_PYTHON if the user set it (e.g. a venv).
    if let Ok(p) = std::env::var("INSTACLIP_PYTHON") {
        return PathBuf::from(p);
    }
    // 2. Default to the system Python on Windows.
    #[cfg(windows)]
    {
        let candidate = PathBuf::from(format!(
            "{}\\AppData\\Local\\Programs\\Python\\Python312\\python.exe",
            std::env::var("USERPROFILE").unwrap_or_default()
        ));
        if candidate.exists() {
            return candidate;
        }
    }
    PathBuf::from("python")
}

fn locate_backend_sidecar() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let parent = exe.parent()?;
    let candidates = [
        parent.join("instaclip-backend.exe"),
        parent.join("instaclip-backend-x86_64-pc-windows-msvc.exe"),
        parent.join("binaries").join("instaclip-backend.exe"),
        parent.join("binaries").join("instaclip-backend-x86_64-pc-windows-msvc.exe"),
    ];
    candidates.into_iter().find(|candidate| candidate.exists())
}

fn project_root() -> PathBuf {
    // Allow an installed launcher to target a movable checkout explicitly.
    if let Ok(root) = std::env::var("INSTACLIP_ROOT") {
        let candidate = PathBuf::from(root);
        if candidate.join("config/settings.json").exists() {
            return candidate;
        }
    }

    let exe = std::env::current_exe().unwrap_or_default();
    if let Some(parent) = exe.parent() {
        if parent.join("config/settings.json").exists() {
            return parent.to_path_buf();
        }
    }
    // Dev mode: walk up to the source root.
    let here = std::env::current_dir().unwrap_or_default();
    let mut cursor = here.clone();
    for _ in 0..5 {
        if cursor.join("config/settings.json").exists() {
            return cursor;
        }
        if let Some(p) = cursor.parent() {
            cursor = p.to_path_buf();
        } else {
            break;
        }
    }

    // The installer is a lightweight launcher and intentionally does not copy
    // the user's multi-gigabyte clips/models into Program Files. On this build
    // machine, retain the checkout used to compile the launcher as a fallback.
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    if let Some(compiled_root) = manifest_dir.parent().and_then(|path| path.parent()) {
        if compiled_root.join("config/settings.json").exists() {
            return compiled_root.to_path_buf();
        }
    }

    here
}

fn spawn_backend() -> Result<Child, String> {
    // Keep this guarantee inside the spawn helper as well as the public
    // commands. It closes the race between a health check and process launch.
    kill_port_owners()?;
    let sidecar = locate_backend_sidecar();
    let python = locate_python();
    let root = project_root();
    let mut cmd = if let Some(path) = sidecar.as_ref() {
        log::info!("Spawning bundled clipper backend: {:?}", path);
        let mut command = Command::new(path);
        command.env("INSTACLIP_EDITION", "clipper");
        if let Some(parent) = path.parent() {
            let inherited = std::env::var_os("PATH").unwrap_or_default();
            let mut paths = vec![parent.to_path_buf()];
            paths.extend(std::env::split_paths(&inherited));
            if let Ok(joined) = std::env::join_paths(paths) {
                command.env("PATH", joined);
            }
        }
        command
    } else {
        log::info!("Spawning development backend: {:?} cwd={:?}", python, root);
        let mut command = Command::new(&python);
        command.arg("-m").arg("backend.main").arg("--port").arg("8765").current_dir(&root);
        command
    };
    cmd.stdout(Stdio::inherit()).stderr(Stdio::inherit());

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        // CREATE_NO_WINDOW — no popup console for the sidecar.
        cmd.creation_flags(0x08000000);
    }

    cmd.spawn().map_err(|e| {
        let msg = format!(
            "Failed to spawn backend using {}: {}. Reinstall the clipping beta or set INSTACLIP_PYTHON for development.",
            sidecar.as_ref().unwrap_or(&python).display(),
            e
        );
        log::error!("{msg}");
        msg
    })
}

/// True if the stored child is still running.
fn child_alive(child: &mut Child) -> bool {
    match child.try_wait() {
        Ok(None) => true,     // still running
        Ok(Some(_)) => false, // exited
        Err(_) => false,
    }
}

#[derive(Serialize, Clone)]
struct BackendStatus {
    running: bool,
    pid: Option<u32>,
}

#[tauri::command]
fn backend_status(state: State<BackendProcess>) -> BackendStatus {
    let mut guard = state.0.lock().unwrap();
    if let Some(child) = guard.as_mut() {
        if child_alive(child) {
            return BackendStatus {
                running: true,
                pid: Some(child.id()),
            };
        }
        // Stale handle — child died externally.
        *guard = None;
    }
    BackendStatus {
        running: backend_port_open(),
        pid: listening_pid(),
    }
}

#[tauri::command]
fn start_backend(state: State<BackendProcess>) -> Result<BackendStatus, String> {
    let mut guard = state.0.lock().unwrap();
    if let Some(child) = guard.as_mut() {
        if child_alive(child) {
            log::info!("start_backend: already running (pid {})", child.id());
            return Ok(BackendStatus {
                running: true,
                pid: Some(child.id()),
            });
        }
        *guard = None;
    }
    // The UI uses Start when its HTTP health check is failing. A process may
    // still own the port without serving correctly, so replace untracked
    // listeners instead of reporting a false successful start.
    if backend_port_open() {
        kill_port_owners()?;
    }
    let child = spawn_backend()?;
    let pid = child.id();
    *guard = Some(child);
    Ok(BackendStatus {
        running: true,
        pid: Some(pid),
    })
}

fn kill_locked(guard: &mut std::sync::MutexGuard<'_, Option<Child>>) {
    if let Some(mut child) = guard.take() {
        log::info!("stop_backend: killing pid {}", child.id());
        let _ = child.kill();
        let _ = child.wait();
    }
}

#[tauri::command]
fn stop_backend(state: State<BackendProcess>) -> Result<BackendStatus, String> {
    let mut guard = state.0.lock().unwrap();
    kill_locked(&mut guard);
    kill_port_owners()?;
    Ok(BackendStatus {
        running: false,
        pid: None,
    })
}

#[tauri::command]
fn restart_backend(state: State<BackendProcess>) -> Result<BackendStatus, String> {
    let mut guard = state.0.lock().unwrap();
    kill_locked(&mut guard);
    // A backend launched by a batch file or an older app instance is not in
    // our child handle. Clear the actual port owner before spawning fresh code.
    kill_port_owners()?;
    let child = spawn_backend()?;
    let pid = child.id();
    *guard = Some(child);
    Ok(BackendStatus {
        running: true,
        pid: Some(pid),
    })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .manage(BackendProcess(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![
            backend_status,
            start_backend,
            stop_backend,
            restart_backend,
        ])
        .setup(|app| {
            let handle = app.handle();
            let backend = handle.state::<BackendProcess>();
            if backend_port_open() {
                log::info!(
                    "Backend already listening on port {BACKEND_PORT} (pid {:?}); leaving it running.",
                    listening_pid()
                );
                return Ok(());
            }
            match spawn_backend() {
                Ok(child) => {
                    *backend.0.lock().unwrap() = Some(child);
                }
                Err(e) => {
                    log::warn!(
                        "Auto-start of backend failed ({e}); user can retry via the status bar button."
                    );
                }
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|handle, event| {
            if let RunEvent::ExitRequested { .. } | RunEvent::Exit = event {
                let child_opt = {
                    let backend = handle.state::<BackendProcess>();
                    let x = backend.0.lock().unwrap().take(); x
                };
                if let Some(mut child) = child_opt {
                    log::info!("Killing backend pid={}", child.id());
                    let _ = child.kill();
                }
            }
        });
}

#[cfg(all(test, windows))]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::os::windows::process::CommandExt;
    use std::thread;

    fn edit_sounds_healthy() -> bool {
        let Ok(mut stream) = std::net::TcpStream::connect(("127.0.0.1", BACKEND_PORT)) else {
            return false;
        };
        let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
        if stream
            .write_all(b"GET /edit/sounds HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
            .is_err()
        {
            return false;
        }
        let mut response = String::new();
        stream.read_to_string(&mut response).is_ok() && response.starts_with("HTTP/1.1 200")
    }

    #[test]
    #[ignore = "binds port 8765 and terminates its listener; run explicitly"]
    fn spawn_replaces_untracked_port_owner() {
        kill_port_owners().expect("port must be free before test");
        let mut stale = Command::new(locate_python())
            .args(["-m", "http.server", "8765", "--bind", "127.0.0.1"])
            .creation_flags(0x08000000)
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("start untracked listener");
        for _ in 0..30 {
            if backend_port_open() {
                break;
            }
            thread::sleep(Duration::from_millis(100));
        }
        assert!(backend_port_open(), "untracked listener did not bind");

        let mut backend = spawn_backend().expect("spawn must replace untracked listener");
        let mut healthy = false;
        for _ in 0..100 {
            if edit_sounds_healthy() {
                healthy = true;
                break;
            }
            thread::sleep(Duration::from_millis(200));
        }
        assert!(healthy, "replacement backend never served /edit/sounds");
        assert!(
            matches!(stale.try_wait(), Ok(Some(_))),
            "untracked listener survived"
        );

        let _ = backend.kill();
        let _ = backend.wait();
        kill_port_owners().expect("test backend must stop cleanly");
    }
}
