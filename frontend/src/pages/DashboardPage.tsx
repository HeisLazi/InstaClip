/**
 * Dashboard — the launch screen described in the redesign doc.
 *
 * Layout:
 *   - Action-items strip across the top (Zeigarnik nudges)
 *   - Drop / pick / URL / path input region (4 ways in, doc-faithful)
 *   - "Frequent workflows" quick-action row
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Cpu,
  FileVideo,
  FolderOpen,
  Image,
  Languages,
  ListChecks,
  UploadCloud,
  Settings as SettingsIcon,
  UserRound,
} from "lucide-react";

import { ApiError, api } from "@/api/client";
import { BatchPanel } from "@/components/BatchPanel";
import { JobsPanel } from "@/components/JobsPanel";
import { isTauri, onTauriDrop, pickVodFile } from "@/lib/tauri";
import { cn } from "@/lib/utils";
import { IS_CLIPPER, type PageKey } from "@/nav";
import { PageHeader, PageBody } from "./_shared";

interface DashboardPageProps {
  onNavigate: (page: PageKey) => void;
}

export function DashboardPage({ onNavigate }: DashboardPageProps) {
  const counts = useQuery({ queryKey: ["counts"], queryFn: api.status.counts, refetchInterval: 8000 });
  // Owner-only status queries removed in the public clipper edition.
  const qc = useQueryClient();
  const tauri = isTauri();

  const [url, setUrl]   = useState("");
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ message: string; detail?: any } | null>(null);
  const [info,  setInfo]  = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const runSource = useCallback(async (source: string) => {
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const { job_id } = await api.pipeline.run(source);
      qc.invalidateQueries({ queryKey: ["jobs"] });
      setInfo(`Pipeline started — job ${job_id}`);
    } catch (e: any) {
      if (e instanceof ApiError) {
        setError({ message: e.message, detail: e.detail });
      } else {
        setError({ message: e.message ?? "Pipeline kick-off failed" });
      }
    } finally {
      setBusy(false);
    }
  }, [qc]);

  // Wire Tauri's native drag-drop (only fires when running in the Tauri shell).
  useEffect(() => {
    let unlisten: (() => void) | undefined;
    onTauriDrop((paths) => {
      if (paths.length > 0) runSource(paths[0]);
    }).then((u) => { unlisten = u; });
    return () => unlisten?.();
  }, [runSource]);

  async function handlePick() {
    const picked = await pickVodFile();
    if (picked) {
      runSource(picked);
      return;
    }
    // Browser fallback: open the hidden <input type=file>. We can't get the
    // absolute path here for security reasons — show a hint.
    fileRef.current?.click();
  }

  function handleBrowserPickedFile(file: File | null) {
    if (!file) return;
    setError({
      message:
        `Drag-drop and picker in browser preview can't access the absolute file path ` +
        `(security restriction). Either paste the path of "${file.name}" below, or ` +
        `relaunch via "npm run tauri dev" — drag-drop works natively there.`,
    });
  }

  const newClips  = counts.data?.newly_cut ?? 0;
  const positives = counts.data?.positives ?? 0;
  const negatives = counts.data?.negatives ?? 0;

  return (
    <>
      <PageHeader
        title="Dashboard"
        subtitle="Drop a VOD, paste a URL, or point us at a local file path."
      />
      <PageBody>
        {/* Action-items strip */}
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
          <ActionCard
            tone="primary"
            icon={Image}
            label={`${newClips} newly cut clips`}
            sub={
              newClips > 0
                ? "Review them to label good / bad — feeds your classifier."
                : "Run a VOD to produce some."
            }
            ctaLabel="Open Gallery"
            onClick={() => onNavigate("gallery")}
          />
          <>
            <ActionCard
              tone="neutral"
              icon={ListChecks}
              label="Taste setup"
              sub={`${positives} good · ${negatives} rejected labels. Keep examples explained.`}
              ctaLabel="Open Taste Setup"
              onClick={() => onNavigate("onboarding")}
            />
            <ActionCard
              tone="neutral"
              icon={Languages}
              label="Language pack"
              sub="Teach slang, names, and phrases before the next VOD."
              ctaLabel="Open Language Studio"
              onClick={() => onNavigate("language")}
            />
            <ActionCard
              tone="neutral"
              icon={UserRound}
              label="Account and quota"
              sub="Check allowance, local readiness, and support bundle export."
              ctaLabel="Open Account"
              onClick={() => onNavigate("account")}
            />
          </>
        </div>

        {/* Dropzone */}
        <div
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            // Browser drag-drop: we get a File but not its path. Show the hint.
            const f = e.dataTransfer.files?.[0];
            handleBrowserPickedFile(f ?? null);
          }}
          className={cn(
            "premium-card relative overflow-hidden rounded-xl border border-dashed transition-colors",
            "px-8 py-10 surface-1",
            dragOver
              ? "border-primary/80 bg-primary/5 shadow-[0_28px_80px_hsl(var(--primary)_/_0.12)]"
              : "border-border/50 hover:border-primary/35",
          )}
        >
          <div className="flex flex-col items-center text-center gap-3">
            <div className="brand-mark grid h-14 w-14 place-items-center rounded-2xl text-primary-foreground">
              <UploadCloud className="h-7 w-7" />
            </div>
            <div className="font-semibold text-lg">Drop a VOD to start</div>
            <div className="text-sm text-muted-foreground max-w-md">
              {tauri
                ? ".mp4 · .mkv · .mov · .avi — anything ffmpeg understands."
                : "Browser preview can't read local file paths. Use the picker or paste a path below — or launch via "}
              {!tauri && (
                <code className="font-mono text-foreground/80">npm run tauri dev</code>
              )}
              {!tauri && " for native drag-drop."}
            </div>

            <input
              ref={fileRef}
              type="file"
              accept="video/*"
              className="hidden"
              onChange={(e) => handleBrowserPickedFile(e.target.files?.[0] ?? null)}
            />
            <button
              onClick={handlePick}
              className="mt-2 px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-60"
              disabled={busy}
            >
              <FolderOpen className="inline h-4 w-4 mr-1.5 -mt-0.5" />
              Pick a file
            </button>
          </div>

          {/* Local file path */}
          <div className="mt-8 flex items-center gap-3 max-w-2xl mx-auto">
            <FileVideo className="h-4 w-4 text-muted-foreground" />
            <input
              value={path}
              onChange={(e) => setPath(e.target.value)}
              placeholder={`Local file path  e.g.  C:\\Streams\\my-vod.mp4`}
              className="premium-control flex-1 px-3 py-2 rounded-md text-sm outline-none focus:ring-1 focus:ring-primary placeholder:text-muted-foreground"
              onKeyDown={(e) => {
                if (e.key === "Enter" && path.trim()) runSource(path.trim());
              }}
            />
            <button
              disabled={busy || !path.trim()}
              onClick={() => runSource(path.trim())}
              className="px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50 shadow-[0_12px_28px_hsl(var(--primary)_/_0.18)]"
            >
              Run
            </button>
          </div>

          {/* URL */}
          <div className="mt-3 flex items-center gap-3 max-w-2xl mx-auto">
            <FileVideo className="h-4 w-4 text-muted-foreground" />
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="…or paste a Twitch / YouTube URL"
              className="premium-control flex-1 px-3 py-2 rounded-md text-sm outline-none focus:ring-1 focus:ring-primary placeholder:text-muted-foreground"
              onKeyDown={(e) => {
                if (e.key === "Enter" && url.trim()) runSource(url.trim());
              }}
            />
            <button
              disabled={busy || !url.trim()}
              onClick={() => runSource(url.trim())}
              className="px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50 shadow-[0_12px_28px_hsl(var(--primary)_/_0.18)]"
            >
              Run
            </button>
          </div>

          {error && <ErrorBlock error={error} />}
          {info && (
            <div className="mt-4 text-center text-sm text-success">{info}</div>
          )}
        </div>

        {/* Batch panel — local-VOD folder picker + run-batch */}
        <BatchPanel />

        {/* Running jobs — only renders when something is in flight */}
        <JobsPanel hideWhenEmpty />

        {/* Frequent workflows */}
        <div>
          <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground mb-2">
            Frequent workflows
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <QuickAction icon={Cpu}      label="Open gallery"            onClick={() => onNavigate("gallery")} />
            <>
              <QuickAction icon={ListChecks} label="Set up taste" onClick={() => onNavigate("onboarding")} />
              <QuickAction icon={Languages} label="Teach slang" onClick={() => onNavigate("language")} />
              <QuickAction icon={UserRound} label="Account and usage" onClick={() => onNavigate("account")} />
              <QuickAction icon={SettingsIcon} label="Local settings" onClick={() => onNavigate("preferences")} />
            </>
          </div>
        </div>
      </PageBody>
    </>
  );
}

