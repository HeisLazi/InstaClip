import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { Maximize2, Pause, Play, Volume2 } from "lucide-react";

import { api } from "@/api/client";
import { activeVideoItemsAtTime, allItems, itemEnd, type EditorProjectV2, type TimelineItem, type VideoTransform } from "@/editor-v2/model";
import { cn } from "@/lib/utils";

export function Preview({
  project,
  playhead,
  playing,
  onPlayingChange,
  onSeek,
  onTransform,
}: {
  project: EditorProjectV2;
  playhead: number;
  playing: boolean;
  onPlayingChange: (playing: boolean) => void;
  onSeek: (time: number) => void;
  onTransform: (itemId: string, transform: Partial<VideoTransform>) => void;
}) {
  const mediaRefs = useRef(new Map<string, HTMLVideoElement>());
  const audioRefs = useRef(new Map<string, HTMLAudioElement>());
  const activeVisuals = activeVideoItemsAtTime(project, playhead);
  const activeCaptions = project.tracks
    .filter((track) => track.kind === "caption" && !track.hidden)
    .flatMap((track) => track.items)
    .filter((item) => item.enabled && item.caption && playhead >= item.timelineStart && playhead < itemEnd(item));
  const fadeOverlay = transitionOverlay(project, playhead);
  const duration = Math.max(0.01, ...allItems(project).map(itemEnd));
  const audioLayers = useMemo(() => {
    const hasSolo = project.tracks.some((track) => track.kind === "audio" && track.solo);
    return project.tracks.flatMap((track) => track.items.map((item) => ({ track, item }))).filter(({ track, item }) => {
      const asset = project.assets[item.assetId];
      if (!item.audio || !asset?.hasAudio || track.muted || !item.enabled || item.audio.volume <= 0) return false;
      return track.kind !== "audio" || !hasSolo || track.solo;
    });
  }, [project]);

  useEffect(() => {
    for (const { item } of activeVisuals) {
      const video = mediaRefs.current.get(item.id);
      if (!video) continue;
      const wanted = item.sourceIn + (playhead - item.timelineStart) * item.speed;
      if (Number.isFinite(video.duration) && Math.abs(video.currentTime - wanted) > 0.18) video.currentTime = wanted;
      video.playbackRate = item.speed;
      if (playing) void video.play().catch(() => undefined);
      else video.pause();
    }

    for (const { item } of audioLayers) {
      const audio = audioRefs.current.get(item.id);
      if (!audio) continue;
      const active = playhead >= item.timelineStart && playhead < itemEnd(item);
      if (!active) {
        audio.pause();
        continue;
      }
      const wanted = item.sourceIn + (playhead - item.timelineStart) * item.speed;
      if (Math.abs(audio.currentTime - wanted) > 0.18) audio.currentTime = wanted;
      audio.playbackRate = item.speed;
      audio.volume = Math.max(0, Math.min(1, item.audio?.volume ?? 1));
      if (playing) void audio.play().catch(() => undefined);
      else audio.pause();
    }
  }, [activeVisuals, audioLayers, playhead, playing]);

  return (
    <section className="flex min-h-0 flex-1 flex-col bg-[#090c0f]">
      <div className="flex min-h-0 flex-1 items-center justify-center overflow-hidden p-3">
        <div
          data-preview-canvas
          className="relative h-full max-h-full max-w-full overflow-hidden border border-white/15 bg-black shadow-[0_20px_70px_rgba(0,0,0,.6)]"
          style={{ aspectRatio: `${project.canvas.width}/${project.canvas.height}`, background: project.canvas.background, containerType: "size" }}
        >
          {activeVisuals.map(({ item }) => (
            <VisualLayer key={item.id} project={project} item={item} playhead={playhead} setRef={(element) => {
              if (element) mediaRefs.current.set(item.id, element);
              else mediaRefs.current.delete(item.id);
            }} />
          ))}
          {activeVisuals.map(({ item }) => project.selection.itemIds.includes(item.id) && (
            <TransformBox key={`box-${item.id}`} project={project} item={item} onTransform={onTransform} />
          ))}
          {activeVisuals.length === 0 && <div className="absolute inset-0 grid place-items-center text-[10px] uppercase tracking-[0.2em] text-slate-700">No video at playhead</div>}
          {activeCaptions.map((item) => <CaptionLayer key={item.id} project={project} item={item} playhead={playhead} />)}
          {fadeOverlay && <div className="pointer-events-none absolute inset-0 z-[70]" style={{ backgroundColor: fadeOverlay.color, opacity: fadeOverlay.opacity }} />}
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-black/55 to-transparent" />
          <div className="pointer-events-none absolute bottom-2 left-2 flex items-center gap-1 rounded bg-black/65 px-1.5 py-1 text-[8px] text-white/70"><Volume2 className="h-2.5 w-2.5" /> Live layered audio</div>
        </div>
      </div>

      {audioLayers.map(({ item }) => (
        <audio
          key={item.id}
          ref={(element) => {
            if (element) audioRefs.current.set(item.id, element);
            else audioRefs.current.delete(item.id);
          }}
          src={api.edit.v2.audioProxyUrl(project.id, item.assetId)}
          preload="auto"
        />
      ))}

      <div className="flex h-11 shrink-0 items-center gap-3 border-t border-white/10 bg-[#10151a] px-3">
        <button type="button" onClick={() => onPlayingChange(!playing)} className="grid h-7 w-7 place-items-center rounded-full bg-slate-100 text-slate-950 hover:bg-cyan-300" aria-label={playing ? "Pause" : "Play"}>{playing ? <Pause className="h-3.5 w-3.5" fill="currentColor" /> : <Play className="ml-0.5 h-3.5 w-3.5" fill="currentColor" />}</button>
        <span className="w-20 text-[10px] tabular-nums text-slate-400">{formatClock(playhead)} / {formatClock(duration)}</span>
        <input type="range" min={0} max={duration} step={0.01} value={Math.min(playhead, duration)} onChange={(event) => onSeek(Number(event.target.value))} className="min-w-0 flex-1 accent-cyan-400" aria-label="Preview playhead" />
        <Maximize2 className="h-3.5 w-3.5 text-slate-600" />
      </div>
    </section>
  );
}

