/**
 * Gallery "By stream" view — clips you've labelled Good grouped by which
 * source VOD they came from. Useful for the editing workflow.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, FolderOpen, Layers, RefreshCw } from "lucide-react";

import { api } from "@/api/client";
import { ClipDetailModal } from "@/components/ClipDetailModal";
import { ConfidenceRing } from "@/components/ConfidenceRing";
import { cn } from "@/lib/utils";

export function KeepersView() {
  const qc = useQueryClient();
  const groups = useQuery({
    queryKey: ["keepers-groups"],
    queryFn:  api.clips.keeperGroups,
    refetchInterval: 15000,
  });

  const backfill = useMutation({
    mutationFn: () => api.clips.keeperBackfill(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["keepers-groups"] }),
  });

  // Track which streams are expanded; default first one open.
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<{ stem: string } | null>(null);

  function toggle(vod: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(vod) ? next.delete(vod) : next.add(vod);
      return next;
    });
  }

  const list = groups.data?.groups ?? [];

  // Auto-expand the first group on first load.
  if (expanded.size === 0 && list.length > 0) {
    expanded.add(list[0].vod_stem);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div className="text-xs text-muted-foreground">
          {groups.data ? (
            <>
              <FolderOpen className="inline h-3 w-3 mr-1 -mt-0.5" />
              {groups.data.folder} · {list.length} stream{list.length === 1 ? "" : "s"}
            </>
          ) : (
            "Loading…"
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => backfill.mutate()}
            disabled={backfill.isPending}
            className="text-[11px] px-2 py-1 rounded border border-border/60 text-muted-foreground hover:text-foreground hover:bg-accent flex items-center gap-1"
            title="Walk data/old_clips and link anything we can attribute to a VOD"
          >
            <Layers className="h-3 w-3" /> Backfill from positives
          </button>
          <button
            onClick={() => qc.invalidateQueries({ queryKey: ["keepers-groups"] })}
            className="text-[11px] px-2 py-1 rounded border border-border/60 text-muted-foreground hover:text-foreground hover:bg-accent flex items-center gap-1"
          >
            <RefreshCw className="h-3 w-3" /> Refresh
          </button>
        </div>
      </div>

      {!groups.isLoading && list.length === 0 && (
        <div className="rounded-lg border border-dashed border-border/60 p-8 text-center text-sm text-muted-foreground">
          Nothing here yet. Label clips as Good in the "Newly cut" view and they'll be grouped here
          by source stream. Or hit <span className="text-foreground">Backfill from positives</span>{" "}
          to link any clips already in <code>data/old_clips/</code>.
        </div>
      )}

      {list.map((g) => {
        const isOpen = expanded.has(g.vod_stem);
        return (
          <section key={g.vod_stem} className="premium-card rounded-lg border border-border/50 surface-1 overflow-hidden">
            <button
              onClick={() => toggle(g.vod_stem)}
              className="w-full flex items-center gap-3 px-4 py-3 hover:bg-accent/20 transition-colors text-left"
            >
              <ChevronRight className={cn(
                "h-4 w-4 text-muted-foreground transition-transform",
                isOpen && "rotate-90",
              )} />
              <FolderOpen className="h-4 w-4 text-primary" />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium truncate">{g.vod_stem}</div>
                <div className="text-[11px] text-muted-foreground">
                  {g.count} clip{g.count === 1 ? "" : "s"}
                </div>
              </div>
              <code className="text-[10px] text-muted-foreground truncate max-w-[36%]" title={g.folder}>
                {g.folder}
              </code>
            </button>

            {isOpen && (
              <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3 p-3 pt-0">
                {g.clips.map((c) => (
                  <button
                    key={c.stem}
                    onClick={() => setOpen({ stem: c.stem })}
                    className="group text-left rounded-md overflow-hidden border border-border/60 hover:border-primary/40 surface-2 transition-colors"
                  >
                    <div className="relative aspect-video bg-secondary/40">
                      <img
                        src={api.clips.keeperThumbUrl(g.vod_stem, c.stem)}
                        alt={c.name}
                        loading="lazy"
                        className="w-full h-full object-cover group-hover:scale-[1.02] transition-transform"
                      />
                      {c.score != null && (
                        <div className="absolute top-1.5 right-1.5 pointer-events-none">
                          <div className="rounded-full bg-black/55 p-0.5 backdrop-blur-sm">
                            <ConfidenceRing value={c.score} size={32} stroke={3} />
                          </div>
                        </div>
                      )}
                    </div>
                    <div className="p-2.5">
                      <div className="text-[11px] font-medium truncate" title={c.name}>{c.name}</div>
                      <div className="text-[10px] text-muted-foreground mt-0.5">{c.size_mb.toFixed(1)} MB</div>
                    </div>
                  </button>
                ))}
                {g.clips.length === 0 && (
                  <div className="col-span-full text-xs italic text-muted-foreground py-4">
                    No clips in this folder yet.
                  </div>
                )}
              </div>
            )}
          </section>
        );
      })}

      {open && (
        <ClipDetailModal
          bucket="positives"
          stem={open.stem}
          onClose={() => setOpen(null)}
        />
      )}
    </div>
  );
}