interface ActionCardProps {
  tone: "primary" | "neutral";
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  sub: string;
  ctaLabel: string;
  onClick: () => void;
}

function ActionCard({ tone, icon: Icon, label, sub, ctaLabel, onClick }: ActionCardProps) {
  return (
    <div className={cn(
      "premium-card rounded-xl p-4 border surface-1 transition-all hover:-translate-y-0.5",
      tone === "primary" ? "border-primary/35" : "border-border/50 hover:border-primary/30",
    )}>
      <div className="flex items-start gap-3">
        <div className={cn(
          "grid h-9 w-9 place-items-center rounded-md",
          tone === "primary" ? "bg-primary/15 text-primary" : "bg-secondary text-foreground/80",
        )}>
          <Icon className="h-4 w-4" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold truncate">{label}</div>
          <div className="text-xs text-muted-foreground mt-0.5 leading-snug">{sub}</div>
        </div>
      </div>
      <button onClick={onClick} className="mt-3 text-xs text-primary hover:underline">
        {ctaLabel} →
      </button>
    </div>
  );
}

interface ErrorBlockProps {
  error: { message: string; detail?: any };
}

function ErrorBlock({ error }: ErrorBlockProps) {
  const d = error.detail;
  const isFileNotFound = d && typeof d === "object" && d.error === "file_not_found";

  return (
    <div className="mt-5 mx-auto max-w-2xl rounded-md border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm">
      <div className="font-medium text-destructive">{error.message}</div>

      {isFileNotFound && (
        <div className="mt-2 grid grid-cols-[110px_1fr] gap-x-3 gap-y-1 font-mono text-[11px] text-muted-foreground">
          <span>Raw input:</span>
          <span className="text-foreground/80 break-all">{String(d.received_raw)}</span>

          <span>Tried path:</span>
          <span className="text-foreground/80 break-all">{String(d.tried_path)}</span>

          <span>Parent dir:</span>
          <span className={d.parent_exists ? "text-success" : "text-destructive"}>
            {d.parent_exists ? "exists" : "does NOT exist"}
          </span>

          {Array.isArray(d.sample_files_in_parent) && d.sample_files_in_parent.length > 0 && (
            <>
              <span>Found near:</span>
              <ul className="text-foreground/80 list-disc list-inside">
                {d.sample_files_in_parent.map((s: string, i: number) => (
                  <li key={i} className="break-all">{s}</li>
                ))}
              </ul>
            </>
          )}

          {d.hint && (
            <>
              <span>Hint:</span>
              <span className="text-foreground/80 font-sans">{String(d.hint)}</span>
            </>
          )}
        </div>
      )}

      {!isFileNotFound && d && typeof d === "object" && (
        <pre className="mt-2 text-[11px] font-mono text-muted-foreground overflow-x-auto">
          {JSON.stringify(d, null, 2)}
        </pre>
      )}
    </div>
  );
}

function QuickAction({
  icon: Icon, label, onClick,
}: { icon: React.ComponentType<{ className?: string }>; label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="premium-card group flex items-center gap-3 rounded-lg border border-border/50 surface-1 px-3 py-3 text-sm text-left hover:border-primary/40 hover:bg-primary/5 transition-all hover:-translate-y-0.5"
    >
      <Icon className="h-4 w-4 text-muted-foreground group-hover:text-primary" />
      <span className="truncate">{label}</span>
    </button>
  );
}