function VisualLayer({ project, item, playhead, setRef }: { project: EditorProjectV2; item: TimelineItem; playhead: number; setRef: (element: HTMLVideoElement | null) => void }) {
  const asset = project.assets[item.assetId];
  const transform = item.video!;
  const style: React.CSSProperties = {
    left: `${transform.x / project.canvas.width * 100}%`,
    top: `${transform.y / project.canvas.height * 100}%`,
    width: `${transform.width / project.canvas.width * 100}%`,
    height: `${transform.height / project.canvas.height * 100}%`,
    opacity: transform.opacity * mixOpacity(project, item, playhead),
    transform: `rotate(${transform.rotation}deg)`,
    filter: transform.blur ? `blur(${transform.blur}px)` : undefined,
  };
  const objectFit = transform.fit === "stretch" ? "fill" : transform.fit;
  const mediaStyle = cropMediaStyle(asset.width, asset.height, transform);
  return (
    <div className="absolute overflow-hidden" style={style}>
      {asset.kind === "image" ? (
        <img src={api.edit.v2.streamUrl(project.id, asset.id)} alt="" draggable={false} className={mediaStyle ? "absolute max-w-none" : "h-full w-full"} style={mediaStyle ?? { objectFit }} />
      ) : (
        <video ref={setRef} src={asset.origin === "local-vod" ? api.edit.v2.videoProxyUrl(project.id, asset.id) : api.edit.v2.streamUrl(project.id, asset.id)} muted playsInline preload="auto" className={mediaStyle ? "absolute max-w-none" : "h-full w-full"} style={mediaStyle ?? { objectFit }} />
      )}
    </div>
  );
}

