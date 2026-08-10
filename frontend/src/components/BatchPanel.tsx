/**
 * Batch picker — lists every local VOD with a checkbox.
 * The user explicitly selects which ones go into the batch.
 * Lives on the Dashboard.
 */

import { useDeferredValue, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  CheckSquare,
  FolderOpen,
  Loader2,
  PlayCircle,
  Search,
  SlidersHorizontal,
  Square,
  X,
} from "lucide-react";

import { api } from "@/api/client";
import { filterBatchVods, type BatchSizeFilter, type BatchSort, type BatchStatusFilter } from "@/components/batchFilters";
import { cn } from "@/lib/utils";

export function BatchPanel() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["local-vods"],
    queryFn:  api.pipeline.localVods,
    refetchInterval: 30000,
  });

  const vods = useMemo(() => data?.vods ?? [], [data]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [filter,   setFilter]   = useState("");
  const [status, setStatus] = useState<BatchStatusFilter>("all");
  const [size, setSize] = useState<BatchSizeFilter>("all");
  const [sort, setSort] = useState<BatchSort>("newest");
  const [busy, setBusy]   = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info,  setInfo]  = useState<string | null>(null);

  const deferredFilter = useDeferredValue(filter.trim().toLowerCase());
  const filtered = useMemo(() => filterBatchVods(vods, {
    query: deferredFilter,
    status,
    size,
    sort,
  }), [vods, deferredFilter, status, size, sort]);

  function toggle(path: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(path) ? next.delete(path) : next.add(path);
      return next;
    });
  }

  function selectAllFiltered() {
    setSelected((prev) => {
      const next = new Set(prev);
      for (const v of filtered) next.add(v.path);
      return next;
    });
  }
  function clearSelection() { setSelected(new Set()); }
  function selectUnprocessed() {
    setSelected(new Set(filtered.filter((v) => !v.transcribed).map((v) => v.path)));
  }
  function resetFilters() {
    setFilter("");
    setStatus("all");
    setSize("all");
    setSort("newest");
  }

  async function start() {
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const paths = Array.from(selected);
      if (paths.length === 0) {
        setError("Select at least one VOD.");
        return;
      }
      const { job_id, queued } = await api.pipeline.batch({ paths });
      qc.invalidateQueries({ queryKey: ["jobs"] });
      setInfo(`Batch started — ${queued} VOD(s) queued · job ${job_id}`);
      setSelected(new Set());
    } catch (e: any) {
      setError(e.message ?? "Batch kick-off failed");
    } finally {
      setBusy(false);
    }
  }

  const totalSel = selected.size;
  const unprocessedCount = vods.filter((v) => !v.transcribed).length;

  return (
    <div className="premium-card rounded-xl surface-1 border border-border/50 p-4">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <div className="text-sm font-semibold">Batch</div>
          <div className="text-xs text-muted-foreground mt-0.5 break-all">
            <FolderOpen className="inline h-3 w-3 mr-1 -mt-0.5" />
            {data?.folder ?? "Loading…"}
          </div>
          <div className="text-xs text-muted-foreground mt-1">
            {isLoading
              ? "Scanning folder…"
              : `${vods.length} VODs · ${unprocessedCount} unprocessed · ${totalSel} selected`}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={start}
            disabled={busy || totalSel === 0}
            className={cn(
              "px-3 py-1.5 rounded-md text-sm font-medium flex items-center gap-1.5",
              busy
                ? "bg-primary/60 text-primary-foreground cursor-not-allowed"
                : totalSel === 0
                  ? "bg-secondary text-muted-foreground cursor-not-allowed"
                  : "bg-primary text-primary-foreground hover:bg-primary/90",
            )}
          >
            {busy
              ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
              : <PlayCircle className="h-3.5 w-3.5" />}
            Run batch {totalSel > 0 && `(${totalSel})`}
          </button>
        </div>
      </div>

      {/* Filters + quick actions */}
      <div className="mt-3 grid gap-2 md:grid-cols-[minmax(220px,1fr)_auto_auto_auto]">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Search VOD names…"
            className="w-full bg-secondary/60 pl-7 pr-2 py-1.5 rounded text-xs outline-none focus:ring-1 focus:ring-primary placeholder:text-muted-foreground"
          />
        </div>
        <label className="sr-only" htmlFor="batch-status-filter">Transcript status</label>
        <select id="batch-status-filter" value={status} onChange={(event) => setStatus(event.target.value as typeof status)} className="premium-control rounded px-2 py-1.5 text-xs outline-none">
          <option value="all">All transcript states</option>
          <option value="unprocessed">Needs transcript</option>
          <option value="transcribed">Transcript ready</option>
        </select>
        <label className="sr-only" htmlFor="batch-size-filter">File size</label>
        <select id="batch-size-filter" value={size} onChange={(event) => setSize(event.target.value as typeof size)} className="premium-control rounded px-2 py-1.5 text-xs outline-none">
          <option value="all">All sizes</option>
          <option value="small">Under 1 GB</option>
          <option value="medium">1-5 GB</option>
          <option value="large">5 GB and above</option>
        </select>
        <label className="sr-only" htmlFor="batch-sort">Sort VODs</label>
        <select id="batch-sort" value={sort} onChange={(event) => setSort(event.target.value as typeof sort)} className="premium-control rounded px-2 py-1.5 text-xs outline-none">
          <option value="newest">Newest first</option>
          <option value="oldest">Oldest first</option>
          <option value="name">Name A-Z</option>
          <option value="largest">Largest first</option>
          <option value="smallest">Smallest first</option>
        </select>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground"><SlidersHorizontal className="h-3 w-3" /> {filtered.length} of {vods.length} shown</span>
        <button
          onClick={selectUnprocessed}
          className="text-[11px] px-2 py-1 rounded border border-border/60 text-muted-foreground hover:text-foreground hover:bg-accent"
        >
          Select shown unprocessed
        </button>
        <button
          onClick={selectAllFiltered}
          className="text-[11px] px-2 py-1 rounded border border-border/60 text-muted-foreground hover:text-foreground hover:bg-accent"
        >
          Select all (filter)
        </button>
        <button
          onClick={clearSelection}
          className="text-[11px] px-2 py-1 rounded border border-border/60 text-muted-foreground hover:text-foreground hover:bg-accent"
        >
          Clear
        </button>
        {(filter || status !== "all" || size !== "all" || sort !== "newest") && <button type="button" onClick={resetFilters} className="ml-auto inline-flex items-center gap-1 rounded border border-border/60 px-2 py-1 text-[11px] text-muted-foreground hover:bg-accent hover:text-foreground"><X className="h-3 w-3" /> Reset filters</button>}
      </div>

      {/* VOD list */}
      <div className="mt-3 max-h-72 overflow-y-auto rounded-md border border-border/40">
        {filtered.length === 0 && (
          <div className="px-3 py-6 text-center text-xs text-muted-foreground italic">
            {isLoading ? "Loading…" : "No VODs match this filter."}
          </div>
        )}
        {filtered.map((v) => {
          const isSel = selected.has(v.path);
          return (
            <button
              key={v.path}
              onClick={() => toggle(v.path)}
              className={cn(
                "w-full flex items-center gap-2.5 px-3 py-2 text-left transition-colors",
                "border-b border-border/30 last:border-b-0",
                isSel ? "bg-primary/10" : "hover:bg-accent/30",
              )}
            >
              {isSel
                ? <CheckSquare className="h-4 w-4 text-primary shrink-0" />
                : <Square     className="h-4 w-4 text-muted-foreground shrink-0" />}

              <span className="flex-1 truncate text-xs" title={v.name}>{v.name}</span>

              {v.transcribed && (
                <span title="Transcript already cached — will be reused" className="shrink-0">
                  <CheckCircle2 className="h-3 w-3 text-success" />
                </span>
              )}
              <span className="text-[10px] text-muted-foreground tabular-nums shrink-0 w-20 text-right">
                {v.size_mb.toFixed(0)} MB
              </span>
              <span className="hidden w-20 shrink-0 text-right text-[9px] tabular-nums text-muted-foreground/70 sm:block">
                {new Date(v.mtime * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "2-digit" })}
              </span>
            </button>
          );
        })}
      </div>

      {error && <div className="mt-3 text-xs text-destructive">{error}</div>}
      {info  && <div className="mt-3 text-xs text-success">{info}</div>}
    </div>
  );
}
