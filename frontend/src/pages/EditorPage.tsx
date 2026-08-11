/**
 * Editor workspace tab — pick any clip (output / good / edited) and open the
 * full editor directly, without going through the Gallery review flow.
 */

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FileVideo2, FolderOpen, Scissors, Search, TimerReset } from "lucide-react";

import { api, type Bucket, type ClipInfo } from "@/api/client";
import { EditorV2Modal } from "@/editor-v2/EditorV2Modal";
import { EditorModal } from "@/components/EditorModal";
import { cn } from "@/lib/utils";
import { pickVodFile } from "@/lib/tauri";
import { PageHeader, PageBody } from "./_shared";

const BUCKETS: { key: Bucket; label: string }[] = [
  { key: "output", label: "Newly cut" },
  { key: "positives", label: "Good clips" },
  { key: "edited", label: "Edited" },
];

export function EditorPage() {
  const qc = useQueryClient();
  const [bucket, setBucket] = useState<Bucket>("output");
  const [search, setSearch] = useState("");
  const [localPath, setLocalPath] = useState("");
  const [editing, setEditing] = useState<{ bucket: Bucket; stem: string; mode: "v2" | "legacy"; localPath?: string; projectId?: string } | null>(null);

  async function chooseLocalVod() {
    const chosen = await pickVodFile();
    if (chosen) {
      setLocalPath(chosen);
      openLocalVod(chosen);
    }
  }

  function openLocalVod(path = localPath) {
    const clean = path.trim();
    if (!clean) return;
    const stem = clean.split(/[\\/]/).pop()?.replace(/\.[^.]+$/, "") || "YouTube project";
    setEditing({ bucket: "output", stem, mode: "v2", localPath: clean });
  }

  const { data: clips = [], isLoading } = useQuery({
    queryKey: ["editor-clips", bucket, search.trim()],
    queryFn: () => api.clips.list(bucket, { search: search.trim() || undefined, limit: 300 }),
  });
  const { data: projectData } = useQuery({
    queryKey: ["editor-v2-projects"],
    queryFn: () => api.edit.v2.projects(),
  });
  const projects = projectData?.projects ?? [];

  return (
    <>
      <PageHeader
        title="Editor"
        subtitle="Pick a clip and edit it — trim, crop, reframe, full-cam blur, audio, sound FX, transitions."
      />
      <PageBody>
        <section className="premium-card mb-4 rounded-xl border border-cyan-300/20 surface-1 p-4">
          <div className="flex items-start gap-3">
            <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-cyan-300/25 bg-cyan-300/[0.08] text-cyan-200"><FileVideo2 className="h-4 w-4" /></div>
            <div className="min-w-0 flex-1"><div className="text-sm font-semibold">Open a full VOD in place</div><p className="mt-1 text-xs text-muted-foreground">Creates a durable 16:9 YouTube project without copying the multi-gigabyte source file.</p></div>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <input value={localPath} onChange={(event) => setLocalPath(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") openLocalVod(); }} placeholder="C:\\Streams\\my-vod.mp4" className="premium-control min-w-[280px] flex-1 rounded-md px-3 py-2 text-xs outline-none" />
            <button type="button" onClick={() => void chooseLocalVod()} className="premium-control inline-flex items-center gap-2 rounded-md px-3 py-2 text-xs"><FolderOpen className="h-3.5 w-3.5" /> Browse</button>
            <button type="button" disabled={!localPath.trim()} onClick={() => openLocalVod()} className="inline-flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground disabled:opacity-40"><Scissors className="h-3.5 w-3.5" /> Open YouTube project</button>
          </div>
        </section>
        {projects.length > 0 && <section className="mb-5">
          <div className="mb-2 flex items-center justify-between"><div><h2 className="text-sm font-semibold">Saved projects</h2><p className="text-[11px] text-muted-foreground">Long-form projects stay separate from standalone social clips.</p></div><span className="text-[10px] tabular-nums text-muted-foreground">{projects.length} projects</span></div>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {projects.slice(0, 12).map((project) => <button key={project.id} type="button" onClick={() => setEditing({ bucket: "output", stem: project.name, mode: "v2", projectId: project.id })} className="premium-card group rounded-lg border border-white/10 surface-1 p-3 text-left hover:border-cyan-300/35">
              <div className="flex items-start gap-2"><div className="grid h-8 w-8 shrink-0 place-items-center rounded-md bg-cyan-300/[0.08] text-cyan-300"><TimerReset className="h-4 w-4" /></div><div className="min-w-0 flex-1"><div className="truncate text-xs font-semibold">{project.name}</div><div className="mt-1 flex flex-wrap gap-1"><span className={cn("rounded px-1.5 py-0.5 text-[8px] font-bold uppercase tracking-wide", project.contentMode === "long_form" ? "bg-amber-300/10 text-amber-200" : "bg-cyan-300/10 text-cyan-200")}>{project.contentMode === "long_form" ? "Long form" : "Short form"}</span>{project.strategy && <span className="rounded bg-white/5 px-1.5 py-0.5 text-[8px] uppercase text-muted-foreground">{project.strategy.replace("_", " ")}</span>}{Boolean(project.chapterCount) && <span className="rounded bg-emerald-300/[0.07] px-1.5 py-0.5 text-[8px] text-emerald-200">{project.chapterCount} chapters</span>}{Boolean(project.captionCount) && <span className="rounded bg-amber-300/[0.07] px-1.5 py-0.5 text-[8px] text-amber-200">{project.captionCount} captions</span>}</div></div><span className="text-[9px] tabular-nums text-muted-foreground">{Math.round(project.duration / 60)}m</span></div>
            </button>)}
          </div>
        </section>}
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex gap-1">
            {BUCKETS.map((b) => (
              <button
                key={b.key}
                onClick={() => setBucket(b.key)}
                className={cn(
                  "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                  bucket === b.key ? "bg-primary text-primary-foreground" : "bg-secondary/60 hover:bg-secondary",
                )}
              >
                {b.label}
              </button>
            ))}
          </div>
          <div className="relative ml-auto min-w-[220px] flex-1 max-w-xs">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search clips…"
              className="w-full rounded-md bg-secondary/60 pl-8 pr-3 py-1.5 text-sm outline-none focus:ring-1 focus:ring-primary placeholder:text-muted-foreground"
            />
          </div>
        </div>

        {isLoading ? (
          <div className="mt-8 text-sm text-muted-foreground">Loading clips…</div>
        ) : clips.length === 0 ? (
          <div className="mt-8 text-sm text-muted-foreground">No clips in this bucket{search ? " matching your search" : ""}.</div>
        ) : (
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
            {clips.map((clip: ClipInfo) => (
              <button
                key={`${clip.bucket}/${clip.stem}`}
                onClick={() => setEditing({ bucket, stem: clip.stem, mode: "v2" })}
                className="group relative overflow-hidden rounded-lg border border-border/50 bg-black/40 text-left transition-colors hover:border-primary/60"
                title={`Edit ${clip.stem}`}
              >
                <div className="aspect-video w-full bg-black/60">
                  {clip.has_thumbnail && (
                    <img src={api.clips.thumbUrl(bucket, clip.stem)} alt={clip.stem}
                         className="h-full w-full object-cover" loading="lazy" />
                  )}
                </div>
                <div className="flex items-center gap-1.5 px-2 py-1.5">
                  <span className="truncate text-[11px] text-foreground/90">{clip.stem}</span>
                </div>
                <div className="absolute inset-0 grid place-items-center bg-background/55 opacity-0 transition-opacity group-hover:opacity-100">
                  <span className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground">
                    <Scissors className="h-3.5 w-3.5" /> Edit
                  </span>
                </div>
              </button>
            ))}
          </div>
        )}
      </PageBody>

      {editing?.mode === "v2" && (
        <EditorV2Modal
          bucket={editing.bucket}
          stem={editing.stem}
          localPath={editing.localPath}
          projectId={editing.projectId}
          onOpenProject={(projectId, name) => {
            qc.invalidateQueries({ queryKey: ["editor-v2-projects"] });
            setEditing({ bucket: "output", stem: name, mode: "v2", projectId });
          }}
          onClose={() => setEditing(null)}
          onLegacy={editing.localPath || editing.projectId ? undefined : () => setEditing({ ...editing, mode: "legacy" })}
          onRendered={() => {
            qc.invalidateQueries({ queryKey: ["editor-clips"] });
            qc.invalidateQueries({ queryKey: ["clips"] });
          }}
        />
      )}
      {editing?.mode === "legacy" && (
        <EditorModal
          bucket={editing.bucket}
          stem={editing.stem}
          onClose={() => setEditing(null)}
          onRendered={() => {
            qc.invalidateQueries({ queryKey: ["editor-clips"] });
            qc.invalidateQueries({ queryKey: ["clips"] });
          }}
        />
      )}
    </>
  );
}
