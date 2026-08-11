import { useDeferredValue, useEffect, useState, type ReactNode } from "react";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  BadgeCheck,
  BrainCircuit,
  CircleAlert,
  Clapperboard,
  Clock3,
  ExternalLink,
  Inbox,
  Loader2,
  MessageSquareText,
  MessagesSquare,
  Play,
  RefreshCw,
  RotateCcw,
  Scissors,
  Search,
  Send,
  ShieldAlert,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  UserRoundCheck,
  Wand2,
  type LucideIcon,
} from "lucide-react";

import {
  api,
  type Bucket,
  type ClipRoomAuditEvent,
  type ClipRoomCandidate,
  type ClipRoomState,
  type ClipRoomSort,
  type DirectorJudgement,
  type DirectorTasteVerdict,
} from "@/api/client";
import { ClipDetailModal } from "@/components/ClipDetailModal";
import { cn } from "@/lib/utils";
import { PageHeader } from "./_shared";

type StageId = "inbox" | "discord" | "production" | "review" | "approved" | "archive";

interface Stage {
  id: StageId;
  label: string;
  hint: string;
  icon: LucideIcon;
  states: ClipRoomState[];
}

const STAGES: Stage[] = [
  {
    id: "inbox",
    label: "Candidate inbox",
    hint: "AI-ranked moments waiting to enter the room",
    icon: Inbox,
    states: ["CANDIDATE", "DETECTED"],
  },
  {
    id: "discord",
    label: "Review desk",
    hint: "Sent cards and claimed assignments",
    icon: MessagesSquare,
    states: ["SENT_TO_DISCORD", "CLAIMED"],
  },
  {
    id: "production",
    label: "In production",
    hint: "Raw, edited, and rendering requests",
    icon: Clapperboard,
    states: ["RAW_REQUESTED", "EDIT_REQUESTED", "RENDERING"],
  },
  {
    id: "review",
    label: "Review queue",
    hint: "Rendered cuts and requested revisions",
    icon: Sparkles,
    states: ["READY_FOR_REVIEW", "REVISION_REQUESTED"],
  },
  {
    id: "approved",
    label: "Approved",
    hint: "Ready, scheduled, and published work",
    icon: BadgeCheck,
    states: ["APPROVED", "SCHEDULED", "PUBLISHED"],
  },
  {
    id: "archive",
    label: "Archive",
    hint: "Rejected and completed learning loops",
    icon: Archive,
    states: ["REJECTED", "MEASURED", "LEARNING_COMPLETE"],
  },
];

const REJECTABLE = new Set<ClipRoomState>([
  "CANDIDATE",
  "SENT_TO_DISCORD",
  "CLAIMED",
  "RAW_REQUESTED",
  "EDIT_REQUESTED",
  "READY_FOR_REVIEW",
  "REVISION_REQUESTED",
]);

const STATE_TONES: Partial<Record<ClipRoomState, string>> = {
  DETECTED: "border-slate-500/40 bg-slate-500/10 text-slate-300",
  CANDIDATE: "border-cyan-400/40 bg-cyan-400/10 text-cyan-200",
  SENT_TO_DISCORD: "border-sky-400/40 bg-sky-400/10 text-sky-200",
  CLAIMED: "border-amber-400/40 bg-amber-400/10 text-amber-200",
  RAW_REQUESTED: "border-orange-400/40 bg-orange-400/10 text-orange-200",
  EDIT_REQUESTED: "border-orange-400/40 bg-orange-400/10 text-orange-200",
  RENDERING: "border-fuchsia-400/40 bg-fuchsia-400/10 text-fuchsia-200",
  READY_FOR_REVIEW: "border-emerald-400/40 bg-emerald-400/10 text-emerald-200",
  REVISION_REQUESTED: "border-yellow-400/40 bg-yellow-400/10 text-yellow-200",
  APPROVED: "border-green-400/40 bg-green-400/10 text-green-200",
  SCHEDULED: "border-blue-400/40 bg-blue-400/10 text-blue-200",
  PUBLISHED: "border-teal-400/40 bg-teal-400/10 text-teal-200",
  REJECTED: "border-red-400/40 bg-red-400/10 text-red-200",
};

function stateLabel(state: ClipRoomState) {
  return state.replaceAll("_", " ").toLowerCase().replace(/(^|\s)\w/g, (letter) => letter.toUpperCase());
}