function CaptionLayer({ project, item, playhead }: { project: EditorProjectV2; item: TimelineItem; playhead: number }) {
  const caption = item.caption!;
  const vertical = caption.position === "top" ? "10%" : caption.position === "center" ? "50%" : "86%";
  const variant = caption.variant ?? "subtitle";
  const fade = caption.animation === "fade" ? Math.min(1, (playhead - item.timelineStart) / 0.35, (itemEnd(item) - playhead) / 0.35) : 1;
  return <div className={cn("pointer-events-none absolute z-[60] flex", variant === "lower_third" ? "inset-x-[6%] justify-start" : "inset-x-[5%] justify-center")} style={{ top: vertical, transform: "translateY(-50%)", opacity: Math.max(0, fade) }}>
    <span style={{
      color: caption.color,
      backgroundColor: hexWithAlpha(caption.backgroundColor, caption.backgroundOpacity),
      fontSize: `${caption.fontSize / project.canvas.height * 100}cqh`,
      fontWeight: caption.bold ? 800 : 500,
      WebkitTextStroke: `${caption.strokeWidth / project.canvas.height * 100}cqh ${caption.strokeColor}`,
      paintOrder: "stroke fill",
    }} className={cn("max-w-full whitespace-pre-wrap rounded px-[0.35em] py-[0.12em] leading-[1.08] shadow-lg", variant === "lower_third" ? "max-w-[68%] text-left" : "text-center", variant === "title" && "uppercase tracking-[0.04em]")}>{caption.text}</span>
  </div>;
}

function mixOpacity(project: EditorProjectV2, item: TimelineItem, playhead: number): number {
  for (const transition of project.transitions ?? []) {
    if (transition.kind !== "mix") continue;
    if (transition.toItemId === item.id) {
      return Math.max(0, Math.min(1, (playhead - item.timelineStart) / transition.duration));
    }
    if (transition.fromItemId === item.id) {
      const start = itemEnd(item) - transition.duration;
      if (playhead >= start) return Math.max(0, Math.min(1, (itemEnd(item) - playhead) / transition.duration));
    }
  }
  return 1;
}

function transitionOverlay(project: EditorProjectV2, playhead: number): { color: string; opacity: number } | null {
  for (const transition of project.transitions ?? []) {
    if (transition.kind === "mix") continue;
    const from = allItems(project).find((item) => item.id === transition.fromItemId);
    if (!from) continue;
    const cut = itemEnd(from);
    const half = transition.duration / 2;
    if (playhead < cut - half || playhead > cut + half) continue;
    return {
      color: transition.kind === "fade_white" ? "#ffffff" : "#000000",
      opacity: Math.max(0, 1 - Math.abs(playhead - cut) / Math.max(0.001, half)),
    };
  }
  return null;
}

function hexWithAlpha(color: string, opacity: number): string {
  const match = /^#([0-9a-f]{6})$/i.exec(color);
  if (!match) return color;
  const alpha = Math.round(Math.max(0, Math.min(1, opacity)) * 255).toString(16).padStart(2, "0");
  return `${color}${alpha}`;
}

function cropMediaStyle(sourceWidth: number | undefined, sourceHeight: number | undefined, transform: VideoTransform): React.CSSProperties | null {
  const crop = transform.crop;
  if (!crop || !sourceWidth || !sourceHeight) return null;
  const [cropX, cropY, cropWidth, cropHeight] = crop;
  if (cropWidth <= 0 || cropHeight <= 0) return null;
  const boxWidth = Math.max(1, transform.width);
  const boxHeight = Math.max(1, transform.height);
  const scaleX = boxWidth / cropWidth;
  const scaleY = boxHeight / cropHeight;
  const scale = transform.fit === "contain" ? Math.min(scaleX, scaleY) : transform.fit === "stretch" ? 0 : Math.max(scaleX, scaleY);
  const renderedWidth = transform.fit === "stretch" ? sourceWidth * scaleX : sourceWidth * scale;
  const renderedHeight = transform.fit === "stretch" ? sourceHeight * scaleY : sourceHeight * scale;
  const shownCropWidth = transform.fit === "stretch" ? cropWidth * scaleX : cropWidth * scale;
  const shownCropHeight = transform.fit === "stretch" ? cropHeight * scaleY : cropHeight * scale;
  const left = (boxWidth - shownCropWidth) / 2 - (transform.fit === "stretch" ? cropX * scaleX : cropX * scale);
  const top = (boxHeight - shownCropHeight) / 2 - (transform.fit === "stretch" ? cropY * scaleY : cropY * scale);
  return {
    width: `${renderedWidth / boxWidth * 100}%`,
    height: `${renderedHeight / boxHeight * 100}%`,
    left: `${left / boxWidth * 100}%`,
    top: `${top / boxHeight * 100}%`,
  };
}

