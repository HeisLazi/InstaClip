import { useEffect, useState } from "react";
import { AlertTriangle, BookOpen, Captions, Clock3, Copy, FolderOpen, ListChecks, Loader2, Play, Rewind, Save, Sparkles, Target, Youtube } from "lucide-react";

import { api } from "@/api/client";
import type { EditorProjectV2, LongformPlan, StoryBeatRole, YouTubeBrandKit } from "@/editor-v2/model";
import { cn } from "@/lib/utils";
import { pickVodFile } from "@/lib/tauri";

const ROLE_STYLE: Record<StoryBeatRole, string> = {
  setup: "border-cyan-300/30 bg-cyan-300/[0.07] text-cyan-200",
  escalation: "border-amber-300/30 bg-amber-300/[0.07] text-amber-200",
  development: "border-white/10 bg-white/[0.03] text-slate-300",
  reaction: "border-rose-300/30 bg-rose-300/[0.07] text-rose-200",
  callback: "border-violet-300/30 bg-violet-300/[0.07] text-violet-200",
  payoff: "border-emerald-300/30 bg-emerald-300/[0.07] text-emerald-200",
};
type FlashbackSuggestion = NonNullable<LongformPlan["flashbackSuggestions"]>[number];
type YouTubePackageChanges = Partial<Pick<NonNullable<LongformPlan["youtubePackage"]>, "title" | "description" | "tags">>;

