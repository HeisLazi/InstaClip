import { useState } from "react";

import { CheckCircle2, Circle, ImagePlay, LayoutPanelTop, Link2Off, MonitorPlay, PictureInPicture, Scissors, ScanFace, ShieldCheck, TriangleAlert, UnfoldHorizontal, Unlink, Volume2 } from "lucide-react";

import { api } from "@/api/client";
import type { Bucket, TranscriptEditOperation, TranscriptEditReport, TrimSuggestion } from "@/api/client";
import { CompilationPanel, TemplatesPanel } from "@/editor-v2/WorkflowPanels";
import { StoryPanel } from "@/editor-v2/StoryPanel";
import { TranscriptPanel } from "@/editor-v2/TranscriptPanel";
import { buildYouTubePreflight, findItem, itemDuration, type Command, type CreativeTreatment, type EditorProjectV2, type LongformPlan, type TimelineItem, type TransitionKind } from "@/editor-v2/model";
import type { CompilationEntry, CompilationOptions, LayoutTemplate } from "@/editor-v2/useEditorProject";
import { cn } from "@/lib/utils";

export type InspectorTab = "edit" | "transcript" | "story" | "templates" | "compile" | "audio" | "export";

export function Inspector({
  project,
  tab,
  onTab,
  dispatch,
  detachAudio,
  rendering,
  renderedStem,
  onRender,
  sourceBucket,
  sourceStem,
  onApplyTemplate,
  onSuggestTrim,
  onAutoEdit,
  onBuildCompilation,
  onSeek,
  onOpenProject,
  onAddFlashback,
  onApplyTranscriptOps,
  onDetectCam,
  onExtend,
  onOpenLegacy,
  onError,
}: {
  project: EditorProjectV2;
  tab: InspectorTab;
  onTab: (tab: InspectorTab) => void;
  dispatch: (command: Command) => void;
  detachAudio: () => void;
  rendering: boolean;
  renderedStem: string | null;
  onRender: () => Promise<void>;
  sourceBucket: Bucket;
  sourceStem: string;
  onApplyTemplate: (template: LayoutTemplate) => void;
  onSuggestTrim: () => Promise<TrimSuggestion>;
  onAutoEdit: () => Promise<void>;
  onBuildCompilation: (entries: CompilationEntry[], options: CompilationOptions) => Promise<void>;
  onSeek: (time: number) => void;
  onOpenProject?: (projectId: string, name: string) => void;
  onAddFlashback: (suggestion: NonNullable<LongformPlan["flashbackSuggestions"]>[number]) => void;
  onApplyTranscriptOps: (ops: TranscriptEditOperation[]) => Promise<TranscriptEditReport>;
  onDetectCam?: (sourceTime?: number) => Promise<Awaited<ReturnType<typeof api.edit.v2.detectCam>>>;
  onExtend?: (before: number, after: number) => Promise<{ mode: string; granted: { before: number; after: number } }>;
  onOpenLegacy?: () => void;
  onError: (message: string) => void;
}) {
  const selectedId = project.selection.itemIds[0];
  const selected = selectedId ? findItem(project, selectedId) : undefined;

  return (
    <aside className="flex h-full min-h-0 flex-col border-l border-white/10 bg-[#11151a]">
      <div className={cn("grid h-9 shrink-0 border-b border-white/10 px-1", project.contentMode === "long_form" ? "grid-cols-7" : "grid-cols-6")}>
        {(["edit", "transcript", ...(project.contentMode === "long_form" ? ["story" as const] : []), "templates", "compile", "audio", "export"] as InspectorTab[]).map((value) => (
          <button key={value} type="button" onClick={() => onTab(value)} className={cn("relative flex-1 text-[9px] font-semibold capitalize text-slate-500 hover:text-slate-200", tab === value && "text-cyan-300 after:absolute after:inset-x-1 after:bottom-0 after:h-0.5 after:bg-cyan-400")}>{value}</button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {tab === "edit" && (!selected ? <EmptySelection /> : (
          <>
            <EditPanel project={project} item={selected.item} dispatch={dispatch} detachAudio={detachAudio} />
            {selected.item.video && (onDetectCam || onExtend) && (
              <SmartToolsPanel item={selected.item} dispatch={dispatch}
                onDetectCam={onDetectCam} onExtend={onExtend} />
            )}
          </>
        ))}
        {tab === "transcript" && <TranscriptPanel project={project} onSeek={onSeek} onApply={onApplyTranscriptOps} />}
        {tab === "story" && <StoryPanel project={project} onSeek={onSeek} onOpenProject={onOpenProject} onRenameChapter={(chapterId, title) => dispatch({ type: "SET_CHAPTER_TITLE", chapterId, title })} onAddFlashback={onAddFlashback} onUpdateYouTubePackage={(changes) => dispatch({ type: "SET_YOUTUBE_PACKAGE", changes })} />}
        {tab === "templates" && <TemplatesPanel project={project} fallbackBucket={sourceBucket} fallbackStem={sourceStem} onApply={onApplyTemplate} onSuggestTrim={onSuggestTrim} onAutoEdit={onAutoEdit} onOpenLegacy={onOpenLegacy} onError={onError} />}
        {tab === "compile" && <CompilationPanel onBuild={onBuildCompilation} onError={onError} />}
        {tab === "audio" && (!selected?.item.audio ? <div className="py-10 text-center text-[10px] text-slate-600"><Volume2 className="mx-auto mb-2 h-6 w-6" />Select a clip with audio</div> : <AudioPanel item={selected.item} dispatch={dispatch} />)}
        {tab === "export" && <ExportPanel project={project} dispatch={dispatch} rendering={rendering} renderedStem={renderedStem} onRender={onRender} />}
      </div>
    </aside>
  );
}

function EditPanel({ project, item, dispatch, detachAudio }: { project: EditorProjectV2; item: TimelineItem; dispatch: (command: Command) => void; detachAudio: () => void }) {
  const asset = project.assets[item.assetId];
  const video = item.video;
  if (item.caption) return <CaptionPanel item={item} dispatch={dispatch} />;
  const track = project.tracks.find((candidate) => candidate.id === item.trackId);
  const videoItems = track?.items.filter((candidate) => candidate.video).sort((left, right) => left.timelineStart - right.timelineStart) ?? [];
  const itemIndex = videoItems.findIndex((candidate) => candidate.id === item.id);
  const previous = itemIndex > 0 ? videoItems[itemIndex - 1] : null;
  const transition = previous ? (project.transitions ?? []).find((candidate) => candidate.fromItemId === previous.id && candidate.toItemId === item.id) : undefined;
  return (
    <div className="space-y-4">
      <Section title="Clip">
        <Readout label="Media" value={asset?.name ?? "Missing"} />
        <Readout label="Duration" value={`${itemDuration(item).toFixed(2)} sec`} />
        <Field label="Speed" suffix="x"><input type="number" min={0.25} max={4} step={0.05} value={item.speed} onChange={(event) => dispatch({ type: "SET_ITEM_SPEED", itemId: item.id, speed: Number(event.target.value) })} /></Field>
        <label className="flex items-center justify-between text-[10px] text-slate-400"><span>Enabled</span><input type="checkbox" checked={item.enabled} onChange={(event) => dispatch({ type: "SET_ITEM_ENABLED", itemId: item.id, enabled: event.target.checked })} className="accent-cyan-400" /></label>
      </Section>
      {video && <Section title="Transform">
        <div className="grid grid-cols-2 gap-2">
          {(["x", "y", "width", "height", "rotation", "opacity"] as const).map((key) => <NumberField key={key} label={key} value={video[key]} step={key === "opacity" ? 0.05 : 1} onChange={(value) => dispatch({ type: "SET_ITEM_TRANSFORM", itemId: item.id, transform: { [key]: value } })} />)}
        </div>
        <label className="block text-[9px] uppercase tracking-wide text-slate-600">Fit<select value={video.fit} onChange={(event) => dispatch({ type: "SET_ITEM_TRANSFORM", itemId: item.id, transform: { fit: event.target.value as "contain" | "cover" | "stretch" } })} className="editor-v2-input mt-1"><option value="contain">Contain</option><option value="cover">Cover</option><option value="stretch">Stretch</option></select></label>
      </Section>}
      {video && <CreativeTreatmentPanel project={project} item={item} dispatch={dispatch} />}
      {video && previous && <Section title="Transition from previous clip">
        <label className="block text-[9px] uppercase tracking-wide text-slate-600">Style<select value={transition?.kind ?? ""} onChange={(event) => dispatch({ type: "SET_TRANSITION", fromItemId: previous.id, toItemId: item.id, kind: (event.target.value || null) as TransitionKind | null, duration: transition?.duration ?? 0.6 })} className="editor-v2-input mt-1"><option value="">Hard cut</option><option value="fade_black">Fade through black</option><option value="fade_white">Fade through white</option><option value="mix">Mix / crossfade</option></select></label>
        {transition && <RangeField label="Duration" value={transition.duration} min={0.1} max={3} step={0.05} onChange={(duration) => dispatch({ type: "SET_TRANSITION", fromItemId: previous.id, toItemId: item.id, kind: transition.kind, duration })} />}
        <p className="text-[9px] leading-relaxed text-slate-600">Mix overlaps the two clips. Color fades preserve the cut and fade through black or white.</p>
      </Section>}
      <Section title="Linked media">
        <div className="flex gap-2">
          {item.video && item.audio && <button type="button" onClick={detachAudio} className="editor-v2-action flex-1"><Link2Off className="h-3.5 w-3.5" /> Detach audio</button>}
          {item.linkedGroupId && <button type="button" onClick={() => dispatch({ type: "UNLINK_ITEMS", itemIds: [item.id] })} className="editor-v2-action flex-1"><Unlink className="h-3.5 w-3.5" /> Unlink</button>}
        </div>
      </Section>
    </div>
  );
}

function CaptionPanel({ item, dispatch }: { item: TimelineItem; dispatch: (command: Command) => void }) {
  const caption = item.caption!;
  const update = (changes: Partial<typeof caption>) => dispatch({ type: "SET_ITEM_CAPTION", itemId: item.id, caption: changes });
  return <div className="space-y-4">
    <Section title="Caption text">
      <textarea value={caption.text} onChange={(event) => update({ text: event.target.value })} rows={4} className="editor-v2-input resize-y" placeholder="Type caption text" />
      <Readout label="Duration" value={`${itemDuration(item).toFixed(2)} sec`} />
    </Section>
    <Section title="Caption style">
      <div className="grid grid-cols-3 gap-1.5">
        <button type="button" onClick={() => update({ text: caption.text.toUpperCase(), fontSize: 76, position: "bottom", backgroundOpacity: 0, strokeWidth: 6, bold: true, variant: "subtitle", animation: "none" })} className="editor-v2-action justify-center px-1 text-[8px]">Punch</button>
        <button type="button" onClick={() => update({ fontSize: 96, position: "center", backgroundOpacity: 0.72, strokeWidth: 4, bold: true, variant: "title", animation: "fade" })} className="editor-v2-action justify-center px-1 text-[8px]">Title card</button>
        <button type="button" onClick={() => update({ fontSize: 54, position: "bottom", backgroundOpacity: 0.78, strokeWidth: 2, bold: true, variant: "lower_third", animation: "fade" })} className="editor-v2-action justify-center px-1 text-[8px]">Lower third</button>
      </div>
      <RangeField label="Font size" value={caption.fontSize} min={12} max={240} step={1} onChange={(fontSize) => update({ fontSize })} />
      <label className="block text-[9px] uppercase tracking-wide text-slate-600">Position<select value={caption.position} onChange={(event) => update({ position: event.target.value as typeof caption.position })} className="editor-v2-input mt-1"><option value="top">Top</option><option value="center">Center</option><option value="bottom">Bottom</option></select></label>
      <label className="block text-[9px] uppercase tracking-wide text-slate-600">Animation<select value={caption.animation ?? "none"} onChange={(event) => update({ animation: event.target.value as "none" | "fade" })} className="editor-v2-input mt-1"><option value="none">None</option><option value="fade">Fade in/out</option></select></label>
      <div className="grid grid-cols-2 gap-2"><ColorField label="Text" value={caption.color} onChange={(color) => update({ color })} /><ColorField label="Background" value={caption.backgroundColor} onChange={(backgroundColor) => update({ backgroundColor })} /><ColorField label="Outline" value={caption.strokeColor} onChange={(strokeColor) => update({ strokeColor })} /><NumberField label="Outline px" value={caption.strokeWidth} step={1} onChange={(strokeWidth) => update({ strokeWidth })} /></div>
      <RangeField label="Background opacity" value={caption.backgroundOpacity} min={0} max={1} step={0.05} onChange={(backgroundOpacity) => update({ backgroundOpacity })} />
      <label className="flex items-center justify-between text-[10px] text-slate-400"><span>Bold text</span><input type="checkbox" checked={caption.bold} onChange={(event) => update({ bold: event.target.checked })} className="accent-amber-300" /></label>
    </Section>
  </div>;
}

function AudioPanel({ item, dispatch }: { item: TimelineItem; dispatch: (command: Command) => void }) {
  const audio = item.audio;
  if (!audio) return null;
  return <div className="space-y-4"><Section title="Clip audio">
    <RangeField label="Volume" value={audio.volume} min={0} max={2} step={0.01} onChange={(volume) => dispatch({ type: "SET_ITEM_AUDIO", itemId: item.id, audio: { volume } })} />
    <RangeField label="Pan" value={audio.pan} min={-1} max={1} step={0.01} onChange={(pan) => dispatch({ type: "SET_ITEM_AUDIO", itemId: item.id, audio: { pan } })} />
    <NumberField label="Fade in" value={audio.fadeIn} step={0.05} onChange={(fadeIn) => dispatch({ type: "SET_ITEM_AUDIO", itemId: item.id, audio: { fadeIn: Math.max(0, fadeIn) } })} />
    <NumberField label="Fade out" value={audio.fadeOut} step={0.05} onChange={(fadeOut) => dispatch({ type: "SET_ITEM_AUDIO", itemId: item.id, audio: { fadeOut: Math.max(0, fadeOut) } })} />
    <label className="flex items-center justify-between text-[10px] text-slate-400"><span>Normalize loudness</span><input type="checkbox" checked={audio.normalize} onChange={(event) => dispatch({ type: "SET_ITEM_AUDIO", itemId: item.id, audio: { normalize: event.target.checked } })} className="accent-cyan-400" /></label>
  </Section><p className="text-[9px] leading-relaxed text-slate-600">Audio clips remain independent layers. Drop multiple booms or reactions at the same time to hear and render them together.</p></div>;
}

function ExportPanel({ project, dispatch, rendering, renderedStem, onRender }: { project: EditorProjectV2; dispatch: (command: Command) => void; rendering: boolean; renderedStem: string | null; onRender: () => Promise<void> }) {
  const settings = project.export;
  const preflight = buildYouTubePreflight(project);
  const youtube = project.longformPlan?.youtubePackage;
  return <div className="space-y-4"><Section title="Output">
    <label className="block text-[9px] uppercase tracking-wide text-slate-600">File name<input value={settings.outputName} onChange={(event) => dispatch({ type: "SET_EXPORT", export: { outputName: event.target.value } })} className="editor-v2-input mt-1" /></label>
    <div className="grid grid-cols-2 gap-2"><NumberField label="Width" value={settings.width} step={2} onChange={(width) => dispatch({ type: "SET_EXPORT", export: { width } })} /><NumberField label="Height" value={settings.height} step={2} onChange={(height) => dispatch({ type: "SET_EXPORT", export: { height } })} /></div>
    <div className="grid grid-cols-2 gap-2"><NumberField label="FPS" value={settings.fps} step={1} onChange={(fps) => dispatch({ type: "SET_EXPORT", export: { fps } })} /><label className="text-[9px] uppercase tracking-wide text-slate-600">Quality<select value={settings.quality} onChange={(event) => dispatch({ type: "SET_EXPORT", export: { quality: event.target.value as "draft" | "standard" | "high" } })} className="editor-v2-input mt-1"><option value="draft">Draft</option><option value="standard">Standard</option><option value="high">High</option></select></label></div>
    <label className="text-[9px] uppercase tracking-wide text-slate-600">Range<select value={settings.range} onChange={(event) => dispatch({ type: "SET_EXPORT", export: { range: event.target.value as "full" | "in-out" } })} className="editor-v2-input mt-1"><option value="full">Full timeline</option><option value="in-out">In / out points</option></select></label>
  </Section>
  {youtube && <Section title="YouTube final review">
    <div className={cn("rounded border p-2 text-[9px]", preflight.ready ? "border-emerald-300/25 bg-emerald-300/[0.06] text-emerald-200" : "border-amber-300/25 bg-amber-300/[0.06] text-amber-100")}><div className="flex items-center gap-1.5 font-bold uppercase tracking-wide">{preflight.ready ? <ShieldCheck className="h-3.5 w-3.5" /> : <TriangleAlert className="h-3.5 w-3.5" />}{preflight.ready ? "Ready for final export" : "Review required"}</div><p className="mt-1 text-slate-500">Automatic checks use the current timeline. Manual checks remain explicit creator sign-off.</p></div>
    <div className="space-y-1">{preflight.checks.map((check) => check.kind === "manual" && check.reviewKey ? <button key={check.id} type="button" onClick={() => dispatch({ type: "SET_YOUTUBE_REVIEW", changes: { [check.reviewKey!]: check.status !== "pass" } })} className="flex w-full items-start gap-2 rounded border border-white/8 bg-black/15 p-2 text-left hover:border-white/15">{check.status === "pass" ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-300" /> : <Circle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-600" />}<span><span className="block text-[9px] text-slate-300">{check.label}</span><span className="block text-[8px] leading-3 text-slate-600">{check.detail}</span></span></button> : <div key={check.id} className="flex items-start gap-2 rounded border border-white/8 bg-black/15 p-2">{check.status === "pass" ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-300" /> : <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-rose-300" />}<span><span className="block text-[9px] text-slate-300">{check.label}</span><span className="block text-[8px] leading-3 text-slate-600">{check.detail}</span></span></div>)}</div>
    <label className="block text-[9px] uppercase tracking-wide text-slate-600">Review notes<textarea value={youtube.review?.notes ?? ""} onChange={(event) => dispatch({ type: "SET_YOUTUBE_REVIEW", changes: { notes: event.target.value } })} rows={3} className="editor-v2-input mt-1 resize-y" placeholder="Rights source, audio fix, thumbnail direction..." /></label>
  </Section>}
  <button type="button" disabled={rendering} onClick={() => void onRender()} className={cn("flex w-full items-center justify-center gap-2 rounded px-3 py-2 text-xs font-bold text-slate-950 disabled:opacity-50", preflight.ready ? "bg-emerald-300 hover:bg-emerald-200" : "bg-cyan-400 hover:bg-cyan-300")}><Scissors className="h-4 w-4" />{rendering ? "Rendering..." : preflight.ready ? "Render final timeline" : "Render review copy"}</button>
  {renderedStem && <div className="overflow-hidden rounded border border-emerald-400/30 bg-emerald-400/5"><video controls src={api.edit.videoUrl(renderedStem)} className="aspect-[9/16] max-h-52 w-full bg-black object-contain" /><div className="truncate px-2 py-1.5 text-[9px] text-emerald-300">Rendered: {renderedStem}.mp4</div></div>}
  </div>;
}

function CreativeTreatmentPanel({ project, item, dispatch }: { project: EditorProjectV2; item: TimelineItem; dispatch: (command: Command) => void }) {
  const overlayTrack = [...project.tracks]
    .filter((track) => track.kind === "video" && !track.locked)
    .sort((left, right) => right.order - left.order)[0];
  const treatments: Array<{ id: CreativeTreatment; label: string; detail: string; icon: React.ReactNode }> = [
    { id: "cutaway", label: "B-roll cutaway", detail: "Full-frame cover, source audio muted", icon: <MonitorPlay className="h-3.5 w-3.5" /> },
    { id: "meme", label: "Meme insert", detail: "Centered contain frame, audio preserved", icon: <ImagePlay className="h-3.5 w-3.5" /> },
    { id: "pip", label: "Picture in picture", detail: "Upper-right overlay, source audio muted", icon: <PictureInPicture className="h-3.5 w-3.5" /> },
    { id: "chat", label: "Chat panel", detail: "Left-side vertical overlay", icon: <LayoutPanelTop className="h-3.5 w-3.5" /> },
  ];
  return <Section title="Creative treatment"><div className="grid grid-cols-2 gap-1.5">{treatments.map((treatment) => <button key={treatment.id} type="button" onClick={() => dispatch({ type: "APPLY_CREATIVE_TREATMENT", itemId: item.id, treatment: treatment.id, targetTrackId: overlayTrack?.id })} className="rounded border border-white/10 bg-white/[0.025] p-2 text-left hover:border-cyan-300/30 hover:bg-cyan-300/[0.05]"><span className="flex items-center gap-1.5 text-[8px] font-semibold text-slate-300">{treatment.icon}{treatment.label}</span><span className="mt-1 block text-[7px] leading-3 text-slate-600">{treatment.detail}</span></button>)}</div><p className="text-[8px] leading-3 text-slate-600">Treatments move the item to the highest unlocked video track so it layers above the main edit.</p></Section>;
}

function EmptySelection() { return <div className="py-10 text-center text-[10px] text-slate-600"><Scissors className="mx-auto mb-2 h-6 w-6" />Select a timeline clip to edit it</div>; }
function Section({ title, children }: { title: string; children: React.ReactNode }) { return <section className="space-y-2.5"><h3 className="border-b border-white/10 pb-1.5 text-[9px] font-bold uppercase tracking-[0.16em] text-slate-500">{title}</h3>{children}</section>; }
function Readout({ label, value }: { label: string; value: string }) { return <div className="flex justify-between gap-2 text-[10px]"><span className="text-slate-600">{label}</span><span className="truncate text-slate-300">{value}</span></div>; }
function Field({ label, suffix, children }: { label: string; suffix?: string; children: React.ReactNode }) { return <label className="grid grid-cols-[1fr_72px_auto] items-center gap-1 text-[10px] text-slate-500"><span>{label}</span><span className="[&_input]:block [&_input]:h-7 [&_input]:w-full [&_input]:rounded [&_input]:border [&_input]:border-white/10 [&_input]:bg-black/30 [&_input]:px-2 [&_input]:text-slate-200 [&_input]:outline-none">{children}</span><span>{suffix}</span></label>; }
function NumberField({ label, value, step, onChange }: { label: string; value: number; step: number; onChange: (value: number) => void }) { return <label className="text-[9px] uppercase tracking-wide text-slate-600">{label}<input type="number" value={Number.isFinite(value) ? value : 0} step={step} onChange={(event) => onChange(Number(event.target.value))} className="editor-v2-input mt-1" /></label>; }
function ColorField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) { return <label className="text-[9px] uppercase tracking-wide text-slate-600">{label}<span className="mt-1 flex h-8 items-center gap-2 rounded border border-white/10 bg-black/30 px-2"><input type="color" value={value} onChange={(event) => onChange(event.target.value)} className="h-5 w-6 border-0 bg-transparent p-0" /><span className="truncate text-[9px] normal-case text-slate-400">{value}</span></span></label>; }
function RangeField({ label, value, min, max, step, onChange }: { label: string; value: number; min: number; max: number; step: number; onChange: (value: number) => void }) { return <label className="block text-[9px] uppercase tracking-wide text-slate-600"><span className="flex justify-between"><span>{label}</span><span className="tabular-nums text-slate-400">{value.toFixed(2)}</span></span><input type="range" value={value} min={min} max={max} step={step} onChange={(event) => onChange(Number(event.target.value))} className="mt-1 w-full accent-cyan-400" /></label>; }

function SmartToolsPanel({ item, dispatch, onDetectCam, onExtend }: {
  item: TimelineItem;
  dispatch: (command: Command) => void;
  onDetectCam?: (sourceTime?: number) => Promise<Awaited<ReturnType<typeof api.edit.v2.detectCam>>>;
  onExtend?: (before: number, after: number) => Promise<{ mode: string; granted: { before: number; after: number } }>;
}) {
  const [busy, setBusy] = useState<"cam" | "extend" | null>(null);
  const [note, setNote] = useState("");
  const [cam, setCam] = useState<Awaited<ReturnType<typeof api.edit.v2.detectCam>> | null>(null);
  const [before, setBefore] = useState(5);
  const [after, setAfter] = useState(5);

  async function findCam() {
    if (!onDetectCam) return;
    setBusy("cam"); setNote(""); setCam(null);
    try {
      const mid = (item.sourceIn + item.sourceOut) / 2;
      const result = await onDetectCam(mid);
      if (!result.found) { setNote(result.detail ?? "No face found — seek to a moment where your cam is visible."); return; }
      setCam(result);
      setNote(result.identity
        ? `Found YOUR cam (match ${(result.identity_score ?? 0).toFixed(2)})`
        : "Found a face (enroll your photos for identity matching)");
    } catch { /* error surfaced by the hook */ } finally { setBusy(null); }
  }

  function applyCrop(box?: [number, number, number, number]) {
    if (!box) return;
    dispatch({ type: "SET_ITEM_TRANSFORM", itemId: item.id, transform: { crop: box, fit: "cover" } });
    setNote("Crop applied — adjust in the preview if needed.");
  }

  async function extend() {
    if (!onExtend) return;
    setBusy("extend"); setNote("");
    try {
      const report = await onExtend(before, after);
      setNote(`Extended -${report.granted.before}s / +${report.granted.after}s (${report.mode === "recut_from_vod" ? "re-cut from the stream" : "within the clip"})`);
    } catch { /* surfaced by the hook */ } finally { setBusy(null); }
  }

  return (
    <div className="mt-4 space-y-3 rounded-lg border border-cyan-400/20 bg-cyan-400/5 p-3">
      <div className="text-[9px] font-semibold uppercase tracking-[0.14em] text-cyan-300">Smart tools</div>
      {onDetectCam && (
        <div className="space-y-2">
          <button type="button" onClick={findCam} disabled={busy !== null}
            className="flex w-full items-center justify-center gap-2 rounded border border-cyan-400/30 bg-cyan-400/10 py-2 text-[10px] font-semibold text-cyan-200 hover:bg-cyan-400/20 disabled:opacity-50">
            <ScanFace className="h-3.5 w-3.5" />{busy === "cam" ? "Scanning…" : "Find my cam"}
          </button>
          {cam?.found && (
            <div className="grid grid-cols-2 gap-2">
              <button type="button" onClick={() => applyCrop(cam.cam_box)}
                className="rounded border border-white/10 bg-black/30 py-1.5 text-[10px] text-slate-200 hover:bg-white/10">Crop to cam</button>
              <button type="button" onClick={() => applyCrop(cam.crop_box)}
                className="rounded border border-white/10 bg-black/30 py-1.5 text-[10px] text-slate-200 hover:bg-white/10">9:16 face crop</button>
            </div>
          )}
        </div>
      )}
      {onExtend && (
        <div className="space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <NumberField label="Extend before (s)" value={before} step={1} onChange={setBefore} />
            <NumberField label="Extend after (s)" value={after} step={1} onChange={setAfter} />
          </div>
          <button type="button" onClick={extend} disabled={busy !== null || (before <= 0 && after <= 0)}
            className="flex w-full items-center justify-center gap-2 rounded border border-cyan-400/30 bg-cyan-400/10 py-2 text-[10px] font-semibold text-cyan-200 hover:bg-cyan-400/20 disabled:opacity-50">
            <UnfoldHorizontal className="h-3.5 w-3.5" />{busy === "extend" ? "Extending…" : "Extend clip"}
          </button>
        </div>
      )}
      {note && <div className="text-[10px] text-slate-400">{note}</div>}
    </div>
  );
}
