import { useDeferredValue, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Clock3, Loader2, Search, Sparkles, Trash2, WandSparkles } from "lucide-react";

import { api, type TranscriptEditOperation, type TranscriptEditReport } from "@/api/client";
import type { EditorProjectV2, StoryBeat } from "@/editor-v2/model";
import { cn } from "@/lib/utils";

type SelectedRange = { key: string; start: number; end: number; label: string };

export function TranscriptPanel({
  project,
  onSeek,
  onApply,
}: {
  project: EditorProjectV2;
  onSeek: (time: number) => void;
  onApply: (ops: TranscriptEditOperation[]) => Promise<TranscriptEditReport>;
}) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Record<string, SelectedRange>>({});
  const [fillers, setFillers] = useState("um, uh, uhm, erm, like");
  const [visibleCount, setVisibleCount] = useState(40);
  const [busy, setBusy] = useState<"cut" | "silence" | "fillers" | null>(null);
  const [report, setReport] = useState<TranscriptEditReport | null>(null);
  const deferredQuery = useDeferredValue(query.trim().toLowerCase());
  const transcriptQuery = useQuery({
    queryKey: ["editor-source-transcript", project.id],
    queryFn: () => api.edit.v2.transcript(project.id),
    retry: false,
    staleTime: 60_000,
  });
  const beats = project.longformPlan?.storyGraph?.beats ?? [];
  const sourceSegments = transcriptQuery.data?.segments ?? [];
  const filteredSource = sourceSegments
    .map((segment, index) => ({ segment, index }))
    .filter(({ segment }) => !deferredQuery || segment.text.toLowerCase().includes(deferredQuery));
  const filteredBeats = deferredQuery
    ? beats.filter((beat) => `${beat.title} ${beat.text} ${beat.role}`.toLowerCase().includes(deferredQuery))
    : beats;
  const selectedRanges = Object.values(selected);

  useEffect(() => setVisibleCount(40), [deferredQuery, project.id]);

  async function apply(kind: "cut" | "silence" | "fillers", ops: TranscriptEditOperation[]) {
    setBusy(kind);
    try {
      const next = await onApply(ops);
      setReport(next);
      setSelected({});
    } finally {
      setBusy(null);
    }
  }

  function toggleRange(range: SelectedRange, mutuallyExclusivePrefix?: string) {
    setSelected((current) => {
      const next = { ...current };
      if (next[range.key]) {
        delete next[range.key];
        return next;
      }
      if (mutuallyExclusivePrefix) {
        Object.keys(next).filter((key) => key.startsWith(mutuallyExclusivePrefix)).forEach((key) => delete next[key]);
      }
      next[range.key] = range;
      return next;
    });
  }

  function toggleBeat(beat: StoryBeat) {
    toggleRange({ key: `beat:${beat.id}`, start: beat.start, end: beat.end, label: beat.title });
  }

  return <div className="space-y-3">
    <div>
      <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.14em] text-cyan-200"><WandSparkles className="h-3.5 w-3.5" /> Edit by transcript</div>
      <p className="mt-1 text-[9px] leading-4 text-slate-500">Delete spoken segments or individual timestamped words to cut the linked source range. The original video and transcript remain unchanged.</p>
    </div>

    <section className="space-y-2 rounded border border-white/10 bg-black/20 p-2">
      <div className="text-[8px] font-bold uppercase tracking-[0.14em] text-slate-500">Quick cleanup</div>
      <button type="button" disabled={busy !== null} onClick={() => void apply("silence", [{ type: "remove_silences", min_gap: 0.8, pad: 0.15, noise_db: -35 }])} className="editor-v2-action w-full justify-center text-[9px] disabled:opacity-40">{busy === "silence" ? <Loader2 className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3" />} Remove pauses over 0.8s</button>
      <label className="block text-[8px] uppercase tracking-wide text-slate-600">Filler words<input value={fillers} onChange={(event) => setFillers(event.target.value)} className="editor-v2-input mt-1" /></label>
      <button type="button" disabled={busy !== null || !fillers.trim()} onClick={() => void apply("fillers", [{ type: "remove_fillers", words: fillers.split(",").map((word) => word.trim()).filter(Boolean), pad: 0.05 }])} className="editor-v2-action w-full justify-center text-[9px] disabled:opacity-40">{busy === "fillers" ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />} Remove filler words</button>
    </section>

    {report && <div className="rounded border border-emerald-300/20 bg-emerald-300/[0.05] p-2 text-[8px] leading-4 text-emerald-100/80">Removed {report.removed_seconds.toFixed(2)}s across {report.items_split} timeline item{report.items_split === 1 ? "" : "s"}. {report.skipped_items.length > 0 ? `${report.skipped_items.length} speed-adjusted item(s) were left unchanged.` : "The updated timeline is saved to this project."}</div>}

    <section className="space-y-2">
      <div className="relative"><Search className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-slate-600" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find exact words or moments" className="editor-v2-input pl-7" /></div>
      {transcriptQuery.isLoading && <div className="flex items-center justify-center gap-2 py-8 text-[9px] text-slate-500"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading source transcript</div>}
      {sourceSegments.length > 0 && <>
        <div className="flex items-center justify-between text-[8px] uppercase tracking-wide text-slate-600"><span>{filteredSource.length} source segments · {transcriptQuery.data?.has_words ? "word timing ready" : "segment timing"}</span>{selectedRanges.length > 0 && <button type="button" onClick={() => setSelected({})} className="text-cyan-300/70 hover:text-cyan-200">Clear {selectedRanges.length}</button>}</div>
        <div className="max-h-[420px] space-y-1 overflow-y-auto pr-1">{filteredSource.slice(0, visibleCount).map(({ segment, index }) => {
          const segmentKey = `segment:${index}`;
          const segmentSelected = Boolean(selected[segmentKey]);
          return <div key={segmentKey} className={cn("rounded border p-2", segmentSelected ? "border-rose-300/30 bg-rose-300/[0.06]" : "border-white/8 bg-white/[0.02]")}>
            <div className="flex items-start gap-2">
              <input type="checkbox" checked={segmentSelected} onChange={() => toggleRange({ key: segmentKey, start: segment.start, end: segment.end, label: segment.text }, `word:${index}:`)} className="mt-0.5 accent-rose-300" aria-label={`Select transcript segment at ${clock(segment.start)} for removal`} />
              <button type="button" onClick={() => onSeek(segment.start)} className="min-w-0 flex-1 text-left"><span className="flex items-center gap-1 text-[8px] tabular-nums text-cyan-200/70"><Clock3 className="h-3 w-3" /> {clock(segment.start)}-{clock(segment.end)}</span><span className="mt-1 block text-[8px] leading-3 text-slate-400">{segment.text}</span></button>
            </div>
            {segment.words.length > 0 && <div className="mt-2 flex flex-wrap gap-1 border-t border-white/5 pt-2">{segment.words.map((word, wordIndex) => {
              const wordKey = `word:${index}:${wordIndex}`;
              const wordSelected = Boolean(selected[wordKey]);
              return <button key={wordKey} type="button" disabled={segmentSelected} onClick={() => toggleRange({ key: wordKey, start: word.start, end: word.end, label: word.text }, segmentKey)} title={`${clock(word.start)}-${clock(word.end)} · click to remove this word`} className={cn("rounded px-1 py-0.5 text-[8px] leading-3", wordSelected ? "bg-rose-300 text-slate-950" : "bg-white/[0.045] text-slate-400 hover:bg-cyan-300/10 hover:text-cyan-100", segmentSelected && "opacity-35")}>{word.text}</button>;
            })}</div>}
          </div>;
        })}</div>
        {visibleCount < filteredSource.length && <button type="button" onClick={() => setVisibleCount((count) => count + 40)} className="editor-v2-action w-full justify-center text-[8px]">Show 40 more</button>}
      </>}
      {!transcriptQuery.isLoading && sourceSegments.length === 0 && beats.length > 0 && <StoryRangeFallback beats={filteredBeats} selected={selected} onToggle={toggleBeat} onSeek={onSeek} />}
      {!transcriptQuery.isLoading && sourceSegments.length === 0 && beats.length === 0 && <div className="rounded border border-amber-300/15 bg-amber-300/[0.04] p-3 text-[9px] leading-4 text-amber-100/65">No source transcript is available for this project yet. Pause cleanup remains available above.</div>}
      {transcriptQuery.isError && beats.length > 0 && <p className="text-[8px] leading-3 text-amber-200/60">Source transcript is not live in this backend process yet, so the editor is using the project story map until the automatic backend restart.</p>}
      <button type="button" disabled={busy !== null || selectedRanges.length === 0} onClick={() => void apply("cut", [{ type: "cut_ranges", ranges: selectedRanges.map((range) => ({ start: range.start, end: range.end })) }])} className="flex w-full items-center justify-center gap-1.5 rounded bg-rose-300 px-2 py-2 text-[9px] font-bold text-slate-950 disabled:opacity-35">{busy === "cut" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />} Cut {selectedRanges.length || "selected"} transcript range{selectedRanges.length === 1 ? "" : "s"}</button>
    </section>
  </div>;
}