function clock(seconds: number) {
  const safe = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const secs = safe % 60;
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`
    : `${minutes}:${String(secs).padStart(2, "0")}`;
}

export function StoryPanel({
  project,
  onSeek,
  onOpenProject,
  onRenameChapter,
  onAddFlashback,
  onUpdateYouTubePackage,
}: {
  project: EditorProjectV2;
  onSeek: (time: number) => void;
  onOpenProject?: (projectId: string, name: string) => void;
  onRenameChapter: (chapterId: string, title: string) => void;
  onAddFlashback: (suggestion: FlashbackSuggestion) => void;
  onUpdateYouTubePackage: (changes: YouTubePackageChanges) => void;
}) {
  const plan = project.longformPlan;
  const [brief, setBrief] = useState(plan?.brief || project.name);
  const [streamType, setStreamType] = useState(plan?.streamContext?.selectedType || "auto");
  const [goal, setGoal] = useState(plan?.streamContext?.goal || plan?.brief || "");
  const [requiredEvents, setRequiredEvents] = useState((plan?.streamContext?.requiredEvents ?? []).map((event) => event.query).join("\n"));
  const [excludedTopics, setExcludedTopics] = useState((plan?.streamContext?.excludedTopics ?? []).join("\n"));
  const [targetMinutes, setTargetMinutes] = useState(plan?.target_minutes || 12);
  const [maxSections, setMaxSections] = useState(Math.max(4, plan?.sections?.length || 12));
  const [captions, setCaptions] = useState(true);
  const [busy, setBusy] = useState(false);
  const [brandBusy, setBrandBusy] = useState(false);
  const [brandKit, setBrandKit] = useState<YouTubeBrandKit | null>(null);
  const [message, setMessage] = useState("");
  const chapters = plan?.chapters ?? [];
  const flashbacks = plan?.flashbackSuggestions ?? [];
  const beats = plan?.storyGraph?.beats ?? [];
  const quality = plan?.qualityReport;
  const narrativeArc = plan?.narrativeArc ?? plan?.storyGraph?.narrativeArc ?? [];
  const assembly = plan?.assembly;
  const youtubePackage = plan?.youtubePackage;
  const youtubeDescription = youtubePackage?.description.split("\n\nChapters\n")[0] ?? "";
  const appliedFlashbacks = new Set(plan?.appliedFlashbacks ?? []);
  const selectedBeatIds = new Set((plan?.sections ?? []).flatMap((section) => section.beatIds));

  useEffect(() => {
    void api.edit.v2.brandKit()
      .then((result) => setBrandKit(result.brand_kit))
      .catch((error) => setMessage(error instanceof Error ? error.message : String(error)));
  }, []);

  async function chooseBrandVideo(field: "intro_path" | "outro_path") {
    const path = await pickVodFile();
    if (path) setBrandKit((current) => current ? { ...current, [field]: path } : current);
  }

  async function saveBrandKit() {
    if (!brandKit) return;
    setBrandBusy(true);
    setMessage("");
    try {
      const result = await api.edit.v2.saveBrandKit(brandKit);
      setBrandKit(result.brand_kit);
      setMessage("YouTube brand kit saved on this PC.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBrandBusy(false);
    }
  }

  async function buildStoryCut() {
    if (!brief.trim()) return;
    setBusy(true);
    setMessage("");
    try {
      const result = await api.edit.v2.storyCut(project.id, {
        brief: brief.trim(),
        target_minutes: targetMinutes,
        max_sections: maxSections,
        generate_captions: captions,
        stream_type: streamType,
        goal: goal.trim(),
        required_events: lines(requiredEvents),
        excluded_topics: lines(excludedTopics),
      });
      setMessage(`Created ${result.project.name}: ${result.plan.sections?.length ?? 0} sections, ${result.plan.captionsGenerated ?? 0} captions.`);
      onOpenProject?.(result.project.id, result.project.name);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function copyChapters() {
    const text = chapters.map((chapter) => `${clock(chapter.timelineStart)} ${chapter.title}`).join("\n");
    try {
      await navigator.clipboard.writeText(text);
      setMessage("YouTube chapter timestamps copied.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }

  async function copyYouTubePackage() {
    if (!youtubePackage) return;
    const chaptersBlock = youtubePackage.chapterText ? `\n\nChapters\n${youtubePackage.chapterText}` : "";
    const text = `${youtubePackage.title}\n\n${youtubeDescription}${chaptersBlock}\n\nTags: ${youtubePackage.tags.join(", ")}`;
    try {
      await navigator.clipboard.writeText(text);
      setMessage("YouTube delivery package copied.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }

  return <div className="space-y-4">
    <div>
      <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400"><BookOpen className="h-3.5 w-3.5 text-amber-300" /> Story director</div>
      <p className="mt-1 text-[9px] leading-4 text-slate-600">Builds a new project from transcript evidence. Your full VOD and current edit remain untouched.</p>
    </div>

    {brandKit && <section className="space-y-2 rounded border border-red-300/15 bg-red-300/[0.03] p-2">
      <div className="flex items-center justify-between gap-2"><div><div className="flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-[0.14em] text-red-200/80"><Youtube className="h-3.5 w-3.5" /> YouTube format</div><p className="mt-1 text-[8px] leading-3 text-slate-600">Local to this PC. Prelude → intro → story → outro → optional post-credit.</p></div><button type="button" disabled={brandBusy} onClick={() => void saveBrandKit()} className="editor-v2-action shrink-0 text-[8px]"><Save className="h-3 w-3" /> {brandBusy ? "Saving" : "Save"}</button></div>
      <BrandVideoField label="Intro video" value={brandKit.intro_path} available={brandKit.intro_available} onChange={(value) => setBrandKit({ ...brandKit, intro_path: value })} onChoose={() => void chooseBrandVideo("intro_path")} />
      <BrandVideoField label="Outro video" value={brandKit.outro_path} available={brandKit.outro_available} onChange={(value) => setBrandKit({ ...brandKit, outro_path: value })} onChoose={() => void chooseBrandVideo("outro_path")} />
      <label className="flex items-center justify-between text-[8px] text-slate-400"><span>Build a later-moment cold open</span><input type="checkbox" checked={brandKit.prelude_enabled} onChange={(event) => setBrandKit({ ...brandKit, prelude_enabled: event.target.checked })} className="accent-red-300" /></label>
      <div className="grid grid-cols-2 gap-2">
        <label className="text-[8px] uppercase tracking-wide text-slate-600">Prelude clips<input type="number" min={1} max={3} value={brandKit.prelude_count} onChange={(event) => setBrandKit({ ...brandKit, prelude_count: Number(event.target.value) })} className="editor-v2-input mt-1" /></label>
        <label className="text-[8px] uppercase tracking-wide text-slate-600">Seconds each<input type="number" min={4} max={14} step={0.5} value={brandKit.prelude_clip_seconds} onChange={(event) => setBrandKit({ ...brandKit, prelude_clip_seconds: Number(event.target.value) })} className="editor-v2-input mt-1" /></label>
      </div>
      <label className="block text-[8px] uppercase tracking-wide text-slate-600">Funny post-credit<select value={brandKit.post_credit_mode} onChange={(event) => setBrandKit({ ...brandKit, post_credit_mode: event.target.value as YouTubeBrandKit["post_credit_mode"] })} className="editor-v2-input mt-1"><option value="auto">Only when high confidence</option><option value="never">Never</option><option value="always">Always use best omitted beat</option></select></label>
    </section>}

    <section className="space-y-2 rounded border border-white/10 bg-black/20 p-2">
      <div className="flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-[0.14em] text-amber-200/80"><Target className="h-3.5 w-3.5" /> Define the episode before cutting</div>
      <label className="block text-[9px] uppercase tracking-wide text-slate-500">Stream format<select value={streamType} onChange={(event) => setStreamType(event.target.value)} className="editor-v2-input mt-1"><option value="auto">Detect automatically</option><option value="challenge">Challenge / competition</option><option value="reaction">Reaction</option><option value="gaming">Gaming session</option><option value="irl_event">IRL / event</option><option value="discussion">Discussion / podcast</option><option value="dating_social">Dating / social format</option><option value="sports_watchalong">Sports watchalong</option><option value="variety">Variety / mixed stream</option></select></label>
      <label className="block text-[9px] uppercase tracking-wide text-slate-500">Episode promise<textarea value={goal} onChange={(event) => setGoal(event.target.value)} rows={2} placeholder="Example: Show the full wing challenge, who attempts it, why Ice's attempt matters, and how everyone reacts afterward." className="editor-v2-input mt-1 resize-y" /><span className="mt-1 block normal-case leading-3 text-slate-600">What should a viewer understand or feel by the end?</span></label>
      <label className="block text-[9px] uppercase tracking-wide text-slate-500">Editing angle<textarea value={brief} onChange={(event) => setBrief(event.target.value)} rows={2} placeholder="Fast, funny challenge story with escalating pain and reactions" className="editor-v2-input mt-1 resize-y" /></label>
      <label className="block text-[9px] uppercase tracking-wide text-slate-500">Must-include moments<textarea value={requiredEvents} onChange={(event) => setRequiredEvents(event.target.value)} rows={3} placeholder={"One per line\nIce starts eating the wings\nBathroom screaming aftermath\nFinal result"} className="editor-v2-input mt-1 resize-y" /><span className="mt-1 block normal-case leading-3 text-amber-200/60">These are hard requirements. The cut is blocked if one cannot be located and included.</span></label>
      <label className="block text-[9px] uppercase tracking-wide text-slate-500">Leave out <span className="normal-case text-slate-700">(optional)</span><textarea value={excludedTopics} onChange={(event) => setExcludedTopics(event.target.value)} rows={2} placeholder="One unwanted topic per line" className="editor-v2-input mt-1 resize-y" /></label>
      <div className="grid grid-cols-2 gap-2">
        <label className="text-[9px] uppercase tracking-wide text-slate-500">Target minutes<input type="number" min={3} max={90} value={targetMinutes} onChange={(event) => setTargetMinutes(Number(event.target.value))} className="editor-v2-input mt-1" /></label>
        <label className="text-[9px] uppercase tracking-wide text-slate-500">Max sections<input type="number" min={2} max={30} value={maxSections} onChange={(event) => setMaxSections(Number(event.target.value))} className="editor-v2-input mt-1" /></label>
      </div>
      <label className="flex items-center justify-between text-[9px] text-slate-400"><span className="flex items-center gap-1.5"><Captions className="h-3 w-3" /> Add editable speech captions</span><input type="checkbox" checked={captions} onChange={(event) => setCaptions(event.target.checked)} className="accent-amber-300" /></label>
      <button type="button" disabled={busy || !brief.trim()} onClick={() => void buildStoryCut()} className="flex w-full items-center justify-center gap-1.5 rounded bg-amber-300 px-2 py-2 text-[10px] font-bold text-slate-950 disabled:opacity-40">{busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />} Build new story cut</button>
      {message && <div className={cn("rounded border p-2 text-[9px] leading-4", /created|copied|saved/i.test(message) ? "border-emerald-300/20 bg-emerald-300/[0.06] text-emerald-200" : "border-rose-300/20 bg-rose-300/[0.06] text-rose-200")}>{message}</div>}
      {!plan?.transcript_path && <p className="text-[8px] leading-3 text-slate-600">A transcript is required. If analysis reports none, run the local pipeline on this source first.</p>}
    </section>

    {plan?.streamContext && <section className="space-y-2 rounded border border-sky-300/15 bg-sky-300/[0.035] p-2">
      <div className="flex items-center justify-between text-[9px] font-bold uppercase tracking-[0.14em] text-sky-200/70"><span className="flex items-center gap-1.5"><ListChecks className="h-3.5 w-3.5" /> Story contract</span><span>{formatStreamType(plan.streamContext.selectedType)} · {Math.round(plan.streamContext.confidence * 100)}%</span></div>
      <p className="text-[8px] leading-3 text-slate-500">Goal: {plan.streamContext.goal || "No explicit episode promise supplied."}</p>
      <div className="flex flex-wrap gap-1">{plan.streamContext.storyContract.map((item) => <span key={item} className="rounded border border-sky-300/10 bg-black/20 px-1.5 py-1 text-[7px] text-sky-100/65">{item}</span>)}</div>
      {plan.streamContext.requiredEvents.length > 0 && <div className="space-y-1 border-t border-white/5 pt-2">{plan.streamContext.requiredEvents.map((event) => <button key={event.query} type="button" disabled={!event.matched || event.sourceStart === null} onClick={() => event.sourceStart !== null && onSeek(event.sourceStart)} className={cn("flex w-full items-center gap-2 rounded border px-2 py-1.5 text-left", event.matched && event.included !== false ? "border-emerald-300/15 bg-emerald-300/[0.04]" : "border-rose-300/20 bg-rose-300/[0.05]")}><span className={cn("h-1.5 w-1.5 rounded-full", event.matched ? "bg-emerald-300" : "bg-rose-300")} /><span className="min-w-0 flex-1 truncate text-[8px] text-slate-300">{event.query}</span><span className="text-[7px] tabular-nums text-slate-600">{event.sourceStart === null ? "not found" : clock(event.sourceStart)}</span></button>)}</div>}
      <div className="max-h-28 space-y-1 overflow-y-auto border-t border-white/5 pt-2"><div className="text-[7px] font-bold uppercase tracking-wide text-slate-600">Source-wide segment map</div>{plan.streamContext.sourceSegments.map((segment) => <button key={segment.id} type="button" onClick={() => onSeek(segment.sourceStart)} className="flex w-full items-center gap-2 rounded px-1.5 py-1 text-left hover:bg-white/[0.04]"><span className="w-8 text-[7px] tabular-nums text-slate-600">{clock(segment.sourceStart)}</span><span className="min-w-0 flex-1 truncate text-[8px] text-slate-400">{segment.title}</span><Role role={segment.role} /></button>)}</div>
    </section>}

    {quality && <section className={cn("space-y-2 rounded border p-2", quality.grade === "ready" ? "border-emerald-300/20 bg-emerald-300/[0.04]" : quality.grade === "blocked" ? "border-rose-300/25 bg-rose-300/[0.05]" : "border-amber-300/25 bg-amber-300/[0.05]")}>
      <div className="flex items-center justify-between text-[9px] font-bold uppercase tracking-[0.14em]"><span className="flex items-center gap-1.5"><AlertTriangle className="h-3 w-3" /> Editorial QC</span><span>{quality.grade}</span></div>
      <p className="text-[8px] text-slate-500">{Math.round(quality.metrics.sourceCoverage * 100)}% source coverage · {(quality.metrics.selectedSeconds / 60).toFixed(1)} / {(quality.metrics.targetSeconds / 60).toFixed(1)} target minutes</p>
      {quality.warnings.map((warning) => <p key={warning.code} className="text-[8px] leading-3 text-amber-100/75">{warning.message}</p>)}
      {plan?.storyGraph?.mediaAnalysis && <p className="text-[8px] text-slate-600">Media pass: {plan.storyGraph.mediaAnalysis.status === "unavailable" ? "unavailable" : `${plan.storyGraph.mediaAnalysis.sceneCutCount ?? 0} strong visual changes · ${plan.storyGraph.mediaAnalysis.blackSegmentCount ?? 0} black ranges`}</p>}
    </section>}

    {narrativeArc.length > 0 && <section className="space-y-2">
      <div className="flex items-center justify-between text-[9px] font-bold uppercase tracking-[0.14em] text-slate-600"><span>Narrative arc</span><span>{narrativeArc.filter((stage) => stage.beatIds.length > 0).length}/5 supported</span></div>
      <div className="grid grid-cols-5 gap-1">{narrativeArc.map((stage, index) => <button key={stage.stage} type="button" disabled={!stage.beatIds.length} onClick={() => onSeek(stage.sourceStart)} title={stage.why} className={cn("relative min-w-0 rounded border px-1 py-2 text-center disabled:opacity-30", stage.stage === "climax" ? "border-rose-300/30 bg-rose-300/[0.08]" : stage.stage === "tension" ? "border-amber-300/25 bg-amber-300/[0.06]" : "border-white/10 bg-white/[0.025]")}><div className="text-[7px] font-black uppercase tracking-wide text-slate-400">{index + 1}</div><div className="mt-1 truncate text-[7px] font-semibold text-slate-300">{stage.label}</div><div className="mt-0.5 text-[7px] tabular-nums text-slate-600">{Math.round(stage.confidence * 100)}%</div></button>)}</div>
    </section>}

    {assembly && <section className="space-y-1.5 rounded border border-cyan-300/15 bg-cyan-300/[0.025] p-2">
      <div className="flex items-center justify-between text-[9px] font-bold uppercase tracking-[0.14em] text-cyan-200/60"><span>Assembled format</span><span>{clock(assembly.timelineDuration)}</span></div>
      <p className="text-[8px] leading-3 text-slate-600">{assembly.preludeCount} prelude clip{assembly.preludeCount === 1 ? "" : "s"} · intro {assembly.introIncluded ? "included" : "missing"} · outro {assembly.outroIncluded ? "included" : "missing"} · post-credit {assembly.postCreditIncluded ? "included" : "not used"}</p>
      <div className="flex flex-wrap gap-1">{assembly.segments.map((segment) => <button key={segment.itemId} type="button" onClick={() => onSeek(segment.timelineStart)} title={segment.why || segment.title} className="rounded border border-white/8 bg-black/20 px-1.5 py-1 text-[7px] uppercase text-slate-500 hover:border-cyan-300/25 hover:text-cyan-200">{segment.kind} · {clock(segment.timelineStart)}</button>)}</div>
    </section>}

    {chapters.length > 0 && <section className="space-y-1.5">
      <div className="flex items-center justify-between text-[9px] font-bold uppercase tracking-[0.14em] text-slate-600"><span>Chapters</span><button type="button" onClick={() => void copyChapters()} className="flex items-center gap-1 text-amber-300/70 hover:text-amber-200"><Copy className="h-3 w-3" /> Copy</button></div>
      <div className="max-h-44 space-y-1 overflow-y-auto">{chapters.map((chapter) => <div key={chapter.id} className="flex items-center gap-2 rounded border border-white/10 bg-white/[0.02] px-2 py-1.5 hover:border-amber-300/30 hover:bg-amber-300/[0.05]"><button type="button" onClick={() => onSeek(chapter.timelineStart)} className="flex shrink-0 items-center gap-1.5" title={`Seek to ${clock(chapter.timelineStart)}`}><Play className="h-3 w-3 text-amber-300" /><span className="w-9 text-[8px] tabular-nums text-slate-600">{clock(chapter.timelineStart)}</span></button><input value={chapter.title} onChange={(event) => onRenameChapter(chapter.id, event.target.value)} className="min-w-0 flex-1 bg-transparent text-[9px] text-slate-300 outline-none" aria-label={`Chapter title at ${clock(chapter.timelineStart)}`} /><Role role={chapter.role} /></div>)}</div>
    </section>}

    {flashbacks.length > 0 && <section className="space-y-1.5">
      <div className="flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-[0.14em] text-slate-600"><Rewind className="h-3 w-3" /> Flashback suggestions</div>
      {flashbacks.map((suggestion) => {
        const chapter = chapters.find((candidate) => candidate.beatIds.includes(suggestion.beatId));
        const added = appliedFlashbacks.has(suggestion.beatId);
        return <div key={suggestion.beatId} className="rounded border border-rose-300/15 bg-rose-300/[0.04] p-2"><div className="flex items-center gap-2"><span className="min-w-0 flex-1 truncate text-[9px] font-semibold text-rose-200">{suggestion.title}</span><span className="text-[8px] tabular-nums text-rose-200/60">{Math.round(suggestion.score * 100)}%</span></div><p className="mt-1 text-[8px] leading-3 text-slate-600">Source {clock(suggestion.sourceStart)}-{clock(suggestion.sourceEnd)} · {suggestion.why}</p><div className="mt-2 flex gap-1.5">{chapter && <button type="button" onClick={() => onSeek(chapter.timelineStart)} className="editor-v2-action flex-1 justify-center text-[8px]"><Play className="h-3 w-3" /> Review beat</button>}<button type="button" disabled={added} onClick={() => onAddFlashback(suggestion)} className="editor-v2-action flex-1 justify-center text-[8px] disabled:opacity-40"><Rewind className="h-3 w-3" /> {added ? "Added" : "Add to opening"}</button></div></div>;
      })}
    </section>}

    {youtubePackage && <section className="space-y-2 rounded border border-red-300/15 bg-red-300/[0.03] p-2">
      <div className="flex items-center justify-between text-[9px] font-bold uppercase tracking-[0.14em] text-slate-500"><span className="flex items-center gap-1.5"><Youtube className="h-3.5 w-3.5 text-red-300" /> YouTube package</span><button type="button" onClick={() => void copyYouTubePackage()} className="flex items-center gap-1 text-red-200/70 hover:text-red-100"><Copy className="h-3 w-3" /> Copy all</button></div>
      <label className="block text-[8px] uppercase tracking-wide text-slate-600">Title<input value={youtubePackage.title} maxLength={100} onChange={(event) => onUpdateYouTubePackage({ title: event.target.value })} className="editor-v2-input mt-1" /></label>
      <label className="block text-[8px] uppercase tracking-wide text-slate-600">Description<textarea value={youtubeDescription} maxLength={5000} rows={4} onChange={(event) => onUpdateYouTubePackage({ description: event.target.value })} className="editor-v2-input mt-1 resize-y" /></label>
      <div className="rounded border border-white/8 bg-black/20 p-2"><div className="text-[7px] font-bold uppercase tracking-wide text-slate-600">Current chapter block</div><pre className="mt-1 whitespace-pre-wrap text-[8px] leading-3 text-slate-400">{youtubePackage.chapterText || "No chapters"}</pre></div>
      <label className="block text-[8px] uppercase tracking-wide text-slate-600">Tags<input value={youtubePackage.tags.join(", ")} onChange={(event) => onUpdateYouTubePackage({ tags: event.target.value.split(",") })} className="editor-v2-input mt-1" /></label>
    </section>}

    {beats.length > 0 && <section className="space-y-1.5">
      <div className="flex items-center justify-between text-[9px] font-bold uppercase tracking-[0.14em] text-slate-600"><span>Source story beats</span><span>{selectedBeatIds.size}/{beats.length} selected</span></div>
      <div className="max-h-64 space-y-1 overflow-y-auto">{beats.map((beat) => <div key={beat.id} className={cn("rounded border p-2", selectedBeatIds.has(beat.id) ? ROLE_STYLE[beat.role] : "border-white/5 bg-black/20 text-slate-600")}><div className="flex items-center gap-1.5"><Clock3 className="h-3 w-3 shrink-0" /><span className="text-[8px] tabular-nums">{clock(beat.start)}</span><span className="min-w-0 flex-1 truncate text-[9px] font-semibold">{beat.title}</span><span className="text-[8px] tabular-nums">{Math.round(beat.score * 100)}%</span></div><p className="mt-1 line-clamp-2 text-[8px] leading-3 opacity-70">{beat.text}</p></div>)}</div>
    </section>}
  </div>;
}

function Role({ role }: { role: StoryBeatRole }) {
  return <span className={cn("shrink-0 rounded border px-1 py-0.5 text-[7px] font-bold uppercase", ROLE_STYLE[role])}>{role}</span>;
}

function BrandVideoField({ label, value, available, onChange, onChoose }: { label: string; value: string; available?: boolean; onChange: (value: string) => void; onChoose: () => void }) {
  return <label className="block text-[8px] uppercase tracking-wide text-slate-600"><span className="flex items-center justify-between"><span>{label}</span>{value && <span className={available === false ? "text-rose-300" : "text-emerald-300"}>{available === false ? "Missing" : "Ready"}</span>}</span><div className="mt-1 flex gap-1"><input value={value} onChange={(event) => onChange(event.target.value)} placeholder="Choose a local MP4" className="editor-v2-input min-w-0 flex-1" /><button type="button" onClick={onChoose} title={`Choose ${label.toLowerCase()}`} className="editor-v2-action shrink-0 px-2"><FolderOpen className="h-3 w-3" /></button></div></label>;
}

function lines(value: string) {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
}

function formatStreamType(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}