function TransformBox({ project, item, onTransform }: { project: EditorProjectV2; item: TimelineItem; onTransform: (itemId: string, transform: Partial<VideoTransform>) => void }) {
  const original = item.video!;
  const [draft, setDraft] = useState(original);
  useEffect(() => setDraft(original), [original]);

  function begin(event: ReactPointerEvent, handle: "move" | "nw" | "ne" | "sw" | "se") {
    event.preventDefault();
    event.stopPropagation();
    const startX = event.clientX;
    const startY = event.clientY;
    const start = { ...draft };
    const canvas = event.currentTarget.closest<HTMLElement>("[data-preview-canvas]");
    const bounds = canvas?.getBoundingClientRect();
    if (!bounds) return;
    let latest = start;
    const move = (next: PointerEvent) => {
      const dx = (next.clientX - startX) * project.canvas.width / bounds.width;
      const dy = (next.clientY - startY) * project.canvas.height / bounds.height;
      if (handle === "move") {
        latest = { ...start, x: Math.max(-start.width + 20, Math.min(project.canvas.width - 20, start.x + dx)), y: Math.max(-start.height + 20, Math.min(project.canvas.height - 20, start.y + dy)) };
      } else {
        const left = handle.includes("w") ? start.x + dx : start.x;
        const top = handle.includes("n") ? start.y + dy : start.y;
        const right = handle.includes("e") ? start.x + start.width + dx : start.x + start.width;
        const bottom = handle.includes("s") ? start.y + start.height + dy : start.y + start.height;
        latest = { ...start, x: Math.min(left, right - 20), y: Math.min(top, bottom - 20), width: Math.max(20, right - left), height: Math.max(20, bottom - top) };
      }
      setDraft(latest);
    };
    const up = () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      onTransform(item.id, { x: latest.x, y: latest.y, width: latest.width, height: latest.height });
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up, { once: true });
  }

  return <div
    className="absolute z-50 cursor-move border border-amber-300 bg-amber-300/[0.04] shadow-[0_0_0_1px_rgba(0,0,0,.5)]"
    style={{ left: `${draft.x / project.canvas.width * 100}%`, top: `${draft.y / project.canvas.height * 100}%`, width: `${draft.width / project.canvas.width * 100}%`, height: `${draft.height / project.canvas.height * 100}%` }}
    onPointerDown={(event) => begin(event, "move")}
  >
    <span className="pointer-events-none absolute left-1 top-1 max-w-[80%] truncate rounded bg-black/70 px-1 text-[7px] font-bold uppercase tracking-wide text-amber-200">{project.assets[item.assetId]?.name}</span>
    {(["nw", "ne", "sw", "se"] as const).map((handle) => <button key={handle} type="button" aria-label={`Resize ${handle}`} onPointerDown={(event) => begin(event, handle)} className={cn("absolute h-2.5 w-2.5 rounded-full border border-black bg-amber-300", handle.includes("n") ? "-top-1.5" : "-bottom-1.5", handle.includes("w") ? "-left-1.5" : "-right-1.5")} />)}
  </div>;
}

function formatClock(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  const frames = Math.floor((seconds % 1) * 30);
  return `${minutes.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}:${frames.toString().padStart(2, "0")}`;
}
