import { useCallback, useDeferredValue, useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Check,
  Clock3,
  Folder,
  Grid2X2,
  Loader2,
  Play,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Tags,
  Upload,
  X,
} from "lucide-react";

import { api, type Bucket, type ClipInfo } from "@/api/client";
import { ClipDetailModal } from "@/components/ClipDetailModal";
import { ClipTile, type LabelAction } from "@/components/ClipTile";
import { KeepersView } from "@/components/KeepersView";
import { cn } from "@/lib/utils";
import { PageHeader, PageBody } from "./_shared";

type View = "output" | "positives" | "negatives" | "edited" | "by_stream";
type DurationPreset = "reviewable" | "all" | "micro";
type SortValue = "newest" | "oldest" | "score" | "duration_desc" | "duration_asc" | "size" | "name";

const PAGE_SIZE = 120;

export function GalleryPage() {
  const [view, setView] = useState<View>("output");
  const bucket: Bucket = view === "by_stream" ? "positives" : view;
  const [open, setOpen] = useState<{ bucket: Bucket; stem: string } | null>(null);
  const [hoveredStem, setHoveredStem] = useState<string | null>(null);
  const [folder, setFolder] = useState("all");
  const [tagFilter, setTagFilter] = useState("all");
  const [tagEditor, setTagEditor] = useState<ClipInfo | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search.trim());
  const [durationPreset, setDurationPreset] = useState<DurationPreset>("reviewable");
  const [sort, setSort] = useState<SortValue>("newest");
  const [minScore, setMinScore] = useState(0);
  const [page, setPage] = useState(0);
  const [autoPlay, setAutoPlay] = useState(() =>
    typeof window !== "undefined" && window.sessionStorage.getItem("instaclip-gallery-autoplay") === "true",
  );
  const qc = useQueryClient();

  const sortOptions = (() => {
    if (sort === "duration_asc") return { sortBy: "duration" as const, order: "asc" as const };
    if (sort === "duration_desc") return { sortBy: "duration" as const, order: "desc" as const };
    if (sort === "name") return { sortBy: "name" as const, order: "asc" as const };
    if (sort === "oldest") return { sortBy: "oldest" as const, order: "asc" as const };
    return { sortBy: sort as "newest" | "score" | "size", order: "desc" as const };
  })();

  const groupsQuery = useQuery({
    queryKey: ["clip-groups", bucket],
    queryFn: () => api.clips.groups(bucket),
    enabled: view !== "by_stream",
  });

  const taxonomyQuery = useQuery({
    queryKey: ["clip-tag-taxonomy"],
    queryFn: api.clips.tagTaxonomy,
    enabled: view !== "by_stream",
  });

  const clipsQuery = useQuery({
    queryKey: ["clips", bucket, folder, tagFilter, deferredSearch, durationPreset, sort, minScore],
    queryFn: () => api.clips.list(bucket, {
      limit: 5000,
      group: folder,
      search: deferredSearch,
      minDuration: durationPreset === "reviewable" ? 4 : undefined,
      maxDuration: durationPreset === "micro" ? 3.999 : undefined,
      minScore: minScore || undefined,
      tag: tagFilter,
      ...sortOptions,
    }),
    enabled: view !== "by_stream",
  });

  useEffect(() => {
    setFolder("all");
    setTagFilter("all");
    setPage(0);
  }, [view]);

  useEffect(() => setPage(0), [folder, tagFilter, deferredSearch, durationPreset, sort, minScore]);

  useEffect(() => {
    window.sessionStorage.setItem("instaclip-gallery-autoplay", String(autoPlay));
  }, [autoPlay]);

  const moveClip = useCallback(async (stem: string, target: Bucket) => {
    if (target === bucket) return;
    await api.clips.move(stem, bucket, target);
    qc.invalidateQueries({ queryKey: ["clips"] });
    qc.invalidateQueries({ queryKey: ["clip-groups"] });
    qc.invalidateQueries({ queryKey: ["counts"] });
  }, [bucket, qc]);

  useEffect(() => {
    if (open) return;
    function handler(event: KeyboardEvent) {
      if (!hoveredStem) return;
      const tag = (event.target as HTMLElement | null)?.tagName.toLowerCase() ?? "";
      if (["input", "textarea", "select"].includes(tag)) return;
      if (event.key === "ArrowRight" && bucket !== "positives") {
        event.preventDefault();
        void moveClip(hoveredStem, "positives");
      } else if (event.key === "ArrowLeft" && bucket !== "negatives") {
        event.preventDefault();
        void moveClip(hoveredStem, "negatives");
      } else if (event.code === "Space") {
        event.preventDefault();
        setOpen({ bucket, stem: hoveredStem });
      }
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, hoveredStem, bucket, moveClip]);

  async function handleTileLabel(stem: string, action: LabelAction) {
    await moveClip(stem, action === "good" ? "positives" : "negatives");
  }

  const clips = clipsQuery.data ?? [];
  const groups = groupsQuery.data?.groups ?? [];
  const taxonomy = taxonomyQuery.data?.taxonomy ?? { good: [], bad: [] };
  const folderTags = bucket === "positives" ? taxonomy.good : bucket === "negatives" ? taxonomy.bad : [];
  const pageCount = Math.max(1, Math.ceil(clips.length / PAGE_SIZE));
  const visibleClips = clips.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const selectedGroup = groups.find((item) => item.id === folder);
  const openIndex = open ? clips.findIndex((clip) => clip.stem === open.stem) : -1;

  function openClip(stem: string) {
    const index = clips.findIndex((clip) => clip.stem === stem);
    if (index >= 0) setPage(Math.floor(index / PAGE_SIZE));
    setOpen({ bucket, stem });
  }

  function openQueueIndex(index: number) {
    const clip = clips[index];
    if (!clip) return;
    setPage(Math.floor(index / PAGE_SIZE));
    setHoveredStem(null);
    setOpen({ bucket, stem: clip.stem });
  }

  function autoAdvanceQueue() {
    if (clips.length <= 1) {
      setOpen(null);
      return;
    }
    const currentIndex = open ? clips.findIndex((clip) => clip.stem === open.stem) : -1;
    const nextIndex = currentIndex >= 0 ? (currentIndex + 1) % clips.length : 0;
    openQueueIndex(nextIndex);
  }

  function refresh() {
    void groupsQuery.refetch();
    void clipsQuery.refetch();
  }

  return (
    <>
      <PageHeader
        title="Clip Library"
        subtitle={
          <>
            Batch folders, quality filters and fast review. <kbd className="kbd">Right</kbd> Good, <kbd className="kbd">Left</kbd> Bad, <kbd className="kbd">Space</kbd> Open.
          </>
        }
        actions={
          <div className="flex items-center gap-2">
          <button type="button" onClick={() => setImportOpen(true)} className="premium-control flex items-center gap-1.5 rounded-md px-3 py-2 text-xs text-muted-foreground hover:text-primary"><Upload className="h-3.5 w-3.5" /> Import clip</button>
          <div className="premium-control flex items-center gap-1 rounded-md p-1">
            {([
              { key: "output", label: "New cuts" },
              { key: "positives", label: "Good" },
              { key: "negatives", label: "Bad" },
              { key: "edited", label: "Edited" },
              { key: "by_stream", label: "Keepers" },
            ] as Array<{ key: View; label: string }>).map(({ key, label }) => (
              <button
                key={key}
                type="button"
                data-testid={`gallery-view-${key}`}
                onClick={() => setView(key)}
                className={cn(
                  "rounded px-3 py-1 text-xs",
                  view === key
                    ? "bg-primary text-primary-foreground shadow-[0_10px_22px_hsl(var(--primary)_/_0.16)]"
                    : "text-muted-foreground hover:bg-accent/45 hover:text-foreground",
                )}
              >
                {label}
              </button>
            ))}
          </div>
          </div>
        }
      />

      <PageBody>
        {view === "by_stream" ? <KeepersView /> : (
          <div className="grid min-h-[calc(100vh-150px)] grid-cols-1 gap-4 xl:grid-cols-[260px_minmax(0,1fr)]">
            <aside className="surface-1 h-fit overflow-hidden rounded-xl border border-border/50 xl:sticky xl:top-4">
              <div className="border-b border-border/50 p-3">
                <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.15em] text-muted-foreground">
                  <Folder className="h-4 w-4 text-primary" /> Batch folders
                </div>
                <div className="mt-1 text-[11px] text-muted-foreground">
                  {groupsQuery.data?.total ?? 0} clips across {groups.length} batches
                </div>
              </div>
              <div className="max-h-[calc(100vh-245px)] overflow-y-auto p-2">
                {folderTags.length > 0 && <>
                  <div className="mb-1 mt-1 flex items-center gap-2 px-2 text-[9px] font-semibold uppercase tracking-[0.16em] text-muted-foreground"><Tags className="h-3 w-3 text-primary" /> Tag folders</div>
                  <TagFolderButton active={tagFilter === "all"} label="All tags" onClick={() => setTagFilter("all")} />
                  {folderTags.map((tag) => <TagFolderButton key={tag} active={tagFilter === tag} label={tag} onClick={() => setTagFilter(tag)} />)}
                  <div className="my-2 border-t border-border/40" />
                </>}
                <FolderButton
                  active={folder === "all"}
                  label="All clips"
                  count={groupsQuery.data?.total ?? 0}
                  micro={groupsQuery.data?.micro_total ?? 0}
                  onClick={() => setFolder("all")}
                />
                {groups.map((group) => (
                  <FolderButton
                    key={group.id}
                    active={folder === group.id}
                    label={group.label}
                    count={group.count}
                    micro={group.micro_count}
                    onClick={() => setFolder(group.id)}
                  />
                ))}
              </div>
            </aside>

            <main className="min-w-0">
              <div className="surface-1 mb-4 rounded-xl border border-border/50 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <label className="premium-control flex min-w-[220px] flex-1 items-center gap-2 rounded-lg px-3 py-2">
                    <Search className="h-4 w-4 text-muted-foreground" />
                    <input
                      value={search}
                      onChange={(event) => setSearch(event.target.value)}
                      placeholder="Search clip, batch or trigger..."
                      className="w-full bg-transparent text-sm outline-none"
                    />
                  </label>

                  <div className="premium-control flex rounded-lg p-1">
                    {([
                      { key: "reviewable", label: "Reviewable" },
                      { key: "all", label: "All" },
                      { key: "micro", label: "Micro <4s" },
                    ] as Array<{ key: DurationPreset; label: string }>).map((item) => (
                      <button
                        key={item.key}
                        type="button"
                        onClick={() => setDurationPreset(item.key)}
                        className={cn(
                          "rounded-md px-2.5 py-1.5 text-xs",
                          durationPreset === item.key ? "bg-amber-400 text-black" : "text-muted-foreground hover:text-foreground",
                        )}
                      >
                        {item.label}
                      </button>
                    ))}
                  </div>

                  <label className="premium-control flex items-center gap-2 rounded-lg px-2.5 py-2 text-xs text-muted-foreground">
                    <SlidersHorizontal className="h-3.5 w-3.5" />
                    <select value={sort} onChange={(event) => setSort(event.target.value as SortValue)} className="bg-transparent text-foreground outline-none">
                      <option value="newest">Newest</option>
                      <option value="oldest">Oldest</option>
                      <option value="score">Highest score</option>
                      <option value="duration_desc">Longest</option>
                      <option value="duration_asc">Shortest</option>
                      <option value="size">Largest file</option>
                      <option value="name">Name A-Z</option>
                    </select>
                  </label>

                  <label className="premium-control flex items-center gap-2 rounded-lg px-2.5 py-2 text-xs text-muted-foreground">
                    Score
                    <select value={minScore} onChange={(event) => setMinScore(Number(event.target.value))} className="bg-transparent text-foreground outline-none">
                      <option value={0}>Any</option>
                      <option value={0.7}>70%+</option>
                      <option value={0.8}>80%+</option>
                      <option value={0.9}>90%+</option>
                      <option value={0.95}>95%+</option>
                    </select>
                  </label>

                  <button
                    type="button"
                    role="switch"
                    aria-checked={autoPlay}
                    onClick={() => setAutoPlay((current) => !current)}
                    className={cn(
                      "premium-control flex items-center gap-1.5 rounded-lg px-2.5 py-2 text-xs",
                      autoPlay ? "border-primary/50 bg-primary/15 text-primary" : "text-muted-foreground hover:text-foreground",
                    )}
                    title="Play the next clip using the current filters and sort order"
                  >
                    <Play className="h-3.5 w-3.5" fill={autoPlay ? "currentColor" : "none"} />
                    Autoplay {autoPlay ? "on" : "off"}
                  </button>

                  <button type="button" onClick={refresh} className="premium-control rounded-lg p-2 text-muted-foreground hover:text-foreground" title="Refresh library">
                    <RefreshCw className={cn("h-4 w-4", (clipsQuery.isFetching || groupsQuery.isFetching) && "animate-spin")} />
                  </button>
                </div>

                <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-border/40 pt-3 text-xs">
                  <div className="flex items-center gap-3">
                    <span className="font-medium text-foreground">{selectedGroup?.label ?? "All clips"}</span>
                    {tagFilter !== "all" && <span className="rounded bg-primary/10 px-2 py-0.5 text-primary">#{tagFilter}</span>}
                    <span className="text-muted-foreground">{clips.length} matching</span>
                    {durationPreset === "reviewable" && (groupsQuery.data?.micro_total ?? 0) > 0 && (
                      <span className="flex items-center gap-1 text-amber-300">
                        <AlertTriangle className="h-3.5 w-3.5" /> {groupsQuery.data?.micro_total} micro clips separated
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 text-muted-foreground">
                    {selectedGroup?.avg_duration != null && <span><Clock3 className="mr-1 inline h-3.5 w-3.5" />avg {selectedGroup.avg_duration.toFixed(1)}s</span>}
                    <span><Grid2X2 className="mr-1 inline h-3.5 w-3.5" />page {page + 1}/{pageCount}</span>
                  </div>
                </div>
              </div>

              {clipsQuery.isLoading && <div className="text-sm text-muted-foreground">Indexing clip metadata...</div>}
              {!clipsQuery.isLoading && clips.length === 0 && (
                <div className="surface-1 rounded-xl border border-border/50 p-8 text-center text-sm text-muted-foreground">
                  No clips match these filters. Try All durations or a lower score threshold.
                </div>
              )}

              <div className="grid grid-cols-2 gap-4 md:grid-cols-3 2xl:grid-cols-4">
                {visibleClips.map((clip) => (
                  <ClipTile
                    key={`${clip.group}/${clip.stem}`}
                    bucket={bucket}
                    stem={clip.stem}
                    name={clip.name}
                    sizeMb={clip.size_mb}
                    score={clip.score ?? null}
                    durationSeconds={clip.duration_seconds}
                    group={clip.group}
                    tags={clip.tags}
                    hovered={hoveredStem === clip.stem}
                    onHover={(hovered) => setHoveredStem(hovered ? clip.stem : (current) => current === clip.stem ? null : current)}
                    onOpen={() => openClip(clip.stem)}
                    onLabel={(action) => handleTileLabel(clip.stem, action)}
                    onEditTags={() => setTagEditor(clip)}
                  />
                ))}
              </div>

              {pageCount > 1 && (
                <div className="mt-5 flex items-center justify-center gap-2">
                  <button type="button" disabled={page === 0} onClick={() => setPage((current) => current - 1)} className="premium-control rounded-lg px-4 py-2 text-xs disabled:opacity-40">Previous</button>
                  <span className="px-3 text-xs text-muted-foreground">{page * PAGE_SIZE + 1}-{Math.min((page + 1) * PAGE_SIZE, clips.length)} of {clips.length}</span>
                  <button type="button" disabled={page >= pageCount - 1} onClick={() => setPage((current) => current + 1)} className="premium-control rounded-lg px-4 py-2 text-xs disabled:opacity-40">Next</button>
                </div>
              )}
            </main>
          </div>
        )}
      </PageBody>

      {open && (
        <ClipDetailModal
          bucket={open.bucket}
          stem={open.stem}
          onClose={() => setOpen(null)}
          autoPlay={autoPlay}
          queuePosition={openIndex >= 0 ? openIndex + 1 : undefined}
          queueLength={clips.length}
          onAutoPlayChange={setAutoPlay}
          onPrevious={openIndex > 0 ? () => openQueueIndex(openIndex - 1) : undefined}
          onNext={openIndex >= 0 && openIndex < clips.length - 1 ? () => openQueueIndex(openIndex + 1) : undefined}
          onAutoAdvance={autoAdvanceQueue}
        />
      )}
      {tagEditor && <TagEditorDialog key={`${tagEditor.bucket}/${tagEditor.stem}`} clip={tagEditor} taxonomy={taxonomy} onClose={() => setTagEditor(null)} onSaved={async (tags) => {
        await api.clips.setTags(tagEditor.bucket, tagEditor.stem, tags);
        await qc.invalidateQueries({ queryKey: ["clips"] });
        setTagEditor(null);
      }} />}
      {importOpen && <ImportClipDialog initialBucket={bucket} taxonomy={taxonomy} onClose={() => setImportOpen(false)} onImported={async (target) => {
        setImportOpen(false);
        setView(target);
        setFolder("all");
        setTagFilter("all");
        await qc.invalidateQueries({ queryKey: ["clips"] });
        await qc.invalidateQueries({ queryKey: ["clip-groups"] });
        await qc.invalidateQueries({ queryKey: ["counts"] });
      }} />}
    </>
  );
}

function TagFolderButton({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }) {
  return <button type="button" onClick={onClick} className={cn("mb-1 flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-xs transition", active ? "bg-primary/15 text-primary ring-1 ring-primary/25" : "text-muted-foreground hover:bg-accent/55 hover:text-foreground")}><span className="text-primary/65">#</span><span className="min-w-0 flex-1 truncate capitalize">{label}</span></button>;
}

function DialogShell({ title, detail, onClose, children }: { title: string; detail: string; onClose: () => void; children: React.ReactNode }) {
  return <div className="fixed inset-0 z-[110] grid place-items-center bg-background/80 p-4 backdrop-blur-sm" onMouseDown={onClose}><section role="dialog" aria-modal="true" aria-label={title} data-testid="gallery-dialog" className="glass-strong w-full max-w-lg overflow-hidden rounded-xl border border-border/60 shadow-2xl" onMouseDown={(event) => event.stopPropagation()}><header className="flex items-start gap-3 border-b border-border/50 p-4"><div className="min-w-0 flex-1"><h2 className="text-sm font-semibold">{title}</h2><p className="mt-1 text-xs text-muted-foreground">{detail}</p></div><button type="button" aria-label="Close dialog" onClick={onClose} className="premium-control rounded p-1.5 text-muted-foreground hover:text-foreground"><X className="h-4 w-4" /></button></header><div className="space-y-4 p-4">{children}</div></section></div>;
}

function TagEditorDialog({ clip, taxonomy, onClose, onSaved }: { clip: ClipInfo; taxonomy: { good: string[]; bad: string[] }; onClose: () => void; onSaved: (tags: string[]) => Promise<void> }) {
  const [selected, setSelected] = useState(() => new Set(clip.tags));
  const [custom, setCustom] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const suggested = clip.bucket === "positives" ? taxonomy.good : clip.bucket === "negatives" ? taxonomy.bad : [...taxonomy.good, ...taxonomy.bad];
  const options = [...new Set([...suggested, ...clip.tags])];
  async function save() {
    setSaving(true);
    setError("");
    try {
      const tags = new Set(selected);
      custom.split(",").map((tag) => tag.trim().toLowerCase()).filter(Boolean).forEach((tag) => tags.add(tag));
      await onSaved([...tags]);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : String(nextError));
      setSaving(false);
    }
  }
  return <DialogShell title={`Organize ${clip.stem}`} detail="Tags act like folders and can be combined on the same clip." onClose={onClose}><div className="grid grid-cols-2 gap-2">{options.map((tag) => { const active = selected.has(tag); return <button key={tag} type="button" onClick={() => setSelected((current) => { const next = new Set(current); active ? next.delete(tag) : next.add(tag); return next; })} className={cn("flex items-center gap-2 rounded-lg border px-3 py-2 text-left text-xs", active ? "border-primary/50 bg-primary/10 text-primary" : "border-border/50 text-muted-foreground hover:text-foreground")}><span className={cn("grid h-4 w-4 place-items-center rounded border", active ? "border-primary bg-primary text-primary-foreground" : "border-border")}><Check className={cn("h-3 w-3", !active && "opacity-0")} /></span><span className="truncate capitalize">{tag}</span></button>; })}</div><label className="block text-xs text-muted-foreground">Custom tags, comma-separated<input value={custom} onChange={(event) => setCustom(event.target.value)} placeholder="reaction, chat stream" className="premium-control mt-1.5 w-full rounded-lg px-3 py-2 text-foreground outline-none" /></label>{error && <p className="text-xs text-destructive">{error}</p>}<button type="button" onClick={() => void save()} disabled={saving} className="flex w-full items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50">{saving && <Loader2 className="h-4 w-4 animate-spin" />} Save tags</button></DialogShell>;
}

function ImportClipDialog({ initialBucket, taxonomy, onClose, onImported }: { initialBucket: Bucket; taxonomy: { good: string[]; bad: string[] }; onClose: () => void; onImported: (bucket: Bucket) => Promise<void> }) {
  const [file, setFile] = useState<File | null>(null);
  const [bucket, setBucket] = useState<Bucket>(initialBucket);
  const [group, setGroup] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [custom, setCustom] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const options = bucket === "positives" ? taxonomy.good : bucket === "negatives" ? taxonomy.bad : [...taxonomy.good, ...taxonomy.bad];
  async function submit() {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const tags = new Set(selected);
      custom.split(",").map((tag) => tag.trim().toLowerCase()).filter(Boolean).forEach((tag) => tags.add(tag));
      await api.clips.importClip(file, bucket, group, [...tags]);
      await onImported(bucket);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : String(nextError));
      setBusy(false);
    }
  }
  return <DialogShell title="Import a clip" detail="Add an external video to New, Good, Bad, or Edited and optionally file it under a stream." onClose={onClose}><label className="block rounded-xl border border-dashed border-border p-4 text-center text-xs text-muted-foreground hover:border-primary/50"><Upload className="mx-auto mb-2 h-5 w-5 text-primary" /><span>{file?.name ?? "Choose a video file"}</span><input type="file" accept="video/*,.mkv,.mov,.webm,.avi,.m4v" className="hidden" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /></label><div className="grid grid-cols-2 gap-3"><label className="text-xs text-muted-foreground">Destination<select value={bucket} onChange={(event) => { setBucket(event.target.value as Bucket); setSelected(new Set()); }} className="premium-control mt-1.5 w-full rounded-lg px-3 py-2 text-foreground outline-none"><option value="output">New cuts</option><option value="positives">Good</option><option value="negatives">Bad</option><option value="edited">Edited</option></select></label><label className="text-xs text-muted-foreground">Stream folder<input value={group} onChange={(event) => setGroup(event.target.value)} placeholder="austria_bet" className="premium-control mt-1.5 w-full rounded-lg px-3 py-2 text-foreground outline-none" /></label></div>{options.length > 0 && <div><div className="mb-2 text-xs text-muted-foreground">Tag folders</div><div className="flex flex-wrap gap-1.5">{options.map((tag) => { const active = selected.has(tag); return <button key={tag} type="button" onClick={() => setSelected((current) => { const next = new Set(current); active ? next.delete(tag) : next.add(tag); return next; })} className={cn("rounded-full border px-2.5 py-1 text-[10px] capitalize", active ? "border-primary/50 bg-primary/10 text-primary" : "border-border/50 text-muted-foreground")}>{tag}</button>; })}</div></div>}<label className="block text-xs text-muted-foreground">Custom tags<input value={custom} onChange={(event) => setCustom(event.target.value)} placeholder="raw example, discord" className="premium-control mt-1.5 w-full rounded-lg px-3 py-2 text-foreground outline-none" /></label>{error && <p className="text-xs text-destructive">{error}</p>}<button type="button" onClick={() => void submit()} disabled={!file || busy} className="flex w-full items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />} Import into library</button></DialogShell>;
}

function FolderButton({
  active,
  label,
  count,
  micro,
  onClick,
}: {
  active: boolean;
  label: string;
  count: number;
  micro: number;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "mb-1 flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left transition",
        active ? "bg-primary/15 text-primary ring-1 ring-primary/25" : "text-muted-foreground hover:bg-accent/55 hover:text-foreground",
      )}
    >
      <Folder className={cn("h-4 w-4 shrink-0", active ? "fill-primary/25" : "fill-muted/25")} />
      <span className="min-w-0 flex-1 truncate text-xs font-medium" title={label}>{label}</span>
      <span className="text-[10px] tabular-nums">{count}</span>
      {micro > 0 && <span className="rounded bg-amber-400/15 px-1 py-0.5 text-[9px] text-amber-300" title={`${micro} clips under 4 seconds`}>{micro}</span>}
    </button>
  );
}