function secondsLabel(value: number) {
  if (!Number.isFinite(value)) return "--:--";
  const minutes = Math.floor(value / 60);
  const seconds = Math.max(0, Math.floor(value % 60));
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

function durationOf(candidate: ClipRoomCandidate) {
  return Math.max(0, (candidate.end ?? 0) - (candidate.start ?? 0));
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

interface EditableClipTarget {
  bucket: Bucket;
  stem: string;
  candidateId: string;
}

function editableTargetFromAudit(events: ClipRoomAuditEvent[], candidateId: string | undefined): EditableClipTarget | null {
  if (!candidateId) return null;
  const rendered = [...events]
    .sort((a, b) => b.ts - a.ts)
    .find((event) => typeof event.payload?.path === "string");
  const path = rendered?.payload?.path;
  if (typeof path !== "string") return null;

  const normalized = path.replaceAll("\\", "/");
  const filename = normalized.split("/").pop();
  if (!filename) return null;
  const stem = filename.replace(/\.[^.]+$/, "");
  if (!stem) return null;

  const bucket: Bucket = normalized.includes("/output/edited/")
    ? "edited"
    : normalized.includes("/output/positives/")
      ? "positives"
      : normalized.includes("/output/negatives/")
        ? "negatives"
        : "output";
  return { bucket, stem, candidateId };
}

export function ClipRoomPage() {
  const queryClient = useQueryClient();
  const [stageId, setStageId] = useState<StageId>("inbox");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<ClipRoomSort>("score_desc");
  const [vodFilter, setVodFilter] = useState("");
  const [durationFilter, setDurationFilter] = useState<"any" | "micro" | "short" | "long">("any");
  const [minScore, setMinScore] = useState("");
  const [renderStatus, setRenderStatus] = useState<"any" | "rendered" | "unrendered">("any");
  const [hazardFilter, setHazardFilter] = useState<"any" | "yes" | "no">("any");
  const [assigneeFilter, setAssigneeFilter] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const [openClip, setOpenClip] = useState<EditableClipTarget | null>(null);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionNotice, setActionNotice] = useState<string | null>(null);
  const [previewFailed, setPreviewFailed] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editLayout, setEditLayout] = useState<"reaction" | "crop" | "fullcam" | "passthrough">("reaction");
  const [normalize, setNormalize] = useState(true);
  const [boost, setBoost] = useState(0);
  const [revisionNotes, setRevisionNotes] = useState("");
  const deferredSearch = useDeferredValue(search.trim().toLowerCase());
  const filterStorageKey = `clip-room-filters:local-tester`;
  const stage = STAGES.find((item) => item.id === stageId) ?? STAGES[0];

  const candidatesQuery = useInfiniteQuery({
    queryKey: ["clip-room-candidates", stage.id, deferredSearch, sort, vodFilter, durationFilter, minScore, renderStatus, hazardFilter, assigneeFilter, tagFilter],
    initialPageParam: "",
    queryFn: ({ pageParam }) => api.clipRoom.queryCandidates({
      states: stage.states,
      q: deferredSearch || undefined,
      vod_id: vodFilter || undefined,
      min_score: minScore === "" ? undefined : Number(minScore),
      max_duration: durationFilter === "micro" ? 3 : durationFilter === "short" ? 15 : undefined,
      min_duration: durationFilter === "long" ? 45 : undefined,
      render_status: renderStatus,
      hazard: hazardFilter === "any" ? undefined : hazardFilter === "yes",
      claimed_by: assigneeFilter || undefined,
      tag: tagFilter || undefined,
      sort,
      cursor: pageParam || undefined,
      limit: 100,
    }),
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    refetchInterval: 5000,
  });

  const candidatePages = candidatesQuery.data?.pages ?? [];
  const candidates = candidatePages.flatMap((page) => page.candidates);
  const totalCandidates = candidatePages[0]?.total ?? 0;
  const facets = candidatePages[0]?.facets;

  useEffect(() => {
    const stored = window.localStorage.getItem(filterStorageKey);
    if (!stored) return;
    try {
      const value = JSON.parse(stored) as Record<string, string>;
      if (value.sort) setSort(value.sort as ClipRoomSort);
      if (value.duration) setDurationFilter(value.duration as typeof durationFilter);
      if (value.render) setRenderStatus(value.render as typeof renderStatus);
      if (value.hazard) setHazardFilter(value.hazard as typeof hazardFilter);
      if (value.minScore) setMinScore(value.minScore);
      if (value.assignee) setAssigneeFilter(value.assignee);
      if (value.tag) setTagFilter(value.tag);
    } catch { /* ignore stale local preferences */ }
  }, [filterStorageKey]);

  useEffect(() => {
    window.localStorage.setItem(filterStorageKey, JSON.stringify({
      sort, duration: durationFilter, render: renderStatus, hazard: hazardFilter, minScore, assignee: assigneeFilter, tag: tagFilter,
    }));
  }, [filterStorageKey, sort, durationFilter, renderStatus, hazardFilter, minScore, assigneeFilter, tagFilter]);

  useEffect(() => {
    if (!candidates.length) {
      setSelectedId(null);
      return;
    }
    if (!selectedId || !candidates.some((candidate) => candidate.id === selectedId)) {
      setSelectedId(candidates[0].id);
    }
  }, [candidates, selectedId]);

  const selected = candidates.find((candidate) => candidate.id === selectedId) ?? null;
  const auditQuery = useQuery({
    queryKey: ["clip-room-audit", selected?.id],
    queryFn: () => api.clipRoom.audit(selected!.id),
    enabled: Boolean(selected),
  });
  const judgementQuery = useQuery({
    queryKey: ["clip-room-judgement", selected?.id],
    queryFn: () => api.clipRoom.judgement(selected!.id),
    enabled: Boolean(selected),
  });
  const verdictQuery = useQuery({
    queryKey: ["clip-room-verdict", selected?.id],
    queryFn: () => api.clipRoom.verdict(selected!.id),
    enabled: Boolean(selected),
  });
  const editableTarget = editableTargetFromAudit(auditQuery.data?.audit ?? [], selected?.id);

  useEffect(() => {
    setPreviewFailed(false);
    setEditOpen(false);
    setRevisionNotes("");
    setActionError(null);
    setActionNotice(null);
  }, [selected?.id]);

  async function runAction(
    key: string,
    action: Parameters<typeof api.clipRoom.action>[1],
    body: Record<string, unknown> = { actor: "lazi" },
  ) {
    if (!selected) return;
    setActionBusy(key);
    setActionError(null);
    setActionNotice(null);
    try {
      const result = await api.clipRoom.action(selected.id, action, body);
      setActionNotice(result.job_id ? `Render queued as ${result.job_id.slice(0, 8)}.` : "Workflow updated.");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["clip-room-candidates"] }),
        queryClient.invalidateQueries({ queryKey: ["clip-room-audit", selected.id] }),
      ]);
    } catch (error) {
      setActionError(errorMessage(error));
    } finally {
      setActionBusy(null);
    }
  }

  function changeStage(next: StageId) {
    setStageId(next);
    setSelectedId(null);
    setSearch("");
  }

  function applyPreset(preset: "top" | "micro" | "unclaimed" | "review" | "export") {
    setMinScore(preset === "top" ? "0.7" : "");
    setDurationFilter(preset === "micro" ? "micro" : "any");
    setRenderStatus(preset === "export" ? "rendered" : "any");
    setHazardFilter("any");
    setSort(preset === "top" ? "score_desc" : preset === "review" ? "updated" : "newest");
    setAssigneeFilter(preset === "unclaimed" ? "__unclaimed__" : "");
    if (preset === "review") setStageId("review");
    if (preset === "export") setStageId("approved");
  }

  return (
    <div className="min-h-full">
      <PageHeader
        title="Clip Room"
        subtitle="The operational desk between AI candidates, review, rendering, and approval."
        actions={(
          <button
            type="button"
            onClick={() => void candidatesQuery.refetch()}
            disabled={candidatesQuery.isFetching}
            className="premium-control inline-flex items-center gap-2 rounded-md border border-border/60 px-3 py-2 text-xs text-muted-foreground hover:text-foreground disabled:opacity-50"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", candidatesQuery.isFetching && "animate-spin")} />
            Refresh
          </button>
        )}
      />

      <div className="px-5 py-5">
        <div className={cn(
          "mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-sky-400/20 bg-sky-400/[0.06] px-4 py-3",
        )}>
          <div className="flex min-w-0 items-center gap-3">
            <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-sky-400/25 bg-sky-400/10">
              <BadgeCheck className="h-4 w-4 text-sky-300" />
            </div>
            <div className="min-w-0">
              <div className="text-xs font-medium text-sky-100">
                Local Clip Room workflow
              </div>
              <div className="mt-0.5 text-[11px] leading-4 text-muted-foreground">
                Rendered clips are delivered to the local Clip Room; Discord delivery is not part of this edition.
              </div>
            </div>
          </div>
          <span className={cn(
            "rounded-full border border-sky-400/30 bg-sky-400/10 px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.12em] text-sky-200",
          )}>
            Active
          </span>
        </div>

        {/* Viewport-bounded height so the candidate list scrolls INSIDE its own
            column and the preview pane stays visible while scrolling (Lazarus
            2026-07-05: "scrollbar for the candidate inbox — preview isn't
            viewable anymore"). Was min-h only, which let a long list grow the
            page and push the preview off-screen. */}
        <div className="grid h-[calc(100vh-190px)] min-h-[560px] gap-4 xl:grid-cols-[180px_minmax(350px,1fr)_320px] 2xl:grid-cols-[220px_minmax(420px,1fr)_380px]">
          <aside className="surface-1 overflow-hidden rounded-xl border border-border/50">
            <div className="border-b border-border/40 px-4 py-3">
              <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">Workflow</div>
            </div>
            <div className="space-y-1 p-2">
              {STAGES.map((item) => {
                const Icon = item.icon;
                const active = stage.id === item.id;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => changeStage(item.id)}
                    className={cn(
                      "w-full rounded-lg border px-3 py-3 text-left transition-colors",
                      active
                        ? "border-primary/35 bg-primary/10 text-foreground"
                        : "border-transparent text-muted-foreground hover:border-border/50 hover:bg-white/[0.03] hover:text-foreground",
                    )}
                  >
                    <div className="flex items-center gap-2.5">
                      <Icon className={cn("h-4 w-4", active && "text-primary")} />
                      <span className="text-xs font-medium">{item.label}</span>
                    </div>
                    <p className="mt-1.5 pl-6 text-[10px] leading-4 text-muted-foreground">{item.hint}</p>
                  </button>
                );
              })}
            </div>
            <div className="mx-3 mt-3 border-t border-border/40 px-1 py-4">
              <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 shadow-[0_0_10px_rgba(52,211,153,.7)]" />
                Local workflow API online
              </div>
            </div>
          </aside>

          <section className="surface-1 flex min-w-0 flex-col overflow-hidden rounded-xl border border-border/50">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/40 px-4 py-3">
              <div>
                <div className="text-sm font-semibold text-foreground">{stage.label}</div>
                <div className="mt-0.5 text-[10px] text-muted-foreground">
                  {totalCandidates} item{totalCandidates === 1 ? "" : "s"} across {stage.states.map(stateLabel).join(" / ")}
                </div>
              </div>
              <label className="flex h-8 w-full max-w-[260px] items-center gap-2 rounded-md border border-border/60 bg-black/20 px-2.5 focus-within:border-primary/40">
                <Search className="h-3.5 w-3.5 text-muted-foreground" />
                <input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Search stem, reason, hazard..."
                  className="min-w-0 flex-1 bg-transparent text-[11px] text-foreground outline-none placeholder:text-muted-foreground/70"
                />
              </label>
              <div className="flex w-full flex-wrap items-center gap-2">
                <select value={vodFilter} onChange={(event) => setVodFilter(event.target.value)} className="premium-control h-8 min-w-[150px] rounded-md border border-border/60 px-2 text-[10px]">
                  <option value="">All streams</option>
                  {(facets?.vods ?? []).map((vod) => <option key={vod.id} value={vod.id}>{vod.stem}</option>)}
                </select>
                <select value={sort} onChange={(event) => setSort(event.target.value as ClipRoomSort)} className="premium-control h-8 rounded-md border border-border/60 px-2 text-[10px]">
                  <option value="score_desc">Best score</option><option value="newest">Newest</option><option value="oldest">Oldest</option><option value="duration_asc">Shortest</option><option value="duration_desc">Longest</option><option value="stream_position">Stream order</option><option value="updated">Recently updated</option>
                </select>
                <select value={durationFilter} onChange={(event) => setDurationFilter(event.target.value as typeof durationFilter)} className="premium-control h-8 rounded-md border border-border/60 px-2 text-[10px]">
                  <option value="any">Any duration</option><option value="micro">Under 3s</option><option value="short">Under 15s</option><option value="long">45s+</option>
                </select>
                <select value={renderStatus} onChange={(event) => setRenderStatus(event.target.value as typeof renderStatus)} className="premium-control h-8 rounded-md border border-border/60 px-2 text-[10px]">
                  <option value="any">Any render</option><option value="rendered">Rendered</option><option value="unrendered">Not rendered</option>
                </select>
                <select value={hazardFilter} onChange={(event) => setHazardFilter(event.target.value as typeof hazardFilter)} className="premium-control h-8 rounded-md border border-border/60 px-2 text-[10px]">
                  <option value="any">Any hazards</option><option value="yes">Has hazards</option><option value="no">No hazards</option>
                </select>
                <select value={assigneeFilter} onChange={(event) => setAssigneeFilter(event.target.value)} className="premium-control h-8 rounded-md border border-border/60 px-2 text-[10px]">
                  <option value="">Any owner</option><option value="__unclaimed__">Unclaimed</option>{(facets?.assignees ?? []).map((owner) => <option key={owner} value={owner}>{owner}</option>)}
                </select>
                <select value={tagFilter} onChange={(event) => setTagFilter(event.target.value)} className="premium-control h-8 rounded-md border border-border/60 px-2 text-[10px]">
                  <option value="">Any tag</option>{(facets?.tags ?? []).map((tag) => <option key={tag} value={tag}>{tag}</option>)}
                </select>
                <input value={minScore} onChange={(event) => setMinScore(event.target.value)} type="number" min="0" max="1" step="0.05" placeholder="Min score" className="premium-control h-8 w-20 rounded-md border border-border/60 px-2 text-[10px]" />
              </div>
              <div className="flex w-full flex-wrap gap-1.5">
                {([['top','Top candidates'],['micro','Micro junk'],['unclaimed','Unclaimed'],['review','Needs review'],['export','Ready to export']] as const).map(([key, label]) => <button key={key} type="button" onClick={() => applyPreset(key)} className="rounded-full border border-border/50 bg-white/[0.025] px-2.5 py-1 text-[9px] text-muted-foreground hover:border-primary/35 hover:text-primary">{label}</button>)}
                <button type="button" onClick={() => { setSearch(""); setVodFilter(""); setDurationFilter("any"); setMinScore(""); setRenderStatus("any"); setHazardFilter("any"); setAssigneeFilter(""); setTagFilter(""); setSort("score_desc"); }} className="rounded-full border border-border/50 px-2.5 py-1 text-[9px] text-muted-foreground hover:text-foreground">Reset</button>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto p-3">
              {candidatesQuery.isLoading && (
                <EmptyState icon={Loader2} title="Loading Clip Room" detail="Reading durable workflow state..." spinning />
              )}
              {candidatesQuery.isError && (
                <EmptyState
                  icon={CircleAlert}
                  title="Clip Room API unavailable"
                  detail={`${errorMessage(candidatesQuery.error)} Restart the backend if it was changed without reload.`}
                />
              )}
              {!candidatesQuery.isLoading && !candidatesQuery.isError && candidates.length === 0 && (
                <EmptyState
                  icon={Inbox}
                  title={deferredSearch ? "No matching candidates" : "This stage is clear"}
                  detail={deferredSearch ? "Try a stem, reason, editor, or hazard." : "Candidates will appear here as the pipeline advances them."}
                />
              )}
              <div className="space-y-2">
                {candidates.map((candidate) => (
                  <CandidateRow
                    key={candidate.id}
                    candidate={candidate}
                    selected={candidate.id === selected?.id}
                    onSelect={() => setSelectedId(candidate.id)}
                  />
                ))}
                {candidatesQuery.hasNextPage && (
                  <button
                    type="button"
                    onClick={() => void candidatesQuery.fetchNextPage()}
                    disabled={candidatesQuery.isFetchingNextPage}
                    className="mt-3 w-full rounded-md border border-border/50 bg-white/[0.02] px-3 py-2.5 text-[10px] font-medium text-muted-foreground hover:border-primary/35 hover:text-primary"
                  >
                    {candidatesQuery.isFetchingNextPage ? "Loading..." : `Load 100 more (${Math.max(0, totalCandidates - candidates.length)} remaining)`}
                  </button>
                )}
              </div>
            </div>
          </section>

          <aside className="surface-1 min-w-0 overflow-hidden rounded-xl border border-border/50">
            {!selected ? (
              <EmptyState icon={MessageSquareText} title="Select a candidate" detail="Preview its source, take the next action, and inspect the audit trail." />
            ) : (
              <div className="flex h-full flex-col">
                <div className="border-b border-border/40 p-3">
                  <div className="relative aspect-video overflow-hidden rounded-lg border border-border/50 bg-black/50">
                    {!previewFailed ? (
                      <video
                        key={selected.id}
                        controls
                        preload="metadata"
                        src={api.clipRoom.previewUrl(selected.id)}
                        onError={() => setPreviewFailed(true)}
                        className="h-full w-full object-contain"
                      />
                    ) : (
                      <div className="grid h-full place-items-center px-5 text-center text-[11px] text-muted-foreground">
                        Source VOD is unavailable for this candidate. The durable workflow record is still intact.
                      </div>
                    )}
                    <div className="pointer-events-none absolute left-2 top-2">
                      <StatePill state={selected.state} />
                    </div>
                  </div>

                  <div className="mt-3 flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate font-mono text-xs font-semibold text-foreground" title={selected.stem}>{selected.stem}</div>
                      <p className="mt-1 line-clamp-3 text-[11px] leading-4 text-muted-foreground">
                        {selected.reason || "No candidate reason was recorded."}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => editableTarget && setOpenClip(editableTarget)}
                      disabled={!editableTarget}
                      className="grid h-8 w-8 shrink-0 place-items-center rounded-md border border-border/60 text-muted-foreground hover:border-primary/40 hover:text-primary disabled:cursor-not-allowed disabled:opacity-35"
                      title={editableTarget ? "Open latest rendered clip" : "Render this candidate before opening it"}
                    >
                      <ExternalLink className="h-3.5 w-3.5" />
                    </button>
                  </div>

                  <div className="mt-3 grid grid-cols-3 gap-2">
                    <Metric label="Score" value={selected.score == null ? "--" : selected.score.toFixed(2)} />
                    <Metric label="Duration" value={secondsLabel(durationOf(selected))} />
                    <Metric label="Owner" value={selected.claimed_by || "Unclaimed"} />
                  </div>
                </div>

                <div className="border-t border-border/40 px-4 py-3">
                  <DirectorRead
                    judgement={judgementQuery.data?.judgement}
                    loading={judgementQuery.isLoading}
                    failed={judgementQuery.isError}
                    verdict={verdictQuery.data?.verdict}
                    verdictLoading={verdictQuery.isLoading}
                    verdictFailed={verdictQuery.isError}
                  />
                </div>

                <div className="flex-1 overflow-y-auto">
                  <ActionDesk
                    candidate={selected}
                    busy={actionBusy}
                    error={actionError}
                    notice={actionNotice}
                    editOpen={editOpen}
                    editLayout={editLayout}
                    normalize={normalize}
                    boost={boost}
                    revisionNotes={revisionNotes}
                    canOpenClip={Boolean(editableTarget)}
                    onEditOpen={setEditOpen}
                    onEditLayout={setEditLayout}
                    onNormalize={setNormalize}
                    onBoost={setBoost}
                    onRevisionNotes={setRevisionNotes}
                    onRun={runAction}
                    onOpenClip={() => editableTarget && setOpenClip(editableTarget)}
                  />

                  <div className="border-t border-border/40 p-4">
                    <div className="mb-3 flex items-center justify-between">
                      <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Audit trail</div>
                      {auditQuery.isFetching && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />}
                    </div>
                    <AuditTrail events={auditQuery.data?.audit ?? []} />
                  </div>
                </div>
              </div>
            )}
          </aside>
        </div>
      </div>

      {openClip && (
        <ClipDetailModal bucket={openClip.bucket} stem={openClip.stem} candidateId={openClip.candidateId} onClose={() => setOpenClip(null)} />
      )}
    </div>
  );
}

