/**
 * Transcript with decision provenance — highlights words/phrases that match
 * the active profile and shows a tooltip explaining the boost / penalty.
 *
 * Doc reference: Section 9 "Interactive Transcripts and Decision Provenance".
 */

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import { cn } from "@/lib/utils";

interface AnnotatedTranscriptProps {
  text: string;
  className?: string;
}

type Tone = "highlight" | "hype" | "repetition" | "penalty" | "background" | "low_energy";

interface Match {
  pattern: string;     // lowercased
  tone:    Tone;
  detail:  string;
  score?:  number;
}

const TONE_CLASS: Record<Tone, string> = {
  highlight:  "decoration-success/70    text-success-foreground/95 bg-success/15",
  hype:       "decoration-primary/70    text-foreground bg-primary/15",
  repetition: "decoration-primary/70    text-foreground bg-primary/10",
  penalty:    "decoration-destructive   text-destructive-foreground/95 bg-destructive/15",
  background: "decoration-muted-foreground/40 text-muted-foreground",
  low_energy: "decoration-warning/60    text-warning bg-warning/10",
};

const TONE_LABEL: Record<Tone, string> = {
  highlight:  "Highlight word",
  hype:       "Hype phrase",
  repetition: "Repetition pattern",
  penalty:    "Penalized word",
  background: "Background word",
  low_energy: "Low-energy phrase",
};

function buildMatches(profile: any): Match[] {
  if (!profile) return [];
  const out: Match[] = [];
  for (const w of (profile.highlight_words ?? [])) {
    if (typeof w === "string") out.push({ pattern: w.toLowerCase(), tone: "highlight", detail: "Boosts score" });
  }
  for (const w of (profile.penalized_words ?? [])) {
    if (typeof w === "string") out.push({ pattern: w.toLowerCase(), tone: "penalty", detail: "Drops score hard" });
  }
  for (const w of (profile.background_words ?? [])) {
    if (typeof w === "string") out.push({ pattern: w.toLowerCase(), tone: "background", detail: "Filler — too many = penalty" });
  }
  for (const p of (profile.low_energy_patterns ?? [])) {
    if (typeof p === "string") out.push({ pattern: p.toLowerCase(), tone: "low_energy", detail: "Calm/thoughtful talk — penalty" });
  }
  for (const item of (profile.hype_phrases ?? [])) {
    const phrase = typeof item === "string" ? item : item?.phrase;
    if (phrase) out.push({
      pattern: String(phrase).toLowerCase(),
      tone: "hype",
      detail: "Hype phrase match — boost",
      score: typeof item === "object" ? item?.score : undefined,
    });
  }
  for (const item of (profile.repetition_patterns ?? [])) {
    const pattern = typeof item === "string" ? item : item?.pattern;
    if (pattern) out.push({
      pattern: String(pattern).toLowerCase(),
      tone: "repetition",
      detail: "Repetition pattern — boost",
      score: typeof item === "object" ? item?.score : undefined,
    });
  }
  // Longer patterns first so multi-word phrases beat single-word matches.
  out.sort((a, b) => b.pattern.length - a.pattern.length);
  return out;
}

interface Segment {
  text: string;
  match?: Match;
}

function segmentText(text: string, matches: Match[]): Segment[] {
  if (!matches.length) return [{ text }];
  const lower = text.toLowerCase();
  // Walk the string left-to-right; at each position try every pattern
  // (longest-first) and consume the first hit.
  const out: Segment[] = [];
  let i = 0;
  let plain = "";

  while (i < text.length) {
    let hit: Match | undefined;
    let hitLen = 0;
    for (const m of matches) {
      const len = m.pattern.length;
      if (len === 0 || i + len > text.length) continue;
      if (lower.substr(i, len) !== m.pattern) continue;
      // Word-boundary check for single-word patterns; phrases match anywhere.
      const isPhrase = m.pattern.includes(" ");
      if (!isPhrase) {
        const before = i === 0 ? " " : text[i - 1];
        const after  = i + len >= text.length ? " " : text[i + len];
        if (/[a-z0-9_]/i.test(before) || /[a-z0-9_]/i.test(after)) continue;
      }
      hit = m;
      hitLen = len;
      break;
    }

    if (hit) {
      if (plain) {
        out.push({ text: plain });
        plain = "";
      }
      out.push({ text: text.substr(i, hitLen), match: hit });
      i += hitLen;
    } else {
      plain += text[i];
      i += 1;
    }
  }
  if (plain) out.push({ text: plain });
  return out;
}

export function AnnotatedTranscript({ text, className }: AnnotatedTranscriptProps) {
  const { data: profileData } = useQuery({
    queryKey: ["profile"],
    queryFn:  api.profile.get,
    staleTime: 60_000,
  });

  const matches = useMemo(
    () => buildMatches(profileData?.profile),
    [profileData?.profile],
  );

  const segments = useMemo(
    () => segmentText(text ?? "", matches),
    [text, matches],
  );

  if (!text) {
    return (
      <p className="text-xs italic text-muted-foreground">No transcript cached yet.</p>
    );
  }

  return (
    <div className={cn("text-sm leading-relaxed whitespace-pre-wrap text-foreground/85", className)}>
      {segments.map((seg, i) =>
        seg.match ? (
          <span
            key={i}
            title={`${TONE_LABEL[seg.match.tone]}${seg.match.score != null ? ` · score ${seg.match.score.toFixed(2)}` : ""}\n${seg.match.detail}`}
            className={cn(
              "underline decoration-2 underline-offset-2 rounded px-0.5",
              TONE_CLASS[seg.match.tone],
            )}
          >
            {seg.text}
          </span>
        ) : (
          <span key={i}>{seg.text}</span>
        ),
      )}
    </div>
  );
}
