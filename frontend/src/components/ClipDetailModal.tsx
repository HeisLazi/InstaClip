/**
 * Modal preview opened when the user clicks a thumbnail in the Gallery.
 *
 * Phase 3 upgrades:
 *   - ConfidenceRings for generator score + live quality-classifier prediction
 *   - AnnotatedTranscript with decision-provenance highlighting
 *   - Per-signal breakdown (audio_spike, repetition, ...) where metadata exists
 *   - Triggers list (audio_spike / state_change / face_reaction / ...)
 */

import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, ExternalLink, Play, Scissors, Sparkles, Star, ThumbsDown, ThumbsUp, X } from "lucide-react";

import { api, type Bucket, type ClipDetails, type ClipReview } from "@/api/client";
import { AmbientPlayer } from "@/components/AmbientPlayer";
import { EditorModal } from "@/components/EditorModal";
import { EditorV2Modal } from "@/editor-v2/EditorV2Modal";
import { AnnotatedTranscript } from "@/components/AnnotatedTranscript";
import { ConfidenceRing } from "@/components/ConfidenceRing";
import { cn } from "@/lib/utils";

interface ClipDetailModalProps {
  bucket: Bucket;
  stem: string;
  candidateId?: string;
  onClose: () => void;
  autoPlay?: boolean;
  queuePosition?: number;
  queueLength?: number;
  onAutoPlayChange?: (enabled: boolean) => void;
  onPrevious?: () => void;
  onNext?: () => void;
  onAutoAdvance?: () => void;
}