function CandidateRow({
  candidate,
  selected,
  onSelect,
}: {
  candidate: ClipRoomCandidate;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "group flex w-full gap-3 rounded-lg border p-2.5 text-left transition-all",
        selected
          ? "border-primary/40 bg-primary/[0.08] shadow-[0_10px_35px_rgba(0,0,0,.2)]"
          : "border-border/45 bg-black/[0.12] hover:border-border hover:bg-white/[0.03]",
      )}
    >
      <div className="relative h-[72px] w-28 shrink-0 overflow-hidden rounded-md border border-border/40 bg-black/40">
        <img
          src={api.clips.thumbUrl("output", candidate.stem)}
          alt=""
          loading="lazy"
          onError={(event) => { event.currentTarget.style.display = "none"; }}
          className="h-full w-full object-cover opacity-85 transition-transform duration-300 group-hover:scale-[1.03]"
        />
        <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-transparent" />
        <div className="absolute bottom-1 left-1 flex items-center gap-1 rounded bg-black/70 px-1.5 py-0.5 text-[9px] text-slate-200">
          <Clock3 className="h-2.5 w-2.5" />
          {secondsLabel(durationOf(candidate))}
        </div>
      </div>
      <div className="min-w-0 flex-1 py-0.5">
        <div className="flex items-center justify-between gap-2">
          <div className="truncate font-mono text-[11px] font-medium text-foreground">{candidate.stem}</div>
          <div className="shrink-0 text-[11px] font-semibold tabular-nums text-primary">
            {candidate.score == null ? "--" : candidate.score.toFixed(2)}
          </div>
        </div>
        <p className="mt-1 line-clamp-2 text-[10px] leading-4 text-muted-foreground">
          {candidate.reason || "No reason recorded"}
        </p>
        <div className="mt-2 flex min-w-0 items-center gap-1.5">
          <StatePill state={candidate.state} compact />
          {candidate.claimed_by && (
            <span className="truncate text-[9px] text-muted-foreground">@{candidate.claimed_by}</span>
          )}
          {(candidate.hazards?.length ?? 0) > 0 && (
            <ShieldAlert className="ml-auto h-3 w-3 shrink-0 text-amber-300" />
          )}
        </div>
      </div>
    </button>
  );
}

