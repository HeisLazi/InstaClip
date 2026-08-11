import {
  Copy,
  MousePointer2,
  Redo2,
  Scissors,
  Trash2,
  Undo2,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { useMemo, useRef, type PointerEvent as ReactPointerEvent } from "react";

import { cn } from "@/lib/utils";

export type EditorLayout = "reaction" | "crop" | "fullcam" | "passthrough";
export type TimelineMediaKind = "source" | "video" | "image";

export type TimelineSegment = {
  id: string;
  sourceStart: number;
  sourceEnd: number;
  layout: EditorLayout;
  mediaId?: string;
  mediaKind?: TimelineMediaKind;
  mediaName?: string;
  mediaDuration?: number;
  mediaWidth?: number;
  mediaHeight?: number;
  mediaUrl?: string;
  thumbnailUrl?: string;
  clipBucket?: "output" | "positives" | "negatives" | "edited";
  clipStem?: string;
};

export type TimelineFx = {
  id: string;
  name: string;
  at: number;
  gain: number;
};

type SegmentPosition = TimelineSegment & { sequenceStart: number; duration: number };

export function sequencePositions(segments: TimelineSegment[]): SegmentPosition[] {
  let cursor = 0;
  return segments.map((segment) => {
    const duration = Math.max(0, segment.sourceEnd - segment.sourceStart);
    const positioned = { ...segment, sequenceStart: cursor, duration };
    cursor += duration;
    return positioned;
  });
}

export function locatePlayhead(segments: TimelineSegment[], at: number) {
  const positions = sequencePositions(segments);
  if (!positions.length) return null;
  const duration = positions.reduce((total, segment) => total + segment.duration, 0);
  const safe = Math.min(Math.max(0, at), duration);
  const position = positions.find((segment, index) =>
    safe < segment.sequenceStart + segment.duration || index === positions.length - 1,
  ) ?? positions[positions.length - 1];
  const offset = Math.min(position.duration, Math.max(0, safe - position.sequenceStart));
  return {
    segment: position,
    sequenceTime: safe,
    sourceTime: position.sourceStart + offset,
  };
}

interface EditorTimelineProps {
  sourceDuration: number;
  segments: TimelineSegment[];
  selectedId: string;
  playhead: number;
  zoom: number;
  fx: TimelineFx[];
  peaks: number[];
  thumbnailUrl: string;
  canUndo: boolean;
  canRedo: boolean;
  onSelect: (id: string) => void;
  onSeek: (at: number) => void;
  onTrim: (id: string, start: number, end: number) => void;
  onSplit: () => void;
  onDelete: () => void;
  onDuplicate: () => void;
  onUndo: () => void;
  onRedo: () => void;
  onZoom: (value: number) => void;
  onFxMove: (id: string, at: number) => void;
}

export function EditorTimeline({
  sourceDuration,
  segments,
  selectedId,
  playhead,
  zoom,
  fx,
  peaks,
  thumbnailUrl,
  canUndo,
  canRedo,
  onSelect,
  onSeek,
  onTrim,
  onSplit,
  onDelete,
  onDuplicate,
  onUndo,
  onRedo,
  onZoom,
  onFxMove,
}: EditorTimelineProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const positions = useMemo(() => sequencePositions(segments), [segments]);
  const duration = positions.reduce((total, segment) => total + segment.duration, 0);
  const width = Math.max(720, duration * zoom);
  const tickStep = zoom >= 100 ? 0.5 : zoom >= 55 ? 1 : zoom >= 28 ? 2 : 5;
  const ticks = Array.from({ length: Math.ceil(duration / tickStep) + 1 }, (_, index) => index * tickStep);

  function timeAt(clientX: number) {
    const rect = scrollRef.current?.getBoundingClientRect();
    if (!rect) return 0;
    const x = clientX - rect.left + (scrollRef.current?.scrollLeft ?? 0);
    return Math.min(duration, Math.max(0, x / zoom));
  }

  function beginFxDrag(event: ReactPointerEvent, id: string) {
    event.preventDefault();
    event.stopPropagation();
    const update = (clientX: number) => onFxMove(id, timeAt(clientX));
    update(event.clientX);
    const move = (next: PointerEvent) => update(next.clientX);
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop, { once: true });
  }

  return (
    <section className="flex min-h-[280px] flex-1 flex-col border-t border-border/70 bg-[hsl(228_22%_5%)]">
      <div className="flex h-11 shrink-0 items-center gap-1 border-b border-border/60 bg-[hsl(224_18%_9%)] px-3">
        <ToolButton label="Selection tool" active icon={<MousePointer2 className="h-3.5 w-3.5" />} />
        <div className="mx-1 h-5 w-px bg-border" />
        <ToolButton label="Split at playhead (S)" onClick={onSplit} icon={<Scissors className="h-3.5 w-3.5" />} />
        <ToolButton label="Delete segment (Delete)" onClick={onDelete} disabled={segments.length <= 1} icon={<Trash2 className="h-3.5 w-3.5" />} />
        <ToolButton label="Duplicate segment" onClick={onDuplicate} icon={<Copy className="h-3.5 w-3.5" />} />
        <div className="mx-1 h-5 w-px bg-border" />
        <ToolButton label="Undo (Ctrl+Z)" onClick={onUndo} disabled={!canUndo} icon={<Undo2 className="h-3.5 w-3.5" />} />
        <ToolButton label="Redo (Ctrl+Shift+Z)" onClick={onRedo} disabled={!canRedo} icon={<Redo2 className="h-3.5 w-3.5" />} />

        <div className="ml-auto flex items-center gap-2 text-[10px] text-muted-foreground">
          <span>Sequence {formatTime(duration)}</span>
          <ZoomOut className="h-3.5 w-3.5" />
          <input
            type="range"
            min={12}
            max={140}
            step={2}
            value={zoom}
            onChange={(event) => onZoom(Number(event.target.value))}
            className="w-28 accent-cyan-400"
            aria-label="Timeline zoom"
          />
          <ZoomIn className="h-3.5 w-3.5" />
          <span className="w-10 tabular-nums">{Math.round(zoom)} px/s</span>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[88px_minmax(0,1fr)]">
        <div className="border-r border-border/60 bg-[hsl(224_18%_8%)] pt-7 text-[10px] text-muted-foreground">
          <TrackHeader label="V1" detail="Video" className="h-[78px]" />
          <TrackHeader label="A1" detail="Audio" className="h-[58px]" />
          <TrackHeader label="S1" detail="Layered FX" className="h-[58px]" />
        </div>

        <div ref={scrollRef} className="min-w-0 overflow-x-auto overflow-y-hidden" onPointerDown={(event) => onSeek(timeAt(event.clientX))}>
          <div className="relative h-full min-h-[226px]" style={{ width }}>
            <div className="absolute inset-x-0 top-0 h-7 border-b border-border/50 bg-white/[0.02]">
              {ticks.map((tick) => (
                <div key={tick} className="absolute inset-y-0 border-l border-white/15" style={{ left: tick * zoom }}>
                  <span className="absolute left-1 top-1 text-[9px] tabular-nums text-muted-foreground">{formatTime(tick)}</span>
                </div>
              ))}
            </div>

            <div className="absolute inset-x-0 top-7 h-[78px] border-b border-border/45 bg-cyan-400/[0.025]">
              {positions.map((segment, index) => (
                <TimelineClip
                  key={segment.id}
                  segment={segment}
                  index={index}
                  zoom={zoom}
                  selected={segment.id === selectedId}
                  thumbnailUrl={segment.thumbnailUrl ?? thumbnailUrl}
                  sourceDuration={segment.mediaDuration ?? sourceDuration}
                  onSelect={onSelect}
                  onTrim={onTrim}
                />
              ))}
            </div>

            <div className="absolute inset-x-0 top-[105px] h-[58px] border-b border-border/45 bg-sky-400/[0.025]">
              {positions.map((segment) => (
                <WaveformClip
                  key={segment.id}
                  segment={segment}
                  zoom={zoom}
                  selected={segment.id === selectedId}
                  peaks={(segment.mediaKind ?? "source") === "source" ? peaks : []}
                  sourceDuration={segment.mediaDuration ?? sourceDuration}
                />
              ))}
            </div>

            <div className="absolute inset-x-0 top-[163px] h-[58px] border-b border-border/45 bg-amber-400/[0.02]">
              {fx.map((item, index) => (
                <button
                  key={item.id}
                  type="button"
                  onPointerDown={(event) => beginFxDrag(event, item.id)}
                  className="absolute h-6 min-w-16 -translate-x-1/2 cursor-ew-resize touch-none rounded border border-amber-300/55 bg-amber-400/85 px-2 text-[9px] font-semibold text-black shadow-lg"
                  style={{ left: item.at * zoom, top: 4 + (index % 2) * 26 }}
                  title={`${item.name} at ${formatTime(item.at)}`}
                >
                  {item.name}
                </button>
              ))}
            </div>

            <div
              className="pointer-events-none absolute bottom-0 top-0 z-40 w-px bg-white shadow-[0_0_10px_rgba(255,255,255,0.65)]"
              style={{ left: playhead * zoom }}
            >
              <span className="absolute -left-1 top-0 h-2 w-2 rotate-45 bg-white" />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function TimelineClip({
  segment,
  index,
  zoom,
  selected,
  thumbnailUrl,
  sourceDuration,
  onSelect,
  onTrim,
}: {
  segment: SegmentPosition;
  index: number;
  zoom: number;
  selected: boolean;
  thumbnailUrl: string;
  sourceDuration: number;
  onSelect: (id: string) => void;
  onTrim: (id: string, start: number, end: number) => void;
}) {
  function beginTrim(event: ReactPointerEvent, side: "left" | "right") {
    event.preventDefault();
    event.stopPropagation();
    onSelect(segment.id);
    const startX = event.clientX;
    const originalStart = segment.sourceStart;
    const originalEnd = segment.sourceEnd;
    const move = (next: PointerEvent) => {
      const delta = (next.clientX - startX) / zoom;
      if (side === "left") {
        onTrim(segment.id, Math.min(originalEnd - 0.1, Math.max(0, originalStart + delta)), originalEnd);
      } else {
        onTrim(segment.id, originalStart, Math.max(originalStart + 0.1, Math.min(sourceDuration, originalEnd + delta)));
      }
    };
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop, { once: true });
  }

  return (
    <div
      className={cn(
        "absolute inset-y-1 overflow-hidden rounded-sm border text-left shadow",
        selected ? "z-20 border-cyan-200 ring-2 ring-cyan-300/55" : "border-sky-400/55 hover:border-sky-200",
      )}
      style={{ left: segment.sequenceStart * zoom, width: Math.max(8, segment.duration * zoom) }}
    >
      <button
        type="button"
        onPointerDown={(event) => {
          event.stopPropagation();
          onSelect(segment.id);
        }}
        className="absolute inset-0 text-left"
        aria-label={`Select segment ${index + 1}`}
      >
        <span
          className="absolute inset-0 opacity-65"
          style={{
            backgroundImage: `linear-gradient(90deg,rgba(2,6,23,.2),rgba(14,165,233,.2)),url(${thumbnailUrl})`,
            backgroundSize: "110px 100%",
            backgroundRepeat: "repeat-x",
            backgroundPosition: "center",
          }}
        />
        <span className="absolute inset-x-0 bottom-0 flex h-5 items-center justify-between bg-sky-950/85 px-2 text-[9px] text-sky-100">
          <span className="truncate">{index + 1}. {segment.mediaName ?? segment.layout}</span>
          <span className="tabular-nums">{formatTime(segment.duration)}</span>
        </span>
      </button>
      <button type="button" className="absolute left-0 top-0 h-full w-2 cursor-ew-resize touch-none bg-cyan-200/0 hover:bg-cyan-200/70" onPointerDown={(event) => beginTrim(event, "left")} aria-label={`Trim segment ${index + 1} in point`} />
      <button type="button" className="absolute right-0 top-0 h-full w-2 cursor-ew-resize touch-none bg-cyan-200/0 hover:bg-cyan-200/70" onPointerDown={(event) => beginTrim(event, "right")} aria-label={`Trim segment ${index + 1} out point`} />
    </div>
  );
}

function WaveformClip({
  segment,
  zoom,
  selected,
  peaks,
  sourceDuration,
}: {
  segment: SegmentPosition;
  zoom: number;
  selected: boolean;
  peaks: number[];
  sourceDuration: number;
}) {
  const bars = 120;
  const sampled = Array.from({ length: bars }, (_, index) => {
    if (!peaks.length || sourceDuration <= 0) return 0.18 + ((index * 17) % 9) / 18;
    const sourceTime = segment.sourceStart + (segment.duration * index) / Math.max(1, bars - 1);
    const peakIndex = Math.min(peaks.length - 1, Math.floor((sourceTime / sourceDuration) * peaks.length));
    return peaks[peakIndex] ?? 0;
  });

  return (
    <div
      className={cn("absolute inset-y-1 overflow-hidden rounded-sm border", selected ? "border-cyan-200/70 bg-cyan-500/15" : "border-sky-500/35 bg-sky-500/10")}
      style={{ left: segment.sequenceStart * zoom, width: Math.max(8, segment.duration * zoom) }}
    >
      <svg viewBox={`0 0 ${bars} 40`} preserveAspectRatio="none" className="h-full w-full">
        {sampled.map((peak, index) => {
          const height = Math.max(2, peak * 36);
          return <line key={index} x1={index} x2={index} y1={20 - height / 2} y2={20 + height / 2} stroke="rgb(56 189 248)" strokeOpacity="0.72" strokeWidth="0.7" />;
        })}
      </svg>
    </div>
  );
}

function ToolButton({
  label,
  icon,
  active = false,
  disabled = false,
  onClick,
}: {
  label: string;
  icon: React.ReactNode;
  active?: boolean;
  disabled?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "grid h-7 w-7 place-items-center rounded text-muted-foreground transition hover:bg-accent hover:text-foreground disabled:opacity-30",
        active && "bg-primary/15 text-primary",
      )}
      title={label}
      aria-label={label}
    >
      {icon}
    </button>
  );
}

function TrackHeader({ label, detail, className }: { label: string; detail: string; className?: string }) {
  return (
    <div className={cn("flex items-center gap-2 border-b border-border/45 px-3", className)}>
      <span className="font-semibold text-primary">{label}</span>
      <span>{detail}</span>
    </div>
  );
}

function formatTime(value: number) {
  const safe = Number.isFinite(value) ? Math.max(0, value) : 0;
  const minutes = Math.floor(safe / 60);
  const seconds = safe - minutes * 60;
  return `${minutes}:${seconds.toFixed(1).padStart(4, "0")}`;
}
