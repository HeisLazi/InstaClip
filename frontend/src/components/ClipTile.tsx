/**
 * Gallery tile with:
 *   - silent hover-play preview (debounced)
 *   - gradient metadata overlay
 *   - Good/Bad/Open action buttons that fade in on hover
 *   - brief ✓ / ✗ confirmation flash before the tile disappears
 */

import { useEffect, useRef, useState } from "react";
import { ExternalLink, Tags, ThumbsDown, ThumbsUp } from "lucide-react";

import { api, type Bucket } from "@/api/client";
import { ConfidenceRing } from "@/components/ConfidenceRing";
import { cn, formatDuration } from "@/lib/utils";

export type LabelAction = "good" | "bad";

interface ClipTileProps {
  bucket:    Bucket;
  stem:      string;
  name:      string;
  sizeMb:    number;
  score:     number | null;
  durationSeconds?: number | null;
  group?: string;
  tags?: string[];
  hovered:   boolean;
  onHover:   (hovered: boolean) => void;
  onOpen:    () => void;
  onLabel:   (action: LabelAction) => Promise<void>;
  onEditTags?: () => void;
}

export function ClipTile({
  bucket, stem, name, sizeMb, score, durationSeconds, group, tags = [],
  hovered, onHover, onOpen, onLabel, onEditTags,
}: ClipTileProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [showVideo, setShowVideo] = useState(false);
  const [duration, setDuration]   = useState<number | null>(durationSeconds ?? null);
  const [flash, setFlash]         = useState<LabelAction | null>(null);
  const [leaving, setLeaving]     = useState(false);

  useEffect(() => {
    if (durationSeconds != null) setDuration(durationSeconds);
  }, [durationSeconds]);

  // Debounce the actual <video> mount so flicking through the grid doesn't
  // spam range requests at the backend.
  useEffect(() => {
    if (hovered) {
      const t = window.setTimeout(() => setShowVideo(true), 200);
      return () => window.clearTimeout(t);
    }
    setShowVideo(false);
    setDuration((d) => d); // keep last known duration
  }, [hovered]);

  // Try to play with sound off when the <video> mounts.
  useEffect(() => {
    if (!showVideo) return;
    const v = videoRef.current;
    if (!v) return;
    v.muted = true;
    v.play().catch(() => {});
  }, [showVideo]);

  async function applyLabel(action: LabelAction) {
    if (flash || leaving) return;
    setFlash(action);
    try {
      await onLabel(action);
      setLeaving(true);
    } catch (e) {
      setFlash(null);
    }
  }

  // Reveal more of the filename on hover, otherwise truncate to one line.
  return (
    <div
      onMouseEnter={() => onHover(true)}
      onMouseLeave={() => onHover(false)}
      className={cn(
        "group premium-card rounded-lg overflow-hidden surface-1 border border-border/50 transition-all duration-200",
        hovered && "border-primary/45 shadow-[0_22px_70px_hsl(var(--primary)_/_0.12)] -translate-y-0.5",
        leaving && "opacity-0 scale-95 pointer-events-none",
      )}
    >
      <div className="relative aspect-video bg-secondary/40 overflow-hidden">
        {/* Static thumbnail — always present so the hover->video swap is seamless */}
        <button
          onClick={onOpen}
          className="absolute inset-0 w-full h-full text-left"
          title="Click to preview"
        >
          <img
            src={api.clips.thumbUrl(bucket, stem)}
            alt={stem}
            loading="lazy"
            className={cn(
              "w-full h-full object-cover transition-transform duration-300",
              hovered && "scale-[1.045]",
            )}
          />
        </button>

        {/* Hover-play video on top */}
        {showVideo && (
          <video
            ref={videoRef}
            src={api.clips.videoUrl(bucket, stem)}
            muted
            loop
            playsInline
            preload="metadata"
            onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
            className="absolute inset-0 w-full h-full object-cover pointer-events-none"
          />
        )}

        {/* Bottom gradient with metadata — only on hover */}
        <div className={cn(
          "absolute inset-x-0 bottom-0 px-3 py-2 pointer-events-none",
          "bg-gradient-to-t from-black/90 via-black/45 to-transparent",
          "opacity-0 group-hover:opacity-100 transition-opacity duration-200",
        )}>
          <div className="flex items-end justify-between gap-2 text-[11px] text-white/90 tabular-nums">
            <span className="font-medium">{formatDuration(duration)}</span>
          </div>
        </div>

        {/* Confidence ring — always visible top-right for generator score */}
        {score != null && (
          <div className="absolute top-1.5 right-1.5 pointer-events-none">
            <div className="rounded-full bg-black/45 p-0.5 backdrop-blur-md border border-white/10 shadow-lg">
              <ConfidenceRing value={score} size={38} stroke={4} />
            </div>
          </div>
        )}

        {group && (
          <div className="absolute left-1.5 top-1.5 max-w-[68%] truncate rounded bg-black/65 px-2 py-1 text-[9px] font-medium text-white/80 backdrop-blur-md">
            {group.replaceAll("_", " ")}
          </div>
        )}

        {duration != null && duration < 4 && (
          <div className="absolute bottom-1.5 left-1.5 rounded border border-amber-300/40 bg-amber-400/90 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-black">
            micro {duration.toFixed(1)}s
          </div>
        )}

        {/* Confirmation flash */}
        {flash && (
          <div className={cn(
            "absolute inset-0 grid place-items-center pointer-events-none",
            "transition-opacity duration-200",
            flash === "good" ? "bg-success/35" : "bg-destructive/35",
          )}>
            <div className={cn(
              "rounded-full p-4 shadow-2xl",
              flash === "good" ? "bg-success text-success-foreground" : "bg-destructive text-destructive-foreground",
            )}>
              {flash === "good"
                ? <ThumbsUp   className="h-8 w-8" />
                : <ThumbsDown className="h-8 w-8" />}
            </div>
          </div>
        )}
      </div>

      {/* Bottom bar */}
      <div className="p-3 flex flex-col gap-2">
        <button onClick={onOpen} className="text-left min-w-0">
          <div className="text-xs font-medium truncate" title={name}>{name}</div>
          <div className="mt-0.5 flex items-center gap-2 text-[11px] text-muted-foreground">
            <span>{sizeMb.toFixed(1)} MB</span>
            {duration != null && <span>{formatDuration(duration)}</span>}
          </div>
        </button>

        {tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {tags.slice(0, 3).map((tag) => <span key={tag} className="max-w-full truncate rounded bg-primary/10 px-1.5 py-0.5 text-[9px] text-primary">{tag}</span>)}
            {tags.length > 3 && <span className="rounded bg-muted/40 px-1.5 py-0.5 text-[9px] text-muted-foreground">+{tags.length - 3}</span>}
          </div>
        )}

        {/* Quick-label buttons fade in on hover */}
        <div className={cn(
          "flex items-center gap-2 transition-opacity duration-200",
          hovered ? "opacity-100" : "opacity-0 group-focus-within:opacity-100",
        )}>
          {bucket !== "positives" && (
            <button
              onClick={() => applyLabel("good")}
              className="premium-control flex items-center gap-1 px-2 py-1 rounded text-[11px] text-success hover:bg-success/15"
              title="Mark as Good (→)"
            >
              <ThumbsUp className="h-3 w-3" /> Good
            </button>
          )}
          {bucket !== "negatives" && (
            <button
              onClick={() => applyLabel("bad")}
              className="premium-control flex items-center gap-1 px-2 py-1 rounded text-[11px] text-destructive hover:bg-destructive/15"
              title="Mark as Bad (←)"
            >
              <ThumbsDown className="h-3 w-3" /> Bad
            </button>
          )}
          <div className="flex-1" />
          {onEditTags && (
            <button
              type="button"
              onClick={onEditTags}
              className="premium-control flex items-center gap-1 rounded px-2 py-1 text-[11px] text-muted-foreground hover:text-primary"
              title="Organize with tags"
            >
              <Tags className="h-3 w-3" />
            </button>
          )}
          <button
            onClick={onOpen}
            className="premium-control flex items-center gap-1 px-2 py-1 rounded text-[11px] text-muted-foreground hover:text-foreground"
            title="Open detail view (Space)"
          >
            <ExternalLink className="h-3 w-3" />
          </button>
        </div>
      </div>
    </div>
  );
}