function StatePill({ state, compact = false }: { state: ClipRoomState; compact?: boolean }) {
  return (
    <span className={cn(
      "inline-flex max-w-full items-center rounded-full border font-medium uppercase tracking-[0.08em]",
      compact ? "px-1.5 py-0.5 text-[8px]" : "px-2 py-1 text-[9px]",
      STATE_TONES[state] ?? "border-border/60 bg-white/5 text-muted-foreground",
    )}>
      <span className="truncate">{stateLabel(state)}</span>
    </span>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border/45 bg-black/15 px-2.5 py-2">
      <div className="text-[8px] font-medium uppercase tracking-[0.12em] text-muted-foreground">{label}</div>
      <div className="mt-1 truncate text-[10px] font-medium text-foreground" title={value}>{value}</div>
    </div>
  );
}

function DirectorRead({
  judgement,
  loading,
  failed,
  verdict,
  verdictLoading,
  verdictFailed,
}: {
  judgement?: DirectorJudgement;
  loading: boolean;
  failed: boolean;
  verdict?: DirectorTasteVerdict | null;
  verdictLoading: boolean;
  verdictFailed: boolean;
}) {
  if (loading && verdictLoading) {
    return <div className="flex items-center gap-2 text-[10px] text-muted-foreground"><Loader2 className="h-3 w-3 animate-spin" /> Reading Director memory</div>;
  }
  if ((failed || !judgement) && (verdictFailed || !verdict)) {
    return <div className="text-[10px] text-muted-foreground">Director explanation is unavailable.</div>;
  }

  const changed = judgement ? Math.abs(judgement.adjustment) > 0.0001 : false;
  const verdictTone = verdict?.verdict === "keep"
    ? "border-emerald-300/25 bg-emerald-300/[0.06] text-emerald-200"
    : verdict?.verdict === "skip"
      ? "border-rose-300/25 bg-rose-300/[0.06] text-rose-200"
      : "border-amber-300/25 bg-amber-300/[0.06] text-amber-200";
  return (
    <div className="space-y-2">
      {judgement && <div className={cn(
        "rounded-lg border px-3 py-2.5",
        judgement.null_like ? "border-amber-300/25 bg-amber-300/[0.06]" : "border-cyan-300/20 bg-cyan-300/[0.04]",
      )}>
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5 text-[9px] font-semibold uppercase tracking-[0.12em] text-cyan-200">
            <BrainCircuit className="h-3.5 w-3.5" /> Why this pick
          </div>
          <div className="font-mono text-[9px] text-muted-foreground">
            {judgement.base_score.toFixed(2)} {changed ? `${judgement.adjustment >= 0 ? "+" : ""}${judgement.adjustment.toFixed(2)}` : ""} = <span className="text-foreground">{judgement.adjusted_score.toFixed(2)}</span>
          </div>
        </div>
        <p className="mt-1.5 text-[10px] leading-4 text-muted-foreground">
          {judgement.notes.length
            ? judgement.notes.join(" ")
            : "The Director found no memory rule that should move this candidate away from its detector score."}
        </p>
      </div>}
      {verdict ? <div className={cn("rounded-lg border px-3 py-2.5", verdictTone)}>
        <div className="flex items-center justify-between gap-2 text-[9px] font-semibold uppercase tracking-[0.12em]">
          <span className="flex items-center gap-1.5"><Sparkles className="h-3.5 w-3.5" /> Director taste verdict</span>
          <span className="font-mono">{verdict.verdict} · {verdict.fit.toFixed(2)}</span>
        </div>
        <p className="mt-1.5 text-[10px] leading-4 text-muted-foreground">{verdict.why}</p>
        <p className="mt-1 text-[8px] text-muted-foreground/70">Advisory only. Your review remains the final decision.</p>
      </div> : !verdictLoading && !verdictFailed ? <div className="text-[9px] text-muted-foreground">Taste verdict pending for this candidate.</div> : null}
    </div>
  );
}

