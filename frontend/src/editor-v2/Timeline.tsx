import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { Captions, Eye, EyeOff, Lock, Plus, Scissors, Unlock, Volume2, VolumeX } from "lucide-react";

import { api } from "@/api/client";
import { readAssetDrag } from "@/editor-v2/dnd";
import { Waveform } from "@/editor-v2/Waveform";
import {
  itemDuration,
  itemEnd,
  projectDuration,
  type Command,
  type EditorProjectV2,
  type EditorTrack,
  type TimelineItem,
  type TrackKind,
} from "@/editor-v2/model";
import type { AssetSource } from "@/editor-v2/useEditorProject";
import { cn } from "@/lib/utils";

const TRACK_HEADER = 112;
const ROW_HEIGHT = 58;

type DragState = {
  itemId: string;
  startX: number;
  deltaTime: number;
  targetTrackId: string;
};

export function Timeline({
  project,
  playhead,
  onPlayhead,
  dispatch,
  onDropSource,
  onDropFiles,
  onAddTrack,
  onAddCaption,
  layoutMarkers = [],
  followPlayhead = false,
}: {
  project: EditorProjectV2;
  playhead: number;
  onPlayhead: (time: number) => void;
  dispatch: (command: Command) => void;
  onDropSource: (source: AssetSource, trackId: string, time: number) => Promise<void>;
  onDropFiles: (files: FileList, trackId: string, time: number) => Promise<void>;
  onAddTrack: (kind: TrackKind) => void;
  onAddCaption: () => void;
  layoutMarkers?: Array<{ time: number; label: string }>;
  followPlayhead?: boolean;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<DragState | null>(null);
  const [viewW, setViewW] = useState(900);
  const pps = project.view.pixelsPerSecond;
  // Keep a full screen of empty timeline after the last clip so you can always
  // scroll past the end and drop new clips there.
  const visibleTimelineSeconds = Math.max(5, (viewW - TRACK_HEADER) / pps);
  const projectEnd = projectDuration(project);
  const trailingPad = Math.max(10, visibleTimelineSeconds);
  const duration = Math.max(projectEnd, playhead, 10) + trailingPad;
  const timelineWidth = duration * pps;

  // Track the visible width of the scroller (drives the trailing pad + follow).
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setViewW(el.clientWidth));
    ro.observe(el);
    setViewW(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  // Auto-scroll so the playhead stays visible (follows during playback/seek).
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const x = TRACK_HEADER + playhead * pps;
    const left = el.scrollLeft;
    const right = left + el.clientWidth;
    const timelineViewport = Math.max(1, el.clientWidth - TRACK_HEADER);
    if (followPlayhead) {
      const target = Math.max(0, x - TRACK_HEADER - timelineViewport * 0.38);
      if (Math.abs(el.scrollLeft - target) > 1) el.scrollLeft = target;
    } else if (x < left + TRACK_HEADER + 24) {
      el.scrollLeft = Math.max(0, x - TRACK_HEADER - 48);
    } else if (x > right - 48) {
      el.scrollLeft = x - el.clientWidth + 96;
    }
  }, [followPlayhead, playhead, pps]);
  const selected = new Set(project.selection.itemIds);
  const tracks = useMemo(() => {
    const captions = project.tracks.filter((track) => track.kind === "caption").sort((a, b) => a.order - b.order);
    const video = project.tracks.filter((track) => track.kind === "video").sort((a, b) => b.order - a.order);
    const audio = project.tracks.filter((track) => track.kind === "audio").sort((a, b) => a.order - b.order);
    return [...captions, ...video, ...audio];
  }, [project.tracks]);

  function seekFromPointer(event: ReactPointerEvent<HTMLElement>) {
    const bounds = event.currentTarget.getBoundingClientRect();
    onPlayhead(Math.max(0, (event.clientX - bounds.left) / pps));
  }

  function beginMove(event: ReactPointerEvent, item: TimelineItem) {
    if ((event.target as HTMLElement).dataset.trim) return;
    const track = project.tracks.find((candidate) => candidate.id === item.trackId);
    if (track?.locked) return;
    event.stopPropagation();
    dispatch({ type: "SET_SELECTION", itemIds: event.shiftKey ? [...new Set([...project.selection.itemIds, item.id])] : [item.id], focusedTrackId: item.trackId });
    const initial: DragState = { itemId: item.id, startX: event.clientX, deltaTime: 0, targetTrackId: item.trackId };
    setDrag(initial);
    const move = (next: PointerEvent) => {
      const target = document.elementFromPoint(next.clientX, next.clientY)?.closest<HTMLElement>("[data-track-id]");
      const candidateTrack = target?.dataset.trackId ?? item.trackId;
      const sourceTrack = project.tracks.find((candidate) => candidate.id === item.trackId);
      const destination = project.tracks.find((candidate) => candidate.id === candidateTrack);
      const compatible = sourceTrack && destination && sourceTrack.kind === destination.kind && !destination.locked;
      setDrag({ ...initial, deltaTime: (next.clientX - initial.startX) / pps, targetTrackId: compatible ? candidateTrack : item.trackId });
    };
    const up = (next: PointerEvent) => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      const target = document.elementFromPoint(next.clientX, next.clientY)?.closest<HTMLElement>("[data-track-id]");
      const candidateTrack = target?.dataset.trackId ?? item.trackId;
      const sourceTrack = project.tracks.find((candidate) => candidate.id === item.trackId);
      const destination = project.tracks.find((candidate) => candidate.id === candidateTrack);
      const targetTrackId = sourceTrack && destination && sourceTrack.kind === destination.kind && !destination.locked ? candidateTrack : item.trackId;
      const deltaTime = (next.clientX - initial.startX) / pps;
      if (Math.abs(deltaTime) > 0.002 || targetTrackId !== item.trackId) {
        dispatch({ type: "MOVE_ITEMS", itemIds: project.selection.itemIds.includes(item.id) ? project.selection.itemIds : [item.id], deltaTime, targetTrackId });
      }
      setDrag(null);
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up, { once: true });
  }

  function beginTrim(event: ReactPointerEvent, item: TimelineItem, edge: "start" | "end") {
    event.stopPropagation();
    const startX = event.clientX;
    const move = (next: PointerEvent) => {
      setDrag({ itemId: item.id, startX, deltaTime: (next.clientX - startX) / pps, targetTrackId: item.trackId });
    };
    const up = (next: PointerEvent) => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      const timelineDelta = (next.clientX - startX) / pps;
      if (Math.abs(timelineDelta) > 0.002) {
        dispatch({ type: "TRIM_ITEM", itemId: item.id, edge, delta: timelineDelta * item.speed });
      }
      setDrag(null);
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up, { once: true });
  }

  const ticks = Array.from({ length: Math.ceil(duration) + 1 }, (_, index) => index);

  return (
    <section className="flex min-h-0 min-w-0 w-full flex-1 flex-col overflow-hidden border-t border-white/10 bg-[#0c1014]">
      <div className="flex h-9 shrink-0 items-center gap-1 border-b border-white/10 px-2">
        <button type="button" onClick={() => dispatch({ type: "SPLIT_ITEMS", itemIds: project.selection.itemIds, time: playhead })} disabled={project.selection.itemIds.length === 0} className="editor-v2-tool" title="Split selected clips at playhead (S)"><Scissors className="h-3.5 w-3.5" /></button>
        <span className="ml-2 text-[9px] uppercase tracking-[0.18em] text-slate-600">Timeline</span>
        <div className="flex-1" />
        <button type="button" onClick={() => onAddTrack("video")} className="editor-v2-tool gap-1 px-2 text-[9px]"><Plus className="h-3 w-3" /> Video</button>
        <button type="button" onClick={() => onAddTrack("audio")} className="editor-v2-tool gap-1 px-2 text-[9px]"><Plus className="h-3 w-3" /> Audio</button>
        <button type="button" onClick={onAddCaption} className="editor-v2-tool gap-1 px-2 text-[9px]"><Captions className="h-3 w-3" /> Caption</button>
        <input aria-label="Timeline zoom" type="range" min={12} max={240} value={pps} onChange={(event) => dispatch({ type: "SET_VIEW", view: { pixelsPerSecond: Number(event.target.value) } })} className="ml-2 w-24 accent-cyan-400" />
        <span className="w-12 text-right text-[9px] tabular-nums text-slate-500">{Math.round(pps)} px/s</span>
      </div>

      <div ref={scrollRef} data-testid="editor-timeline-scroll" className="relative min-h-0 min-w-0 w-full max-w-full flex-1 overflow-x-scroll overflow-y-auto overscroll-x-contain [scrollbar-gutter:stable]">
        <div style={{ width: TRACK_HEADER + timelineWidth, minHeight: 28 + tracks.length * ROW_HEIGHT }} className="relative">
          <div className="sticky top-0 z-30 flex h-7 border-b border-white/10 bg-[#11161c]">
            <div style={{ width: TRACK_HEADER }} className="sticky left-0 z-40 shrink-0 border-r border-white/10 bg-[#11161c] px-2 py-1 text-[9px] text-slate-600">TRACKS</div>
            <div data-testid="editor-timeline-ruler" style={{ width: timelineWidth }} onPointerDown={seekFromPointer} className="relative cursor-crosshair bg-[linear-gradient(90deg,rgba(255,255,255,.025)_1px,transparent_1px)]">
              {ticks.map((tick) => <div key={tick} className="absolute inset-y-0 border-l border-white/15" style={{ left: tick * pps }}><span className="ml-1 text-[8px] tabular-nums text-slate-500">{formatTime(tick)}</span></div>)}
              {layoutMarkers.map((marker) => <div key={`${marker.time}-${marker.label}`} className="absolute inset-y-0 z-10 border-l border-dashed border-violet-300/80" style={{ left: marker.time * pps }} title={`Layout switch: ${marker.label}`}><span className="absolute left-1 top-3 whitespace-nowrap rounded bg-violet-300/15 px-1 text-[7px] font-semibold uppercase text-violet-200">{marker.label}</span></div>)}
            </div>
          </div>

          {tracks.map((track) => (
            <div key={track.id} data-track-id={track.id} className="flex border-b border-white/[0.07]" style={{ height: ROW_HEIGHT }}>
              <TrackHeader track={track} dispatch={dispatch} />
              <div
                style={{ width: timelineWidth, backgroundSize: `${pps}px 100%` }}
                className={cn("relative bg-[linear-gradient(90deg,rgba(255,255,255,.025)_1px,transparent_1px)]", track.locked && "opacity-60")}
                onPointerDown={seekFromPointer}
                onDragOver={(event) => {
                  event.preventDefault();
                  event.dataTransfer.dropEffect = "copy";
                }}
                onDrop={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  const bounds = event.currentTarget.getBoundingClientRect();
                  const at = Math.max(0, (event.clientX - bounds.left) / pps);
                  if (event.dataTransfer.files.length > 0) {
                    void onDropFiles(event.dataTransfer.files, track.id, at);
                    return;
                  }
                  const source = readAssetDrag(event);
                  if (!source) return;
                  void onDropSource(source, track.id, at);
                }}
              >
                {track.items.map((item) => {
                  const moving = drag?.itemId === item.id;
                  const delta = moving ? drag.deltaTime : 0;
                  return (
                    <TimelineClip
                      key={item.id}
                      project={project}
                      track={track}
                      item={item}
                      selected={selected.has(item.id)}
                      pps={pps}
                      delta={delta}
                      onMove={beginMove}
                      onTrim={beginTrim}
                    />
                  );
                })}
              </div>
            </div>
          ))}

          {project.inPoint !== null && project.outPoint !== null && <div className="pointer-events-none absolute bottom-0 top-7 z-10 bg-cyan-400/[0.055] ring-1 ring-inset ring-cyan-400/20" style={{ left: TRACK_HEADER + project.inPoint * pps, width: Math.max(1, (project.outPoint - project.inPoint) * pps) }} />}
          {layoutMarkers.map((marker) => <div key={`line-${marker.time}-${marker.label}`} className="pointer-events-none absolute bottom-0 top-7 z-20 border-l border-dashed border-violet-300/45" style={{ left: TRACK_HEADER + marker.time * pps }} />)}
          <div data-testid="editor-project-end" className="pointer-events-none absolute bottom-0 top-7 z-20 border-l border-dashed border-amber-300/35" style={{ left: TRACK_HEADER + projectEnd * pps }}><span className="absolute left-1 top-1 whitespace-nowrap text-[8px] font-semibold uppercase tracking-wide text-amber-300/60">End · drop after here</span></div>
          <div className="pointer-events-none absolute bottom-0 top-0 z-40 w-px bg-rose-400 shadow-[0_0_8px_rgba(251,113,133,.8)]" style={{ left: TRACK_HEADER + playhead * pps }}><div className="-ml-1.5 h-2.5 w-3 bg-rose-400 [clip-path:polygon(0_0,100%_0,50%_100%)]" /></div>
        </div>
      </div>
    </section>
  );
}

