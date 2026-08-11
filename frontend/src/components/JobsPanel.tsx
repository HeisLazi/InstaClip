/**
 * Live progress panel — one card per active or recently stopped job,
 * subscribes to /stream/job/{id} so state changes remain truthful in real time.
 */

import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Loader2, X } from "lucide-react";

import { api, subscribeJob, type JobInfo } from "@/api/client";
import {
  jobPhase,
  nextStoppedExpiry,
  replaceJobSnapshot,
  selectVisibleJobs,
  type JobPhase,
} from "@/components/jobsPanelModel";
import { ICON_FOR_KIND } from "@/nav";
import { cn } from "@/lib/utils";

const STAGE_LABEL: Record<string, string> = {
  starting:            "Starting…",
  fetching:            "Fetching VOD",
  extracting_audio:    "Extracting audio",
  loading_whisper:     "Loading Whisper",
  transcribing:        "Transcribing",
  listener_starting:   "Preparing transcript",
  clip_engine_starting: "Analysing transcript",
  scoring:             "Scoring segments",
  merging_highlights:  "Merging highlights",
  cutter_starting:     "Cutting clips",
  cutting:             "Cutting clips",
  done:                "Done",
  building_dataset:    "Building dataset",
  captioning:          "Captioning frames",
  recording:           "Recording mic",
  embedding:           "Embedding voiceprint",
  thinking:            "LLM is thinking…",
  fetching_clip_list:  "Fetching clip list",
};

function stageLabel(stage?: string) {
  if (!stage) return "Running…";
  return STAGE_LABEL[stage] ?? stage.replace(/_/g, " ");
}

interface JobsPanelProps {
  /** When true, the entire panel hides if there are no active jobs. */
  hideWhenEmpty?: boolean;
}

export function JobsPanel({ hideWhenEmpty = true }: JobsPanelProps) {
  const [nowSeconds, setNowSeconds] = useState(() => Date.now() / 1000);
  const { data: jobs } = useQuery({
    queryKey: ["jobs"],
    queryFn:  api.pipeline.jobs,
    refetchInterval: 4000,
  });

  const visible = useMemo(
    () => selectVisibleJobs(jobs ?? [], nowSeconds),
    [jobs, nowSeconds],
  );
  const liveCount = visible.filter((job) => jobPhase(job) !== "stopped").length;

  useEffect(() => {
    const current = Date.now() / 1000;
    const expiry = nextStoppedExpiry(jobs ?? [], current);
    if (expiry == null) {
      if (nowSeconds < current - 0.25) setNowSeconds(current);
      return;
    }
    const timeout = window.setTimeout(
      () => setNowSeconds(Date.now() / 1000),
      Math.max(50, (expiry - current) * 1000 + 50),
    );
    return () => window.clearTimeout(timeout);
  }, [jobs, nowSeconds]);

  if (hideWhenEmpty && visible.length === 0) return null;

  return (
    <div>
      <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground mb-2 flex items-center gap-2">
        {liveCount > 0
          ? <Loader2 className="h-3 w-3 animate-spin text-primary" />
          : <CheckCircle2 className="h-3 w-3 text-muted-foreground" />}
        Job activity ({visible.length})
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {visible.map((j) => (
          <JobCard key={j.id} initial={j} />
        ))}
        {visible.length === 0 && (
          <div className="text-sm text-muted-foreground italic px-1">
            No jobs running. Start one above.
          </div>
        )}
      </div>
    </div>
  );
}

function JobCard({ initial }: { initial: JobInfo }) {
  const [requestingCancel, setRequestingCancel] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const qc = useQueryClient();

  useEffect(() => {
    let mounted = true;
    const unsub = subscribeJob(
      initial.id,
      (info) => {
        if (!mounted) return;
        qc.setQueryData<JobInfo[]>(["jobs"], (current) => replaceJobSnapshot(current, info));
      },
      () => {
        if (mounted) void qc.invalidateQueries({ queryKey: ["jobs"] });
      },
    );
    return () => {
      mounted = false;
      unsub();
    };
  }, [initial.id, qc]);

  async function onCancel() {
    if (requestingCancel || initial.cancel_requested || initial.status === "cancelled") return;
    setCancelError(null);
    setRequestingCancel(true);
    try {
      await api.pipeline.cancel(initial.id);
      qc.setQueryData<JobInfo[]>(["jobs"], (current) => replaceJobSnapshot(current, {
        ...initial,
        cancel_requested: true,
      }));
      void qc.invalidateQueries({ queryKey: ["jobs"] });
    } catch (error) {
      setCancelError(error instanceof Error ? error.message : "Could not stop this job. Try again.");
    } finally {
      setRequestingCancel(false);
    }
  }

  return <JobCardView job={initial} requestingCancel={requestingCancel} cancelError={cancelError} onCancel={onCancel} />;
}