function ActionDesk({
  candidate,
  busy,
  error,
  notice,
  editOpen,
  editLayout,
  normalize,
  boost,
  revisionNotes,
  canOpenClip,
  onEditOpen,
  onEditLayout,
  onNormalize,
  onBoost,
  onRevisionNotes,
  onRun,
  onOpenClip,
}: {
  candidate: ClipRoomCandidate;
  busy: string | null;
  error: string | null;
  notice: string | null;
  editOpen: boolean;
  editLayout: "reaction" | "crop" | "fullcam" | "passthrough";
  normalize: boolean;
  boost: number;
  revisionNotes: string;
  canOpenClip: boolean;
  onEditOpen: (open: boolean) => void;
  onEditLayout: (layout: "reaction" | "crop" | "fullcam" | "passthrough") => void;
  onNormalize: (value: boolean) => void;
  onBoost: (value: number) => void;
  onRevisionNotes: (value: string) => void;
  onRun: (
    key: string,
    action: Parameters<typeof api.clipRoom.action>[1],
    body?: Record<string, unknown>,
  ) => Promise<void>;
  onOpenClip: () => void;
}) {
  const state = candidate.state;
  const isBusy = Boolean(busy);

  async function reject() {
    if (!window.confirm(`Reject ${candidate.stem}? This closes its current workflow.`)) return;
    await onRun("reject", "reject", { actor: "lazi", reason: "Rejected from desktop Clip Room" });
  }

  return (
    <div className="p-4">
      <div className="mb-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Next action</div>

      <div className="grid grid-cols-2 gap-2">
        {state === "DETECTED" && (
          <ActionButton icon={Sparkles} busy={busy === "promote"} disabled={isBusy} onClick={() => onRun("promote", "promote")}>
            Promote
          </ActionButton>
        )}

        {state === "CANDIDATE" && (
          <div className="col-span-2 text-[10px] leading-4 text-slate-300/80">
            Candidate is available for local workflow actions. Discord delivery is not part of this edition.
          </div>
        )}

        {state === "SENT_TO_DISCORD" && (
          <ActionButton icon={UserRoundCheck} busy={busy === "claim"} disabled={isBusy} onClick={() => onRun("claim", "claim")}>
            Claim as Lazi
          </ActionButton>
        )}

        {(state === "CLAIMED" || state === "REVISION_REQUESTED") && (
          <>
            {state === "CLAIMED" && (
              <ActionButton icon={Play} busy={busy === "raw"} disabled={isBusy} onClick={() => onRun("raw", "request-raw")}>
                Request raw
              </ActionButton>
            )}
            <ActionButton icon={Wand2} disabled={isBusy} onClick={() => onEditOpen(!editOpen)}>
              Request edited
            </ActionButton>
          </>
        )}

        {(state === "RAW_REQUESTED" || state === "EDIT_REQUESTED") && (
          <ActionButton icon={Clapperboard} busy={busy === "render"} disabled={isBusy} onClick={() => onRun("render", "render")}>
            Start render
          </ActionButton>
        )}

        {state === "RENDERING" && (
          <div className="col-span-2 flex items-center gap-2 rounded-md border border-fuchsia-400/25 bg-fuchsia-400/[0.06] px-3 py-2.5 text-[11px] text-fuchsia-200">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Render worker is processing this clip.
          </div>
        )}

        {state === "READY_FOR_REVIEW" && (
          <>
            <ActionButton icon={ThumbsUp} tone="success" busy={busy === "approve"} disabled={isBusy} onClick={() => onRun("approve", "approve")}>
              Approve
            </ActionButton>
            <ActionButton icon={RotateCcw} disabled={isBusy} onClick={() => onEditOpen(!editOpen)}>
              Request revision
            </ActionButton>
          </>
        )}

        <ActionButton
          icon={Scissors}
          disabled={isBusy || !canOpenClip}
          onClick={onOpenClip}
          title={canOpenClip ? "Open the latest rendered version" : "Render this candidate before opening the editor"}
        >
          Open clip + editor
        </ActionButton>

        {REJECTABLE.has(state) && (
          <ActionButton icon={ThumbsDown} tone="danger" busy={busy === "reject"} disabled={isBusy} onClick={reject}>
            Reject
          </ActionButton>
        )}
      </div>

      {editOpen && (state === "CLAIMED" || state === "REVISION_REQUESTED" || state === "READY_FOR_REVIEW") && (
        <div className="mt-3 space-y-3 rounded-lg border border-primary/25 bg-primary/[0.05] p-3">
          {state === "READY_FOR_REVIEW" ? (
            <>
              <label className="block text-[9px] font-medium uppercase tracking-[0.1em] text-muted-foreground">Revision notes</label>
              <textarea
                value={revisionNotes}
                onChange={(event) => onRevisionNotes(event.target.value)}
                rows={3}
                placeholder="What should change in the next cut?"
                className="w-full resize-none rounded-md border border-border/60 bg-black/25 px-2.5 py-2 text-[11px] text-foreground outline-none"
              />
              <ActionButton
                icon={RotateCcw}
                busy={busy === "revision"}
                disabled={isBusy || !revisionNotes.trim()}
                onClick={() => onRun("revision", "request-revision", { actor: "lazi", notes: revisionNotes.trim() })}
              >
                Send revision
              </ActionButton>
            </>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-2">
                <label className="text-[9px] font-medium uppercase tracking-[0.1em] text-muted-foreground">
                  Layout
                  <select
                    value={editLayout}
                    onChange={(event) => onEditLayout(event.target.value as typeof editLayout)}
                    className="mt-1.5 h-8 w-full rounded-md border border-border/60 bg-black/25 px-2 text-[10px] text-foreground outline-none"
                  >
                    <option value="reaction">Reaction</option>
                    <option value="crop">9:16 crop</option>
                    <option value="fullcam">Full camera</option>
                    <option value="passthrough">Passthrough</option>
                  </select>
                </label>
                <label className="text-[9px] font-medium uppercase tracking-[0.1em] text-muted-foreground">
                  Audio boost
                  <div className="mt-1.5 flex h-8 items-center gap-2 rounded-md border border-border/60 bg-black/25 px-2">
                    <input
                      type="range"
                      min={-12}
                      max={12}
                      step={1}
                      value={boost}
                      onChange={(event) => onBoost(Number(event.target.value))}
                      className="min-w-0 flex-1 accent-cyan-400"
                    />
                    <span className="w-8 text-right text-[9px] text-foreground">{boost} dB</span>
                  </div>
                </label>
              </div>
              <label className="flex items-center gap-2 text-[10px] text-muted-foreground">
                <input type="checkbox" checked={normalize} onChange={(event) => onNormalize(event.target.checked)} className="accent-cyan-400" />
                Normalize voice and source audio
              </label>
              <ActionButton
                icon={Wand2}
                busy={busy === "edit"}
                disabled={isBusy}
                onClick={() => onRun("edit", "request-edit", {
                  actor: "lazi",
                  edit: {
                    trim: { start: candidate.start ?? 0, end: candidate.end ?? 0 },
                    layout: editLayout,
                    audio_normalize: normalize,
                    audio_boost_db: boost,
                  },
                })}
              >
                Submit edit plan
              </ActionButton>
            </>
          )}
        </div>
      )}

      {candidate.hazards && candidate.hazards.length > 0 && (
        <div className="mt-3 rounded-lg border border-amber-400/20 bg-amber-400/[0.05] p-3">
          <div className="flex items-center gap-2 text-[10px] font-medium text-amber-200">
            <ShieldAlert className="h-3.5 w-3.5" />
            Review hazards
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {candidate.hazards.map((hazard) => (
              <span key={hazard} className="rounded border border-amber-400/20 bg-black/20 px-1.5 py-0.5 text-[9px] text-amber-100/80">{hazard}</span>
            ))}
          </div>
        </div>
      )}

      {error && (
        <div className="mt-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-[10px] leading-4 text-red-200">{error}</div>
      )}
      {notice && (
        <div className="mt-3 rounded-md border border-emerald-400/25 bg-emerald-400/[0.08] px-3 py-2 text-[10px] text-emerald-200">{notice}</div>
      )}
    </div>
  );
}