function TrackHeader({ track, dispatch }: { track: EditorTrack; dispatch: (command: Command) => void }) {
  return (
    <div style={{ width: TRACK_HEADER }} className="sticky left-0 z-20 flex shrink-0 items-center gap-1 border-r border-white/10 bg-[#11161c] px-2">
      <span className={cn("w-7 text-[10px] font-black", track.kind === "audio" ? "text-emerald-400" : track.kind === "caption" ? "text-amber-300" : "text-cyan-400")}>{track.name}</span>
      {track.kind !== "caption" && <button type="button" onClick={() => dispatch({ type: "SET_TRACK_MUTE", trackId: track.id, muted: !track.muted })} className={cn("editor-v2-track-button", track.muted && "text-rose-400")} title={track.muted ? "Unmute" : "Mute"}>{track.muted ? <VolumeX /> : <Volume2 />}</button>}
      {track.kind !== "audio" && <button type="button" onClick={() => dispatch({ type: "SET_TRACK_VISIBILITY", trackId: track.id, hidden: !track.hidden })} className={cn("editor-v2-track-button", track.hidden && "text-rose-400")} title={track.hidden ? "Show" : "Hide"}>{track.hidden ? <EyeOff /> : <Eye />}</button>}
      {track.kind === "audio" && <button type="button" onClick={() => dispatch({ type: "SET_TRACK_SOLO", trackId: track.id, solo: !track.solo })} className={cn("editor-v2-track-button text-[8px] font-bold", track.solo && "bg-amber-400/15 text-amber-300")} title="Solo">S</button>}
      <button type="button" onClick={() => dispatch({ type: "SET_TRACK_LOCK", trackId: track.id, locked: !track.locked })} className={cn("editor-v2-track-button", track.locked && "text-amber-300")} title={track.locked ? "Unlock" : "Lock"}>{track.locked ? <Lock /> : <Unlock />}</button>
    </div>
  );
}