export function JobCardView({
  job,
  requestingCancel = false,
  cancelError = null,
  onCancel,
}: {
  job: JobInfo;
  requestingCancel?: boolean;
  cancelError?: string | null;
  onCancel: () => void;
}) {
  const phase = jobPhase(job, requestingCancel);
  const Icon = ICON_FOR_KIND[job.kind] ?? ICON_FOR_KIND.default;
  const progress = job.progress ?? {};
  const percent = typeof progress.percent === "number" ? progress.percent : undefined;
  const progressMessage = (progress.message as string | undefined) ?? stageLabel(progress.stage);
  const headline = phase === "stopping"
    ? "Stopping at next safe checkpoint…"
    : phase === "stopped"
      ? "Stopped"
      : phase === "queued"
        ? "Queued for processing"
        : progressMessage;
  const sub = subLine(job, progress);
  const detail = phase === "stopping"
    ? [sub, "Some media steps must finish before they can stop."].filter(Boolean).join(" · ")
    : phase === "stopped"
      ? [sub, "Processing stopped safely."].filter(Boolean).join(" · ")
      : sub;
  const canCancel = phase === "running" || phase === "queued";
  const stopping = phase === "stopping";

  return (
    <div className={cn(
      "premium-card rounded-lg border surface-1 px-4 py-3 overflow-hidden",
      stopping ? "border-warning/35" : phase === "stopped" ? "border-border/35 opacity-80" : "border-border/50",
    )}>
      <div className="flex items-center gap-3">
        <div className="grid h-8 w-8 place-items-center rounded-md bg-primary/15 text-primary">
          <Icon className="h-4 w-4" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <div className="text-sm font-medium truncate">{headline}</div>
            {percent != null && (
              <div className="text-xs text-muted-foreground tabular-nums">
                {percent.toFixed(0)}%
              </div>
            )}
            <JobPhaseBadge phase={phase} />
          </div>
          {detail && (
            <div className="text-[11px] text-muted-foreground truncate mt-0.5">
              {detail}
            </div>
          )}
          {cancelError && <div role="alert" className="mt-1 text-[11px] text-destructive">{cancelError}</div>}
        </div>
        {(canCancel || stopping) && <button
            type="button"
            onClick={onCancel}
            disabled={stopping || requestingCancel}
            aria-label={stopping ? `Stopping ${job.kind} job` : `Stop ${job.kind} job`}
            title={stopping ? "Stopping after the current safe checkpoint" : "Stop this job"}
            className={cn(
              "p-1.5 rounded text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors",
              (stopping || requestingCancel) && "opacity-50 cursor-not-allowed",
            )}
          >
            {stopping ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <X className="h-3.5 w-3.5" />}
          </button>}
      </div>

      {/* Progress bar — determinate if percent known, indeterminate otherwise */}
      <div
        role="progressbar"
        aria-label={`${phaseLabel(phase)} ${job.kind} job`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        className="mt-3 h-1.5 rounded-full bg-secondary overflow-hidden"
      >
        {percent != null ? (
          <div
            className={cn(
              "h-full transition-[width] duration-300",
              stopping ? "bg-warning" : phase === "stopped" ? "bg-muted-foreground/50" : "bg-primary",
            )}
            style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
          />
        ) : (
          <div className={cn(
            "h-full w-1/3 animate-pulse",
            stopping ? "bg-warning/70" : phase === "stopped" ? "bg-muted-foreground/40" : "bg-primary/70",
          )} />
        )}
      </div>
    </div>
  );
}

function JobPhaseBadge({ phase }: { phase: JobPhase }) {
  if (phase === "finished") return null;
  return <span
    role="status"
    aria-live="polite"
    className={cn(
      "text-[10px] uppercase tracking-wider",
      phase === "stopping" ? "text-warning" : phase === "stopped" ? "text-muted-foreground" : "text-primary",
    )}
  >
    {phaseLabel(phase)}
  </span>;
}

function phaseLabel(phase: JobPhase) {
  if (phase === "stopping") return "Stopping";
  if (phase === "stopped") return "Stopped";
  if (phase === "queued") return "Queued";
  if (phase === "running") return "Running";
  return "Finished";
}

function subLine(job: JobInfo, progress: Record<string, any>): string | null {
  if (job.kind === "batch") {
    const cur = progress.current ?? 0;
    const tot = progress.total ?? 0;
    const vod = progress.vod;
    if (vod && tot) return `Batch ${cur}/${tot}: ${vod}`;
    if (tot)        return `Batch ${cur}/${tot}`;
  }
  if (progress.vod && progress.vod !== progress.message) {
    return String(progress.vod);
  }
  if (progress.processed_seconds && progress.total_seconds) {
    const m = (s: number) => `${Math.floor(s / 60)}m ${Math.floor(s % 60).toString().padStart(2, "0")}s`;
    return `${m(progress.processed_seconds)} / ${m(progress.total_seconds)}`;
  }
  if (progress.processed && progress.total) {
    return `${progress.processed} / ${progress.total}`;
  }
  return null;
}
