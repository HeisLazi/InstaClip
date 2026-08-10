import { useEffect, useMemo, useRef, useState } from "react";
import { FileAudio, Film, FolderOpen, Image, Loader2, Play, Plus, Search, SlidersHorizontal } from "lucide-react";

import { api, type Bucket, type ClipInfo, type EditorMediaAsset } from "@/api/client";
import { setAssetDrag, type DragAsset } from "@/editor-v2/dnd";
import type { EditorAsset, EditorProjectV2 } from "@/editor-v2/model";
import type { AssetSource } from "@/editor-v2/useEditorProject";
import { cn } from "@/lib/utils";

type Tab = "project" | "clips" | "audio";
type ClipBucket = "all" | "output" | "positives";
type ClipSort = "score" | "newest" | "duration_desc" | "duration_asc" | "name";

export function MediaBin({
  project,
  onRegister,
  onQuickAdd,
  onError,
}: {
  project: EditorProjectV2;
  onRegister: (source: AssetSource) => Promise<EditorAsset>;
  onQuickAdd: (source: AssetSource) => Promise<void>;
  onError: (message: string) => void;
}) {
  const [tab, setTab] = useState<Tab>("project");
  const [clips, setClips] = useState<ClipInfo[]>([]);
  const [sounds, setSounds] = useState<Array<{ name: string; file: string; duration: number }>>([]);
  const [media, setMedia] = useState<EditorMediaAsset[]>([]);
  const [search, setSearch] = useState("");
  const [clipBucket, setClipBucket] = useState<ClipBucket>("all");
  const [clipSort, setClipSort] = useState<ClipSort>("score");
  const [hideMicro, setHideMicro] = useState(true);
  const [importing, setImporting] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    Promise.all([
      api.clips.list("output", { limit: 5000, sortBy: "score" }),
      api.clips.list("positives", { limit: 5000, sortBy: "score" }),
      api.edit.sounds(),
      api.edit.media(),
    ]).then(([output, positives, soundResult, mediaResult]) => {
      setClips([...positives, ...output]);
      setSounds([...soundResult.sounds].sort((left, right) => left.name.localeCompare(right.name)));
      setMedia(mediaResult.assets);
    }).catch((error) => onError(error instanceof Error ? error.message : String(error)));
  }, [onError]);

  async function importFiles(files: FileList | File[]) {
    setImporting(true);
    try {
      for (const file of Array.from(files)) {
        if (file.type.startsWith("audio/") || /\.(wav|mp3|m4a|aac|ogg)$/i.test(file.name)) {
          const result = await api.edit.importSound(file);
          setSounds((current) => [...current.filter((sound) => sound.name !== result.sound.name), result.sound]);
          await onRegister({ type: "sound", soundName: result.sound.name });
        } else {
          const result = await api.edit.importMedia(file);
          setMedia((current) => [...current.filter((asset) => asset.id !== result.asset.id), result.asset]);
          await onRegister({ type: "media", mediaId: result.asset.id });
        }
      }
      setTab("project");
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setImporting(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  const query = search.trim().toLowerCase();
  const projectAssets = useMemo(() => Object.values(project.assets)
    .filter((asset) => asset.kind !== "caption")
    .filter((asset) => !query || asset.name.toLowerCase().includes(query))
    .sort((left, right) => left.name.localeCompare(right.name)), [project.assets, query]);
  const shownClips = useMemo(() => clips
    .filter((clip) => clipBucket === "all" || clip.bucket === clipBucket)
    .filter((clip) => !hideMicro || clip.duration_seconds == null || clip.duration_seconds >= 4)
    .filter((clip) => !query || clip.name.toLowerCase().includes(query) || clip.group.toLowerCase().includes(query))
    .sort((left, right) => {
      if (clipSort === "name") return left.name.localeCompare(right.name);
      if (clipSort === "newest") return right.mtime - left.mtime;
      if (clipSort === "duration_asc") return (left.duration_seconds ?? Number.POSITIVE_INFINITY) - (right.duration_seconds ?? Number.POSITIVE_INFINITY);
      if (clipSort === "duration_desc") return (right.duration_seconds ?? -1) - (left.duration_seconds ?? -1);
      return (right.score ?? right.quality_score ?? -1) - (left.score ?? left.quality_score ?? -1);
    }), [clipBucket, clipSort, clips, hideMicro, query]);
  const shownSounds = useMemo(() => sounds.filter((sound) => !query || sound.name.toLowerCase().includes(query)), [query, sounds]);

  return (
    <section
      className="flex h-full min-h-0 flex-col border-r border-white/10 bg-[#11151a]"
      onDragOver={(event) => {
        if (event.dataTransfer.types.includes("Files")) event.preventDefault();
      }}
      onDrop={(event) => {
        if (event.dataTransfer.files.length) {
          event.preventDefault();
          void importFiles(event.dataTransfer.files);
        }
      }}
    >
      <div className="border-b border-white/10 p-2">
        <div className="flex gap-1">
          {(["project", "clips", "audio"] as Tab[]).map((value) => (
            <button key={value} type="button" onClick={() => setTab(value)} className={cn("rounded px-2 py-1 text-[10px] font-semibold uppercase tracking-wide", tab === value ? "bg-cyan-400/15 text-cyan-300" : "text-slate-500 hover:text-slate-200")}>{value}</button>
          ))}
        </div>
        <label className="mt-2 flex items-center gap-2 rounded border border-white/10 bg-black/30 px-2 py-1.5">
          <Search className="h-3.5 w-3.5 text-slate-500" />
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search media" className="min-w-0 flex-1 bg-transparent text-xs outline-none placeholder:text-slate-600" />
        </label>
        <input ref={inputRef} type="file" multiple accept="video/*,image/*,audio/*,.mkv,.mov,.webm,.wav,.mp3,.m4a" className="hidden" onChange={(event) => event.target.files && void importFiles(event.target.files)} />
        <button type="button" onClick={() => inputRef.current?.click()} disabled={importing} className="mt-2 flex w-full items-center justify-center gap-1.5 rounded border border-dashed border-white/15 py-1.5 text-[10px] text-slate-400 hover:border-cyan-400/50 hover:text-cyan-300 disabled:opacity-50">
          {importing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />} Import or drop files
        </button>
        {tab === "clips" && <div className="mt-2 space-y-1.5 rounded border border-white/10 bg-black/20 p-1.5">
          <div className="grid grid-cols-2 gap-1">
            <label className="flex items-center gap-1 text-[8px] uppercase tracking-wide text-slate-600"><SlidersHorizontal className="h-3 w-3" /><select value={clipBucket} onChange={(event) => setClipBucket(event.target.value as ClipBucket)} className="min-w-0 flex-1 bg-transparent text-[9px] normal-case text-slate-300 outline-none"><option value="all">Good + New</option><option value="positives">Good only</option><option value="output">New only</option></select></label>
            <select value={clipSort} onChange={(event) => setClipSort(event.target.value as ClipSort)} className="min-w-0 rounded border border-white/10 bg-[#11151a] px-1 text-[9px] text-slate-300 outline-none"><option value="score">Highest score</option><option value="newest">Newest</option><option value="duration_desc">Longest</option><option value="duration_asc">Shortest</option><option value="name">Name A-Z</option></select>
          </div>
          <label className="flex items-center justify-between text-[9px] text-slate-500"><span>Hide clips under 4 seconds</span><input type="checkbox" checked={hideMicro} onChange={(event) => setHideMicro(event.target.checked)} className="accent-cyan-400" /></label>
        </div>}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {tab === "project" && <div className="grid grid-cols-2 gap-2">{projectAssets.map((asset) => <AssetCard key={asset.id} asset={asset} project={project} source={{ type: "asset", asset }} onQuickAdd={onQuickAdd} />)}</div>}
        {tab === "clips" && <><div className="mb-1 px-2 text-[8px] text-slate-600">{shownClips.length} sorted clips · drag or use +</div><div className="space-y-1">{shownClips.map((clip) => <SourceRow key={`${clip.bucket}/${clip.stem}`} icon={<Film className="h-3.5 w-3.5" />} label={clip.stem} detail={`${Math.round((clip.score ?? clip.quality_score ?? 0) * 100)}% · ${clip.group} · ${(clip.duration_seconds ?? 0).toFixed(1)}s`} source={{ type: "clip", bucket: clip.bucket as Bucket, stem: clip.stem }} onQuickAdd={onQuickAdd} />)}</div></>}
        {tab === "audio" && <div className="space-y-1">{shownSounds.map((sound) => <SourceRow key={sound.name} icon={<FileAudio className="h-3.5 w-3.5" />} label={sound.name} detail={`${sound.duration.toFixed(1)}s`} source={{ type: "sound", soundName: sound.name }} previewUrl={api.edit.soundUrl(sound.name)} onQuickAdd={onQuickAdd} />)}</div>}
        {tab === "project" && projectAssets.length === 0 && <Empty />}
        {tab === "clips" && shownClips.length === 0 && <Empty />}
        {tab === "audio" && shownSounds.length === 0 && <Empty />}
      </div>
      {media.length > 0 && tab === "project" && <div className="border-t border-white/10 px-2 py-1 text-[9px] text-slate-600">{media.length} imported media files available</div>}
    </section>
  );
}

function AssetCard({ asset, project, source, onQuickAdd }: { asset: EditorAsset; project: EditorProjectV2; source: DragAsset; onQuickAdd: (source: AssetSource) => Promise<void> }) {
  const Icon = asset.kind === "audio" ? FileAudio : asset.kind === "image" ? Image : Film;
  return (
    <div role="button" tabIndex={0} draggable onDragStart={(event) => setAssetDrag(event, source)} onDoubleClick={() => void onQuickAdd(source)} onKeyDown={(event) => { if (event.key === "Enter") void onQuickAdd(source); }} className="group relative overflow-hidden rounded border border-white/10 bg-black/25 text-left hover:border-cyan-400/45 focus:border-cyan-400/60 focus:outline-none">
      <div className="relative grid aspect-video place-items-center bg-black/50">
        {asset.kind === "audio" ? <Icon className="h-6 w-6 text-emerald-400" /> : <img src={api.edit.v2.thumbnailUrl(project.id, asset.id)} alt="" className="h-full w-full object-cover" />}
        <span className="absolute bottom-1 right-1 rounded bg-black/75 px-1 text-[8px] text-white">{asset.kind}</span>
      </div>
      <div className="truncate px-1.5 py-1 text-[10px] text-slate-300">{asset.name}</div>
      <button type="button" onClick={() => void onQuickAdd(source)} className="absolute right-1 top-1 grid h-5 w-5 place-items-center rounded bg-black/75 text-cyan-300 opacity-0 group-hover:opacity-100" title="Add at playhead"><Plus className="h-3 w-3" /></button>
    </div>
  );
}

function SourceRow({ icon, label, detail, source, previewUrl, onQuickAdd }: { icon: React.ReactNode; label: string; detail: string; source: DragAsset; previewUrl?: string; onQuickAdd: (source: AssetSource) => Promise<void> }) {
  function preview(event: React.MouseEvent) {
    event.stopPropagation();
    if (!previewUrl) return;
    const audio = new Audio(previewUrl);
    audio.volume = 0.85;
    void audio.play();
  }
  return (
    <div role="button" tabIndex={0} draggable onDragStart={(event) => setAssetDrag(event, source)} onDoubleClick={() => void onQuickAdd(source)} onKeyDown={(event) => { if (event.key === "Enter") void onQuickAdd(source); }} className="flex w-full items-center gap-2 rounded border border-transparent px-2 py-1.5 text-left hover:border-white/10 hover:bg-white/5 focus:border-cyan-400/40 focus:outline-none">
      <span className="text-cyan-400">{icon}</span>
      <span className="min-w-0 flex-1"><span className="block truncate text-[10px] text-slate-300">{label}</span><span className="block truncate text-[8px] text-slate-600">{detail}</span></span>
      {previewUrl && <button type="button" onClick={preview} className="grid h-5 w-5 shrink-0 place-items-center rounded text-slate-600 hover:bg-white/5 hover:text-emerald-300" title="Preview sound"><Play className="h-2.5 w-2.5" fill="currentColor" /></button>}
      <button type="button" onClick={(event) => { event.stopPropagation(); void onQuickAdd(source); }} className="grid h-5 w-5 shrink-0 place-items-center rounded text-slate-600 hover:bg-cyan-400/10 hover:text-cyan-300" title="Add at playhead"><Plus className="h-3 w-3" /></button>
    </div>
  );
}

function Empty() {
  return <div className="grid h-32 place-items-center text-center text-[10px] text-slate-600"><span><FolderOpen className="mx-auto mb-2 h-6 w-6" />No matching media</span></div>;
}