function TimelineClip({ project, track, item, selected, pps, delta, onMove, onTrim }: {
  project: EditorProjectV2;
  track: EditorTrack;
  item: TimelineItem;
  selected: boolean;
  pps: number;
  delta: number;
  onMove: (event: ReactPointerEvent, item: TimelineItem) => void;
  onTrim: (event: ReactPointerEvent, item: TimelineItem, edge: "start" | "end") => void;
}) {
  const asset = project.assets[item.assetId];
  const start = Math.max(0, item.timelineStart + delta);
  const width = Math.max(12, itemDuration(item) * pps);
  return (
    <div
      onPointerDown={(event) => onMove(event, item)}
      className={cn(
        "absolute top-1.5 h-[46px] cursor-grab overflow-hidden rounded border shadow-sm active:cursor-grabbing",
        track.kind === "audio" ? "border-emerald-400/40 bg-emerald-500/20 text-emerald-200" : track.kind === "caption" ? "border-amber-300/45 bg-amber-400/15 text-amber-100" : "border-cyan-400/40 bg-cyan-500/20 text-cyan-100",
        selected && "z-10 border-amber-300 ring-1 ring-amber-300/70",
        !item.enabled && "opacity-40",
      )}
      style={{ left: start * pps, width }}
      title={`${item.caption?.text ?? asset?.name ?? item.assetId}\n${item.timelineStart.toFixed(2)}-${itemEnd(item).toFixed(2)}s · ${item.speed}x`}
    >
      {track.kind === "audio" && <Waveform projectId={project.id} assetId={item.assetId} />}
      {track.kind === "video" && item.video && asset && <ClipFilmstrip projectId={project.id} assetId={asset.id} assetKind={asset.kind} thumbnailUrl={asset.thumbnailUrl} sourceIn={item.sourceIn} sourceOut={item.sourceOut} width={width} />}
      <div data-trim="start" onPointerDown={(event) => onTrim(event, item, "start")} className="absolute inset-y-0 left-0 z-20 w-1.5 cursor-ew-resize bg-current/30 hover:bg-amber-300" />
      <div className="relative z-10 flex h-full items-start justify-between gap-1 px-2 py-1 text-[9px]">
        <span className="truncate font-semibold">{{ flashback: "FLASHBACK · ", prelude: "COLD OPEN · ", youtube_intro: "INTRO · ", rough_cut: "STORY CUT · ", youtube_outro: "OUTRO · ", post_credit: "POST-CREDIT · ", b_roll: "B-ROLL · ", meme_insert: "MEME · ", title_card: "TITLE · ", speech_caption: "" }[item.editorRole ?? "speech_caption"]}{item.caption?.text ?? asset?.name ?? "Missing asset"}</span>
        {track.kind !== "caption" && <span className="shrink-0 rounded bg-black/35 px-1 text-[8px]">{item.speed}x</span>}
      </div>
      <div data-trim="end" onPointerDown={(event) => onTrim(event, item, "end")} className="absolute inset-y-0 right-0 z-20 w-1.5 cursor-ew-resize bg-current/30 hover:bg-amber-300" />
    </div>
  );
}

