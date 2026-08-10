/**
 * VS Code–style slim status bar at the bottom of the window.
 * Left:  persistent dependency dots (Ollama, Whisper, ffmpeg, …).
 * Right: active jobs + a chevron that opens the log drawer.
 *
 * Per the redesign doc: this is what replaced the 240px log footer.
 */

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, Activity, MessageCircle, Loader2, Play, RotateCw } from "lucide-react";

import { api, type SystemStatus } from "@/api/client";
import { backendShell, isTauri } from "@/lib/tauri";
import { cn } from "@/lib/utils";

interface StatusBarProps {
  drawerOpen: boolean;
  onToggleDrawer: () => void;
  activeJobs: number;
  chatOpen?: boolean;
  onToggleChat?: () => void;
}

type Dot = "ok" | "warn" | "bad";

function dotColor(d: Dot) {
  return d === "ok"   ? "bg-success"
       : d === "warn" ? "bg-warning"
       :                "bg-destructive";
}

function summarize(s: SystemStatus | undefined) {
  if (!s) {
    return {
      ollama:   { state: "bad" as Dot, label: "Backend loading…" },
      ffmpeg:   { state: "bad" as Dot, label: "—" },
      whisper:  { state: "warn" as Dot, label: "—" },
      vision:   { state: "warn" as Dot, label: "—" },
      profile:  { state: "warn" as Dot, label: "—" },
    };
  }
  const whisperState: Dot =
    s.whisper.device === "cuda" ? "ok" : "warn";
  return {
    ollama:  { state: (s.ollama.alive ? "ok" : "bad") as Dot,
               label: `Ollama: ${s.ollama.alive ? "online" : "offline"}` },
    ffmpeg:  { state: (s.ffmpeg.on_path ? "ok" : "bad") as Dot,
               label: `ffmpeg: ${s.ffmpeg.on_path ? "ready" : "missing from PATH"}` },
    whisper: { state: whisperState,
               label: `Whisper ${s.whisper.model_size} · ${s.whisper.device}` },
    vision:  { state: (s.vision.ok ? "ok" : "warn") as Dot,
               label: `Vision: ${s.vision.model} — ${s.vision.msg}` },
    profile: { state: (s.profile.trained ? "ok" : "warn") as Dot,
               label: s.profile.trained ? "Profile trained" : "No profile yet" },
  };
}

export function StatusBar({ drawerOpen, onToggleDrawer, activeJobs, chatOpen = false, onToggleChat }: StatusBarProps) {
  const qc = useQueryClient();
  const { data, isError } = useQuery({
    queryKey: ["status"],
    queryFn:  api.status.full,
    refetchInterval: 5000,
    retry: false,
  });

  const dots = summarize(data);
  const backendUp = !isError && !!data;
  const tauri = isTauri();
  const [backendBusy, setBackendBusy] = useState<"start" | "restart" | null>(null);
  const [backendError, setBackendError] = useState<string | null>(null);

  async function handleBackendAction(action: "start" | "restart") {
    if (!tauri) {
      setBackendError(
        "Backend control needs the native app. In dev: run Start Backend.bat (or start_backend.ps1).",
      );
      return;
    }
    setBackendError(null);
    setBackendBusy(action);
    try {
      if (action === "restart") {
        await backendShell.restart();
      } else {
        await backendShell.start();
      }
      // Give uvicorn ~1.5s to come up before re-polling status.
      setTimeout(() => qc.invalidateQueries({ queryKey: ["status"] }), 1500);
    } catch (e: any) {
      setBackendError(e?.message ?? "Backend command failed");
    } finally {
      setBackendBusy(null);
    }
  }

  return (
    <div className="glass-strong h-7 px-3 flex items-center justify-between text-[11px] border-t border-border/40 select-none">
      {/* Left: dep dots */}
      <div className="flex items-center gap-3.5">
        {(Object.entries(dots) as [string, { state: Dot; label: string }][])
          .map(([k, v]) => (
            <span key={k} className="flex items-center gap-1.5 text-muted-foreground"
                  title={v.label}>
              <span className={cn("h-2 w-2 rounded-full shadow-[0_0_10px_currentColor]", dotColor(v.state))} />
              <span className="capitalize">{k}</span>
            </span>
          ))}

        {/* Backend control: shows "Start" when unreachable, "Restart" when up. */}
        <button
          onClick={() => handleBackendAction(backendUp ? "restart" : "start")}
          disabled={backendBusy !== null}
          className={cn(
            "flex items-center gap-1 px-1.5 py-0.5 rounded transition-colors",
            "text-muted-foreground hover:text-foreground hover:bg-accent disabled:opacity-50",
            !backendUp && "text-destructive hover:text-destructive",
            !tauri && "opacity-70",
          )}
          title={
            !tauri
              ? "Native app only — in browser dev mode, launch Start Backend.bat manually"
              : backendUp
                ? "Restart the Python backend (kills the current uvicorn and respawns)"
                : "Start the Python backend (python -m backend.main)"
          }
        >
          {backendBusy ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : backendUp ? (
            <RotateCw className="h-3 w-3" />
          ) : (
            <Play className="h-3 w-3" />
          )}
          {backendBusy
            ? (backendBusy === "start" ? "Starting…" : "Restarting…")
            : backendUp
              ? "Restart backend"
              : "Start backend"}
        </button>

        {backendError && (
          <span className="text-destructive truncate max-w-[420px]" title={backendError}>
            {backendError}
          </span>
        )}
        {!backendError && isError && (
          <span className="text-destructive">backend unreachable</span>
        )}
      </div>

      {/* Right: active jobs + drawer toggle + chat toggle */}
      <div className="flex items-center gap-3">
        {activeJobs > 0 && (
          <span className="flex items-center gap-1.5 text-foreground">
            <Activity className="h-3 w-3 animate-pulse text-primary" />
            {activeJobs} running
          </span>
        )}
        {onToggleChat && (
          <button
            onClick={onToggleChat}
            className="flex items-center gap-1 text-muted-foreground hover:text-foreground transition-colors"
            title="Toggle chat (Ctrl+M)"
          >
            <MessageCircle className={cn("h-3 w-3", chatOpen && "text-primary")} />
            Chat
          </button>
        )}
        <button
          onClick={onToggleDrawer}
          className="flex items-center gap-1 text-muted-foreground hover:text-foreground transition-colors"
          title={drawerOpen ? "Hide logs" : "Show logs"}
        >
          {drawerOpen ? (
            <ChevronDown className="h-3 w-3" />
          ) : (
            <ChevronUp className="h-3 w-3" />
          )}
          Logs
        </button>
      </div>
    </div>
  );
}
