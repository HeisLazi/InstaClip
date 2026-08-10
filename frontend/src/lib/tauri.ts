/**
 * Helpers for talking to the Tauri shell. Everything degrades to a no-op
 * when the app runs in plain browser preview.
 */

import type { UnlistenFn } from "@tauri-apps/api/event";

export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/** Open an OAuth or documentation URL in the user's normal browser. */
export async function openExternalUrl(url: string): Promise<void> {
  if (isTauri()) {
    const { open } = await import("@tauri-apps/plugin-shell");
    await open(url);
    return;
  }
  const popup = window.open(url, "_blank", "noopener,noreferrer");
  if (!popup) window.location.assign(url);
}

/**
 * Open a native file picker, return the chosen absolute path or null.
 * In browser preview returns null (caller should fall back to <input type=file>).
 */
export async function pickVodFile(): Promise<string | null> {
  if (!isTauri()) return null;
  const { open } = await import("@tauri-apps/plugin-dialog");
  const choice = await open({
    multiple: false,
    filters: [
      { name: "Video", extensions: ["mp4", "mkv", "mov", "avi", "flv", "webm"] },
    ],
  });
  if (!choice || Array.isArray(choice)) return null;
  return choice as string;
}

/**
 * Listen for native drag-drop events on the Tauri window.
 * The callback receives the list of absolute file paths the user dropped.
 * Returns an unlisten function; if not in Tauri it returns a no-op.
 */
export async function onTauriDrop(
  cb: (paths: string[]) => void,
): Promise<UnlistenFn> {
  if (!isTauri()) {
    return () => {};
  }
  const { getCurrentWebview } = await import("@tauri-apps/api/webview");
  const webview = getCurrentWebview();
  return webview.onDragDropEvent((event) => {
    if (event.payload.type === "drop") {
      cb(event.payload.paths as string[]);
    }
  });
}

/**
 * Backend sidecar control. These commands are implemented in src-tauri/src/lib.rs.
 * In browser dev mode they throw — callers should check isTauri() first.
 */
export interface BackendShellStatus {
  running: boolean;
  pid: number | null;
}

async function invokeBackend(cmd: "backend_status" | "start_backend" | "stop_backend" | "restart_backend"): Promise<BackendShellStatus> {
  if (!isTauri()) {
    throw new Error("Backend control is only available in the native app. Launch start_backend.ps1 manually.");
  }
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<BackendShellStatus>(cmd);
}

export const backendShell = {
  status:  () => invokeBackend("backend_status"),
  start:   () => invokeBackend("start_backend"),
  stop:    () => invokeBackend("stop_backend"),
  restart: () => invokeBackend("restart_backend"),
};