function ClipFilmstrip({ projectId, assetId, assetKind, thumbnailUrl, sourceIn, sourceOut, width }: { projectId: string; assetId: string; assetKind: string; thumbnailUrl?: string; sourceIn: number; sourceOut: number; width: number }) {
  if (width < 34 || assetKind === "audio" || assetKind === "caption") return null;
  const count = Math.max(1, Math.min(10, Math.ceil(width / 88)));
  const span = Math.max(0.01, sourceOut - sourceIn);
  return <div className="pointer-events-none absolute inset-0 z-0 flex overflow-hidden bg-black/30" aria-hidden="true">{Array.from({ length: count }, (_, index) => {
    const at = sourceIn + span * ((index + 0.5) / count);
    const src = assetKind === "image" && thumbnailUrl
      ? thumbnailUrl
      : api.edit.v2.frameThumbnailUrl(projectId, assetId, at, 180);
    return <img key={`${index}-${at.toFixed(2)}`} src={src} alt="" loading="lazy" draggable={false} className="h-full min-w-0 flex-1 object-cover opacity-70 saturate-75" />;
  })}<div className="absolute inset-0 bg-gradient-to-b from-black/5 via-transparent to-black/60" /></div>;
}

function formatTime(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds - minutes * 60;
  return `${minutes}:${remainder.toString().padStart(2, "0")}`;
}