export function ClipDetailModal({
  bucket,
  stem,
  candidateId,
  onClose,
  autoPlay = false,
  queuePosition,
  queueLength,
  onAutoPlayChange,
  onPrevious,
  onNext,
  onAutoAdvance,
}: ClipDetailModalProps) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState<"v2" | "legacy" | null>(null);

  const { data: details } = useQuery<ClipDetails>({
    queryKey: ["clip-details", bucket, stem],
    queryFn:  () => api.clips.details(bucket, stem),
  });

  // Close on Esc; label with arrow keys.
  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if (editing) {
        if (e.key === "Escape") setEditing(null);
        return;
      }
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight") moveTo("positives");
      if (e.key === "ArrowLeft")  moveTo("negatives");
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bucket, stem, editing]);

  async function moveTo(target: Bucket) {
    if (target === bucket) return;
    try {
      await api.clips.move(stem, bucket, target);
      if (autoPlay && onAutoAdvance) onAutoAdvance();
      else onClose();
      qc.invalidateQueries({ queryKey: ["clips"] });
      qc.invalidateQueries({ queryKey: ["clip-groups"] });
      qc.invalidateQueries({ queryKey: ["counts"] });
    } catch (e) {
      console.error("move failed", e);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/72 backdrop-blur-md"
      onClick={() => {
        if (!editing) onClose();
      }}
    >
      <div
        className="glass-strong modal-shell w-[min(1120px,94vw)] max-h-[92vh] rounded-xl flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between px-4 py-2 border-b border-border/40">
          <div className="min-w-0">
            <div className="truncate text-sm font-medium">{stem}.mp4</div>
            {queuePosition != null && queueLength != null && (
              <div className="text-[10px] tabular-nums text-muted-foreground">Queue {queuePosition} of {queueLength}</div>
            )}
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
            title="Close (Esc)"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex-1 overflow-hidden grid grid-cols-1 md:grid-cols-[1.4fr_1fr]">
          {/* Video with ambient glow */}
          <div className="bg-black/80 min-h-[280px]">
            <AmbientPlayer
              src={api.clips.videoUrl(bucket, stem)}
              videoKey={`${bucket}/${stem}`}
              className="h-full"
              autoPlay={autoPlay}
              onEnded={() => {
                if (!editing && autoPlay) onAutoAdvance?.();
              }}
            />
          </div>

          {/* Side panel */}
          <div className="border-l border-border/40 overflow-y-auto p-4 space-y-5">
            <Scores details={details} />
            <ReviewCard bucket={bucket} stem={stem} review={details?.review ?? null} />
            <SignalsCard details={details} />
            <TranscriptCard details={details} />
            <VisualCard details={details} />
          </div>
        </div>

        {/* Actions */}
        <footer className="flex items-center gap-2 border-t border-border/40 px-4 py-3 bg-background/45">
          <ActionBtn
            disabled={bucket === "positives"}
            tone="success"
            icon={ThumbsUp}
            label="Good (→)"
            onClick={() => moveTo("positives")}
          />
          <ActionBtn
            disabled={bucket === "negatives"}
            tone="destructive"
            icon={ThumbsDown}
            label="Bad (←)"
            onClick={() => moveTo("negatives")}
          />
          <ActionBtn
            tone="primary"
            icon={Scissors}
            label="Edit"
            onClick={() => setEditing("v2")}
          />
          <div className="mx-1 h-6 w-px bg-border/50" />
          <button type="button" onClick={onPrevious} disabled={!onPrevious} className="premium-control grid h-8 w-8 place-items-center rounded-md text-muted-foreground hover:text-foreground disabled:opacity-30" title="Previous clip in filtered queue" aria-label="Previous clip">
            <ChevronLeft className="h-4 w-4" />
          </button>
          <button type="button" onClick={onNext} disabled={!onNext} className="premium-control grid h-8 w-8 place-items-center rounded-md text-muted-foreground hover:text-foreground disabled:opacity-30" title="Next clip in filtered queue" aria-label="Next clip">
            <ChevronRight className="h-4 w-4" />
          </button>
          <button
            type="button"
            role="switch"
            aria-checked={autoPlay}
            onClick={() => onAutoPlayChange?.(!autoPlay)}
            className={cn(
              "premium-control flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs",
              autoPlay ? "border-primary/50 bg-primary/15 text-primary" : "text-muted-foreground hover:text-foreground",
            )}
            title="Automatically play the next clip in the filtered and sorted queue"
          >
            <Play className="h-3.5 w-3.5" fill={autoPlay ? "currentColor" : "none"} />
            Autoplay {autoPlay ? "on" : "off"}
          </button>
          <div className="flex-1" />
          <a
            href={api.clips.videoUrl(bucket, stem)}
            target="_blank"
            rel="noreferrer"
            className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
          >
            <ExternalLink className="h-3 w-3" />
            Open raw
          </a>
        </footer>
      </div>

      {editing === "v2" && (
        <EditorV2Modal
          bucket={bucket}
          stem={stem}
          candidateId={candidateId}
          onClose={() => setEditing(null)}
          onLegacy={() => setEditing("legacy")}
          onRendered={() => qc.invalidateQueries({ queryKey: ["clips"] })}
        />
      )}
      {editing === "legacy" && (
        <EditorModal
          bucket={bucket}
          stem={stem}
          onClose={() => setEditing(null)}
          onRendered={() => qc.invalidateQueries({ queryKey: ["clips"] })}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

const REVIEW_REASONS = [
  "strong reaction",
  "clean setup",
  "funny line",
  "good pacing",
  "visual context helps",
  "dead air",
  "weak payoff",
  "bad crop",
  "caption missed context",
  "wrong speaker",
];

function ReviewCard({
  bucket,
  stem,
  review,
}: {
  bucket: Bucket;
  stem: string;
  review: ClipReview | null;
}) {
  const qc = useQueryClient();
  const [rating, setRating] = useState(review?.rating ?? 0);
  const [verdict, setVerdict] = useState<ClipReview["verdict"]>(review?.verdict ?? "undecided");
  const [reasons, setReasons] = useState<string[]>(review?.reasons ?? []);
  const [tags, setTags] = useState<string[]>(review?.tags ?? []);
  const [customTag, setCustomTag] = useState("");
  const [notes, setNotes] = useState(review?.notes ?? "");
  const [captionNotes, setCaptionNotes] = useState(review?.caption_notes ?? "");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const taxonomyQuery = useQuery({ queryKey: ["clip-tag-taxonomy"], queryFn: api.clips.tagTaxonomy });
  const taxonomy = taxonomyQuery.data?.taxonomy ?? { good: [], bad: [] };
  const tagOptions = bucket === "positives" ? taxonomy.good : bucket === "negatives" ? taxonomy.bad : [...taxonomy.good, ...taxonomy.bad];

  useEffect(() => {
    setRating(review?.rating ?? 0);
    setVerdict(review?.verdict ?? "undecided");
    setReasons(review?.reasons ?? []);
    setTags(review?.tags ?? []);
    setCustomTag("");
    setNotes(review?.notes ?? "");
    setCaptionNotes(review?.caption_notes ?? "");
    setSaved(false);
  }, [review?.updated_at, stem]);

  function toggleReason(reason: string) {
    setSaved(false);
    setReasons((cur) =>
      cur.includes(reason) ? cur.filter((r) => r !== reason) : [...cur, reason],
    );
  }

  function toggleTag(tag: string) {
    setSaved(false);
    setTags((current) => current.includes(tag) ? current.filter((item) => item !== tag) : [...current, tag]);
  }

  async function save() {
    setSaving(true);
    try {
      const nextTags = new Set(tags);
      customTag.split(",").map((tag) => tag.trim().toLowerCase()).filter(Boolean).forEach((tag) => nextTags.add(tag));
      await api.reviews.save(stem, bucket, {
        rating: rating || null,
        verdict,
        reasons,
        tags: [...nextTags],
        notes,
        caption_notes: captionNotes,
      });
      setSaved(true);
      setTags([...nextTags]);
      setCustomTag("");
      qc.invalidateQueries({ queryKey: ["clip-details", bucket, stem] });
      qc.invalidateQueries({ queryKey: ["clips"] });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Section title="Review">
      <div className="space-y-3">
        <div className="flex items-center gap-1">
          {[1, 2, 3, 4, 5].map((value) => (
            <button
              key={value}
              onClick={() => { setRating(value); setSaved(false); }}
              className={cn(
                "grid h-7 w-7 place-items-center rounded-md transition-colors",
                value <= rating ? "text-warning bg-warning/12" : "text-muted-foreground hover:text-foreground hover:bg-accent/40",
              )}
              title={`${value} star${value === 1 ? "" : "s"}`}
            >
              <Star className="h-4 w-4" fill={value <= rating ? "currentColor" : "none"} />
            </button>
          ))}
        </div>

        <div className="grid grid-cols-4 gap-1">
          {(["keeper", "maybe", "miss", "undecided"] as const).map((v) => (
            <button
              key={v}
              onClick={() => { setVerdict(v); setSaved(false); }}
              className={cn(
                "text-[11px] px-2 py-1.5 rounded premium-control capitalize",
                verdict === v
                  ? "text-primary border-primary/45"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {v === "undecided" ? "Unset" : v}
            </button>
          ))}
        </div>

        <div className="flex flex-wrap gap-1">
          {REVIEW_REASONS.map((reason) => (
            <button
              key={reason}
              onClick={() => toggleReason(reason)}
              className={cn(
                "text-[10px] px-2 py-1 rounded border transition-colors",
                reasons.includes(reason)
                  ? "border-primary/45 bg-primary/12 text-primary"
                  : "border-border/50 text-muted-foreground hover:text-foreground hover:bg-accent/35",
              )}
            >
              {reason}
            </button>
          ))}
        </div>

        <div className="space-y-1.5 border-t border-border/40 pt-2">
          <div className="flex items-center justify-between text-[10px] uppercase tracking-[0.12em] text-muted-foreground"><span>Tag folders</span><span>{tags.length} selected</span></div>
          <div className="flex flex-wrap gap-1">
            {[...new Set([...tagOptions, ...tags])].map((tag) => (
              <button key={tag} type="button" onClick={() => toggleTag(tag)} className={cn("rounded border px-2 py-1 text-[10px] capitalize transition-colors", tags.includes(tag) ? "border-primary/45 bg-primary/12 text-primary" : "border-border/50 text-muted-foreground hover:text-foreground")}>#{tag}</button>
            ))}
          </div>
          <input value={customTag} onChange={(event) => { setCustomTag(event.target.value); setSaved(false); }} placeholder="Custom tags, comma-separated" className="premium-control w-full rounded-md px-2 py-1.5 text-xs outline-none placeholder:text-muted-foreground" />
        </div>

        <textarea
          value={notes}
          onChange={(e) => { setNotes(e.target.value); setSaved(false); }}
          placeholder="Why this worked or missed"
          className="premium-control w-full min-h-[68px] rounded-md px-2 py-1.5 text-xs outline-none focus:ring-1 focus:ring-primary placeholder:text-muted-foreground resize-y"
        />
        <textarea
          value={captionNotes}
          onChange={(e) => { setCaptionNotes(e.target.value); setSaved(false); }}
          placeholder="Caption or visual context notes"
          className="premium-control w-full min-h-[58px] rounded-md px-2 py-1.5 text-xs outline-none focus:ring-1 focus:ring-primary placeholder:text-muted-foreground resize-y"
        />
        <button
          onClick={save}
          disabled={saving}
          className="premium-control px-3 py-1.5 rounded-md text-xs text-foreground hover:border-primary/40 disabled:opacity-50"
        >
          {saving ? "Saving..." : saved ? "Saved" : "Save review"}
        </button>
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------------------

function Scores({ details }: { details?: ClipDetails }) {
  const gen = details?.score ?? null;
  const quality = details?.quality_prediction ?? details?.signals?.quality_score ?? null;

  return (
    <div className="flex items-center gap-4">
      <ConfidenceRing
        value={gen}
        size={64}
        caption="gen"
        title={
          gen != null
            ? `Generator score: ${(gen * 100).toFixed(0)}%`
            : "Generator score unavailable"
        }
      />
      <ConfidenceRing
        value={quality}
        size={64}
        caption="LLM"
        title={
          quality != null
            ? `Quality classifier: ${(quality * 100).toFixed(0)}%`
            : "Classifier not trained or transcript unavailable"
        }
      />
      <div className="text-[11px] text-muted-foreground">
        {details?.signals?.clip_type && (
          <div>
            <span className="text-foreground/70">Type</span>{" "}
            <code className="text-foreground/90">{details.signals.clip_type}</code>
          </div>
        )}
        <div className="mt-0.5">{details?.size_mb?.toFixed(1) ?? "—"} MB</div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------

const SIGNAL_KEYS: Array<{ key: keyof NonNullable<ClipDetails["signals"]>; label: string; hint: string }> = [
  { key: "audio_spike",    label: "Audio spike",     hint: "Loud burst relative to baseline" },
  { key: "explosion",      label: "Explosion",       hint: "Silence → spike pattern" },
  { key: "repetition",     label: "Repetition",      hint: "Words / phrases repeating" },
  { key: "profile_match",  label: "Profile match",   hint: "Hits your highlight_words / hype_phrases" },
  { key: "keyword_spike",  label: "Keyword + spike", hint: "Hype word at the moment of an audio spike" },
  { key: "face_reaction",  label: "Face reaction",   hint: "MediaPipe blendshapes — jaw open, brow up, etc." },
  { key: "state_change",   label: "State change",    hint: "Energy shift between pre- and post-window" },
  { key: "aftermath",      label: "Aftermath",       hint: "Sustained energy after the peak" },
  { key: "semantic_boost", label: "Semantic boost",  hint: "Slang/semantic dictionary hits" },
];

const HAZARD_LABELS: Record<string, { label: string; hint: string }> = {
  dyk_schism:           { label: "DYK schism",           hint: "Mentions tied to the Kai/YourRage/Bruce fallout — may be toxic vs. comedic" },
  theatrical_violence:  { label: "theatrical violence",  hint: "Spatial threats — check this is comedic, not a real TOS violation" },
  intoxication_hint:    { label: "intoxication hint",    hint: "Phrasing implies impaired speech — may need a content classification label" },
  political_debate:     { label: "political debate",     hint: "Civic/political content — short-form algorithms suppress this" },
  dmca_risk_audio_marker:{ label: "DMCA risk",           hint: "Background commercial music with no reactive transcript" },
  dmca_risk:            { label: "DMCA risk",            hint: "High audio energy with no transcript — possible background music" },
  dead_air:             { label: "dead air",             hint: "No speech + low energy — destroys retention" },
};

function SignalsCard({ details }: { details?: ClipDetails }) {
  const signals = details?.signals;
  const triggers = details?.triggers ?? [];
  const hazards = details?.hazard_flags ?? [];

  if (!signals && (!triggers || triggers.length === 0) && hazards.length === 0) {
    return null; // older clips (in old_clips/) don't have stored metadata.
  }

  return (
    <Section title="Why this scored" icon={Sparkles}>
      {hazards.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-2">
          {hazards.map((h) => {
            const info = HAZARD_LABELS[h] ?? { label: h.replace(/_/g, " "), hint: "Flagged by hazard detector" };
            return (
              <span
                key={h}
                title={info.hint}
                className="text-[10px] px-1.5 py-0.5 rounded bg-destructive/15 text-destructive border border-destructive/40"
              >
                ⚠ {info.label}
              </span>
            );
          })}
        </div>
      )}

      {triggers.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-2">
          {triggers.map((t) => (
            <span
              key={t}
              title={`${t} fired during scoring`}
              className="text-[10px] px-1.5 py-0.5 rounded bg-primary/15 text-primary border border-primary/30"
            >
              {t.replace(/_/g, " ")}
            </span>
          ))}
        </div>
      )}

      {signals && (
        <div className="grid grid-cols-1 gap-1.5">
          {SIGNAL_KEYS.map(({ key, label, hint }) => {
            const v = (signals[key] as number | undefined);
            if (typeof v !== "number") return null;
            const pct = Math.max(0, Math.min(100, v * 100));
            return (
              <div key={String(key)} className="grid grid-cols-[110px_1fr_42px] items-center gap-2 text-[11px]">
                <span className="text-muted-foreground truncate" title={hint}>{label}</span>
                <div className="h-1.5 rounded-full bg-secondary overflow-hidden">
                  <div
                    className={cn(
                      "h-full transition-[width] duration-300",
                      pct >= 70 ? "bg-success" : pct >= 40 ? "bg-primary" : "bg-muted-foreground/60",
                    )}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className="tabular-nums text-right text-foreground/85">{v.toFixed(2)}</span>
              </div>
            );
          })}
        </div>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------------------

function TranscriptCard({ details }: { details?: ClipDetails }) {
  return (
    <Section title="Transcript">
      <AnnotatedTranscript text={details?.transcript ?? ""} />
      <div className="mt-2 text-[10px] text-muted-foreground/80">
        Underlined words are profile matches — hover to see what they contribute.
      </div>
    </Section>
  );
}

function VisualCard({ details }: { details?: ClipDetails }) {
  if (!details?.visual_caption) return null;
  return (
    <Section title="Visual context">
      <p className="text-sm leading-relaxed text-foreground/85">{details.visual_caption}</p>
    </Section>
  );
}

// ---------------------------------------------------------------------------

interface SectionProps {
  title: string;
  children: React.ReactNode;
  icon?: React.ComponentType<{ className?: string }>;
}

function Section({ title, children, icon: Icon }: SectionProps) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground mb-1 flex items-center gap-1">
        {Icon && <Icon className="h-3 w-3" />}
        {title}
      </div>
      {children}
    </div>
  );
}

interface ActionBtnProps {
  tone: "success" | "destructive" | "primary";
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  onClick: () => void;
  disabled?: boolean;
}

function ActionBtn({ tone, icon: Icon, label, onClick, disabled }: ActionBtnProps) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
        className={cn(
        "premium-control flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors",
        disabled && "opacity-40 cursor-not-allowed",
        tone === "success"
          ? "text-success hover:bg-success/10"
          : tone === "primary"
          ? "text-primary hover:bg-primary/10"
          : "text-destructive hover:bg-destructive/10",
      )}
    >
      <Icon className="h-3.5 w-3.5" />
      {label}
    </button>
  );
}