function StoryRangeFallback({ beats, selected, onToggle, onSeek }: { beats: StoryBeat[]; selected: Record<string, SelectedRange>; onToggle: (beat: StoryBeat) => void; onSeek: (time: number) => void }) {
  return <><div className="text-[8px] uppercase tracking-wide text-slate-600">{beats.length} story ranges</div><div className="max-h-[420px] space-y-1 overflow-y-auto pr-1">{beats.map((beat) => {
    const key = `beat:${beat.id}`;
    return <div key={beat.id} className={cn("rounded border p-2", selected[key] ? "border-rose-300/30 bg-rose-300/[0.06]" : "border-white/8 bg-white/[0.02]")}><div className="flex items-start gap-2"><input type="checkbox" checked={Boolean(selected[key])} onChange={() => onToggle(beat)} className="mt-0.5 accent-rose-300" aria-label={`Select ${beat.title} for removal`} /><button type="button" onClick={() => onSeek(beat.start)} className="min-w-0 flex-1 text-left"><span className="flex items-center gap-1 text-[8px] tabular-nums text-cyan-200/70"><Clock3 className="h-3 w-3" /> {clock(beat.start)}-{clock(beat.end)} · {beat.role}</span><span className="mt-1 block text-[9px] font-semibold text-slate-300">{beat.title}</span><span className="mt-1 line-clamp-3 block text-[8px] leading-3 text-slate-500">{beat.text}</span></button></div></div>;
  })}</div></>;
}

function clock(seconds: number) {
  const safe = Math.max(0, Math.round(seconds));
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const rest = safe % 60;
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}` : `${minutes}:${String(rest).padStart(2, "0")}`;
}