function ActionButton({
  icon: Icon,
  children,
  busy = false,
  disabled = false,
  tone = "default",
  onClick,
  title,
}: {
  icon: LucideIcon;
  children: ReactNode;
  busy?: boolean;
  disabled?: boolean;
  tone?: "default" | "success" | "danger";
  onClick: () => void | Promise<void>;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={() => void onClick()}
      disabled={disabled || busy}
      title={title}
      className={cn(
        "inline-flex min-h-9 items-center justify-center gap-2 rounded-md border px-2.5 py-2 text-[10px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-45",
        tone === "default" && "border-border/60 bg-white/[0.025] text-foreground hover:border-primary/40 hover:bg-primary/[0.07] hover:text-primary",
        tone === "success" && "border-emerald-400/30 bg-emerald-400/[0.08] text-emerald-200 hover:bg-emerald-400/[0.14]",
        tone === "danger" && "border-red-400/25 bg-red-400/[0.06] text-red-200 hover:bg-red-400/[0.12]",
      )}
    >
      {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Icon className="h-3.5 w-3.5" />}
      <span>{children}</span>
    </button>
  );
}

function AuditTrail({ events }: { events: ClipRoomAuditEvent[] }) {
  if (!events.length) {
    return <div className="rounded-md border border-dashed border-border/50 px-3 py-5 text-center text-[10px] text-muted-foreground">No workflow events yet.</div>;
  }

  return (
    <div className="space-y-0">
      {[...events].reverse().map((event, index) => (
        <div key={`${event.ts}-${index}`} className="relative flex gap-3 pb-4 last:pb-0">
          {index < events.length - 1 && <span className="absolute left-[5px] top-3 h-full w-px bg-border/60" />}
          <span className="relative mt-1 h-[11px] w-[11px] shrink-0 rounded-full border-2 border-background bg-primary" />
          <div className="min-w-0 flex-1">
            <div className="flex items-start justify-between gap-2">
              <div className="text-[10px] font-medium text-foreground">{stateLabel(event.to)}</div>
              <div className="shrink-0 text-[8px] text-muted-foreground">{new Date(event.ts * 1000).toLocaleString()}</div>
            </div>
            <div className="mt-0.5 text-[9px] text-muted-foreground">{event.reason || `${stateLabel(event.from)} to ${stateLabel(event.to)}`}</div>
            <div className="mt-1 text-[8px] uppercase tracking-[0.1em] text-primary/75">{event.actor}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

function EmptyState({
  icon: Icon,
  title,
  detail,
  spinning = false,
}: {
  icon: LucideIcon;
  title: string;
  detail: string;
  spinning?: boolean;
}) {
  return (
    <div className="grid min-h-[300px] place-items-center px-6 py-10 text-center">
      <div>
        <div className="mx-auto grid h-11 w-11 place-items-center rounded-xl border border-border/50 bg-white/[0.03]">
          <Icon className={cn("h-5 w-5 text-muted-foreground", spinning && "animate-spin")} />
        </div>
        <div className="mt-3 text-xs font-medium text-foreground">{title}</div>
        <p className="mx-auto mt-1 max-w-[260px] text-[10px] leading-4 text-muted-foreground">{detail}</p>
      </div>
    </div>
  );
}
