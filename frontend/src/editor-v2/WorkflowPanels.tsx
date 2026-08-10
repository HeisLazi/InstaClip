import { useEffect, useMemo, useState } from "react";
import { Check, Film, Loader2, Plus, Save, Sparkles, Trash2, Wand2 } from "lucide-react";

import { api, type Bucket, type ClipInfo, type EditorPreset, type TrimSuggestion } from "@/api/client";
import { allItems, findItem, type EditorProjectV2 } from "@/editor-v2/model";
import type { CompilationEntry, CompilationOptions, LayoutTemplate } from "@/editor-v2/useEditorProject";
import { cn } from "@/lib/utils";

export function TemplatesPanel({
  project,
  fallbackBucket,
  fallbackStem,
  onApply,
  onSuggestTrim,
  onAutoEdit,
  onOpenLegacy,
  onError,
}: {
  project: EditorProjectV2;
  fallbackBucket: Bucket;
  fallbackStem: string;
  onApply: (template: LayoutTemplate) => void;
  onSuggestTrim: () => Promise<TrimSuggestion>;
  onAutoEdit: () => Promise<void>;
  onOpenLegacy?: () => void;
  onError: (message: string) => void;
}) {
  const rawSelected = project.selection.itemIds[0] ? findItem(project, project.selection.itemIds[0])?.item : undefined;
  const selected = rawSelected && !rawSelected.audio && rawSelected.linkedGroupId
    ? allItems(project).find((candidate) => candidate.id !== rawSelected.id && candidate.assetId === rawSelected.assetId && candidate.linkedGroupId === rawSelected.linkedGroupId && candidate.video && candidate.audio) ?? rawSelected
    : rawSelected;
  const asset = selected ? project.assets[selected.assetId] : undefined;
  const templateBucket = asset?.bucket ?? fallbackBucket;
  const templateStem = asset?.stem ?? fallbackStem;
  const supportsSourceTools = asset?.origin === "source" || asset?.origin === "gallery";
  const [templates, setTemplates] = useState<LayoutTemplate[]>([]);
  const [presets, setPresets] = useState<EditorPreset[]>([]);
  const [presetName, setPresetName] = useState("");
  const [busy, setBusy] = useState<"trim" | "auto" | "preset" | null>(null);
  const [message, setMessage] = useState("");

  async function refresh() {
    if (!templateStem) return;
    const [builtIn, custom] = await Promise.all([
      api.edit.templates(templateBucket, templateStem),
      api.edit.presets(templateBucket, templateStem),
    ]);
    setTemplates(Object.entries(builtIn.templates).map(([id, value]) => ({ id, ...(value as LayoutTemplate) })));
    setPresets(custom.presets);
  }

  useEffect(() => {
    void refresh().catch((error) => onError(error instanceof Error ? error.message : String(error)));
    // The source identity is sufficient; callbacks intentionally do not trigger reloads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templateBucket, templateStem]);

  async function suggest() {
    setBusy("trim");
    try {
      const result = await onSuggestTrim();
      setMessage(`${result.reason} (${Math.round(result.confidence * 100)}%)`);
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(null);
    }
  }

  async function autoEdit() {
    setBusy("auto");
    try {
      await onAutoEdit();
      setMessage("Auto Edit rendered and added the result to the timeline.");
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(null);
    }
  }

  function currentSpec(): LayoutTemplate {
    if (!selected?.video) throw new Error("Select a video clip first");
    const companion = selected.linkedGroupId
      ? allItems(project).find((candidate) => candidate.id !== selected.id && candidate.assetId === selected.assetId && candidate.linkedGroupId === selected.linkedGroupId && candidate.video && !candidate.audio)
      : undefined;
    const volume = selected.audio?.volume ?? 1;
    if (companion?.video) {
      const fullcam = (selected.video.blur ?? 0) > 0;
      return {
        layout: fullcam ? "fullcam" : "reaction",
        cam_box: companion.video.crop ?? undefined,
        content_box: fullcam ? undefined : selected.video.crop ?? undefined,
        audio_normalize: selected.audio?.normalize ?? false,
        audio_boost_db: volume > 0 ? 20 * Math.log10(volume) : -24,
      };
    }
    return {
      layout: selected.video.crop ? "crop" : "passthrough",
      crop_box: selected.video.crop ?? undefined,
      audio_normalize: selected.audio?.normalize ?? false,
      audio_boost_db: volume > 0 ? 20 * Math.log10(volume) : -24,
    };
  }

  async function savePreset() {
    if (!presetName.trim()) return;
    setBusy("preset");
    try {
      await api.edit.savePreset(templateBucket, templateStem, presetName.trim(), currentSpec());
      setPresetName("");
      await refresh();
      setMessage("Custom preset saved.");
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(null);
    }
  }

  async function deletePreset(id: string) {
    try {
      await api.edit.deletePreset(id);
      setPresets((current) => current.filter((preset) => preset.id !== id));
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    }
  }

  return <div className="space-y-4">
    <PanelTitle icon={<Sparkles />} title="Templates" detail="Apply layouts to the selected timeline clip" />
    {!selected?.video && <Hint>Select a video clip on the timeline first.</Hint>}
    {onOpenLegacy && (
      /* The legacy region editor is where cam/content boxes are DRAWN on the
         source with a live 9:16 preview — templates apply those regions, so it
         belongs at the top of this tab (Lazarus 2026-07-06). */
      <button type="button" onClick={onOpenLegacy}
        className="flex w-full items-center justify-between rounded-lg border border-fuchsia-400/30 bg-fuchsia-400/10 px-3 py-2.5 text-left text-[10px] font-semibold text-fuchsia-200 hover:bg-fuchsia-400/20">
        <span>Region editor — draw cam / content boxes with live 9:16 preview</span>
        <Plus className="h-3.5 w-3.5" />
      </button>
    )}
    <div className="grid grid-cols-1 gap-1.5">
      {[...templates, { id: "passthrough", label: "Original frame", layout: "passthrough" as const }].map((template) => (
        <button key={template.id ?? template.label} type="button" disabled={!selected?.video} onClick={() => onApply(template)} className="flex items-center justify-between rounded border border-cyan-400/20 bg-cyan-400/[0.06] px-2.5 py-2 text-left text-[10px] text-cyan-200 hover:border-cyan-300/50 hover:bg-cyan-400/10 disabled:opacity-35"><span>{template.label ?? template.layout}</span><Plus className="h-3 w-3" /></button>
      ))}
    </div>
    <Hint>Layout transition: split the clip at the playhead, select either segment, then apply a different template.</Hint>
    {presets.length > 0 && <section className="space-y-1.5"><div className="text-[9px] font-bold uppercase tracking-[0.14em] text-slate-600">Custom presets</div>{presets.map((preset) => <div key={preset.id} className="flex overflow-hidden rounded border border-amber-300/25 bg-amber-300/[0.06]"><button type="button" onClick={() => onApply(preset)} className="min-w-0 flex-1 truncate px-2 py-1.5 text-left text-[9px] text-amber-200 hover:bg-amber-300/10">{preset.label}</button><button type="button" onClick={() => void deletePreset(preset.id)} className="border-l border-amber-300/20 px-2 text-amber-300/60 hover:text-rose-300" aria-label={`Delete ${preset.label}`}><Trash2 className="h-3 w-3" /></button></div>)}</section>}
    <div className="flex gap-1.5"><input value={presetName} onChange={(event) => setPresetName(event.target.value)} placeholder="Clip Room + chat" className="editor-v2-input min-w-0 flex-1" /><button type="button" disabled={!supportsSourceTools || !presetName.trim() || busy === "preset"} onClick={() => void savePreset()} className="editor-v2-action shrink-0"><Save className="h-3 w-3" /> Save</button></div>
    <section className="space-y-2 border-t border-white/10 pt-3">
      <div className="text-[9px] font-bold uppercase tracking-[0.14em] text-slate-600">AI helpers</div>
      <button type="button" disabled={!supportsSourceTools || busy !== null} onClick={() => void suggest()} className="editor-v2-action w-full py-2">{busy === "trim" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />} Suggest payoff trim</button>
      <button type="button" disabled={!supportsSourceTools || busy !== null} onClick={() => void autoEdit()} className="editor-v2-action w-full py-2">{busy === "auto" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wand2 className="h-3.5 w-3.5" />} Auto Edit and add result</button>
      {!supportsSourceTools && <Hint>AI trim and saved layouts require a Gallery clip, not imported media.</Hint>}
      {message && <div className="rounded border border-emerald-400/20 bg-emerald-400/[0.06] p-2 text-[9px] leading-4 text-emerald-300">{message}</div>}
    </section>
  </div>;
}

export function CompilationPanel({
  onBuild,
  onError,
}: {
  onBuild: (entries: CompilationEntry[], options: CompilationOptions) => Promise<void>;
  onError: (message: string) => void;
}) {
  const [candidates, setCandidates] = useState<ClipInfo[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [sounds, setSounds] = useState<Array<{ name: string; duration: number }>>([]);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState("");
  const [tighten, setTighten] = useState(true);
  const [replacePrimary, setReplacePrimary] = useState(true);
  const [transition, setTransition] = useState(true);
  const [transitionSound, setTransitionSound] = useState("");
  const [transitionDuration, setTransitionDuration] = useState(0.8);

  useEffect(() => {
    api.edit.sounds().then((result) => {
      const ordered = [...result.sounds].sort((left, right) => left.name.localeCompare(right.name));
      setSounds(ordered);
      setTransitionSound(ordered.find((sound) => /compil|transition/i.test(sound.name))?.name ?? ordered[0]?.name ?? "");
    }).catch(() => undefined);
  }, []);

  const key = (clip: Pick<ClipInfo, "bucket" | "stem">) => `${clip.bucket}:${clip.stem}`;

  async function load(mode: "keepers" | "suggested") {
    setLoading(true);
    setProgress("Loading candidates...");
    try {
      const positivesPromise = api.clips.list("positives", { limit: 5000, minDuration: 4, sortBy: "score" });
      const lists = mode === "suggested"
        ? await Promise.all([positivesPromise, api.clips.list("output", { limit: 5000, minDuration: 4, sortBy: "score" })])
        : [await positivesPromise];
      const unique = new Map<string, ClipInfo>();
      lists.flat().forEach((clip) => unique.set(key(clip), clip));
      const ranked = [...unique.values()]
        .sort((left, right) => (right.score ?? right.quality_score ?? 0) - (left.score ?? left.quality_score ?? 0))
        .slice(0, 40);
      setCandidates(ranked);
      const defaultCount = mode === "suggested" ? 8 : Math.min(12, ranked.length);
      setSelected(new Set(ranked.slice(0, defaultCount).map(key)));
      setProgress(`${ranked.length} ranked candidates loaded.`);
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  }

  const chosen = useMemo(() => candidates.filter((clip) => selected.has(key(clip))), [candidates, selected]);

  async function build() {
    if (chosen.length === 0) return;
    setLoading(true);
    try {
      const entries: CompilationEntry[] = [];
      for (let index = 0; index < chosen.length; index += 1) {
        const clip = chosen[index];
        setProgress(tighten ? `Finding payoff ${index + 1}/${chosen.length}: ${clip.stem}` : `Preparing ${index + 1}/${chosen.length}`);
        let trim: CompilationEntry["trim"];
        if (tighten) {
          try {
            const suggestion = await api.edit.suggestTrim(clip.bucket, clip.stem);
            trim = { start: suggestion.start, end: suggestion.end };
          } catch {
            trim = undefined;
          }
        }
        entries.push({ bucket: clip.bucket, stem: clip.stem, trim });
      }
      await onBuild(entries, {
        replacePrimary,
        transitionDuration: transition ? transitionDuration : 0,
        transitionSound: transition ? transitionSound || undefined : undefined,
      });
      setProgress(`Added ${entries.length} clips to the timeline. Review, adjust, then Render in Export.`);
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  }

  return <div className="space-y-4">
    <PanelTitle icon={<Film />} title="Quick compilation" detail="Select ranked clips and build a real editable timeline" />
    <div className="grid grid-cols-2 gap-1.5"><button type="button" disabled={loading} onClick={() => void load("keepers")} className="editor-v2-action py-2">Good clips</button><button type="button" disabled={loading} onClick={() => void load("suggested")} className="editor-v2-action py-2"><Sparkles className="h-3 w-3" /> AI score picks</button></div>
    {candidates.length > 0 && <div className="max-h-48 space-y-1 overflow-y-auto rounded border border-white/10 bg-black/20 p-1">{candidates.map((clip) => {
      const id = key(clip);
      const active = selected.has(id);
      return <button key={id} type="button" onClick={() => setSelected((current) => { const next = new Set(current); active ? next.delete(id) : next.add(id); return next; })} className={cn("flex w-full items-center gap-2 rounded px-1.5 py-1.5 text-left", active ? "bg-cyan-400/10 text-cyan-200" : "text-slate-500 hover:bg-white/5")}><span className={cn("grid h-3.5 w-3.5 shrink-0 place-items-center rounded border", active ? "border-cyan-300 bg-cyan-300 text-slate-950" : "border-white/20")}>{active && <Check className="h-2.5 w-2.5" />}</span><span className="min-w-0 flex-1 truncate text-[9px]">{clip.stem}</span><span className="text-[8px] tabular-nums">{Math.round((clip.score ?? clip.quality_score ?? 0) * 100)}%</span></button>;
    })}</div>}
    <section className="space-y-2 rounded border border-white/10 bg-white/[0.02] p-2">
      <Toggle label="AI-tighten each clip to its payoff" checked={tighten} onChange={setTighten} />
      <Toggle label="Replace the current V1 storyline" checked={replacePrimary} onChange={setReplacePrimary} />
      <Toggle label="Black-screen gap between clips" checked={transition} onChange={setTransition} />
      {transition && <><label className="block text-[9px] text-slate-500">Compilation sound<select value={transitionSound} onChange={(event) => setTransitionSound(event.target.value)} className="editor-v2-input mt-1"><option value="">Silent gap</option>{sounds.map((sound) => <option key={sound.name} value={sound.name}>{sound.name}</option>)}</select></label><label className="block text-[9px] text-slate-500"><span className="flex justify-between"><span>Gap duration</span><span>{transitionDuration.toFixed(1)}s</span></span><input type="range" min={0.2} max={3} step={0.1} value={transitionDuration} onChange={(event) => setTransitionDuration(Number(event.target.value))} className="w-full accent-amber-400" /></label></>}
    </section>
    <button type="button" disabled={loading || chosen.length === 0} onClick={() => void build()} className="flex w-full items-center justify-center gap-1.5 rounded bg-amber-400 px-2 py-2 text-[10px] font-bold text-black disabled:opacity-40">{loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />} Build editable compilation ({chosen.length})</button>
    {progress && <div className="rounded border border-white/10 bg-black/20 p-2 text-[9px] leading-4 text-slate-400">{progress}</div>}
  </div>;
}

function PanelTitle({ icon, title, detail }: { icon: React.ReactNode; title: string; detail: string }) { return <div><div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400"><span className="[&_svg]:h-3.5 [&_svg]:w-3.5 text-cyan-400">{icon}</span>{title}</div><p className="mt-1 text-[9px] leading-4 text-slate-600">{detail}</p></div>; }
function Hint({ children }: { children: React.ReactNode }) { return <div className="rounded border border-white/10 bg-black/20 p-2 text-[9px] leading-4 text-slate-600">{children}</div>; }
function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (checked: boolean) => void }) { return <label className="flex items-center justify-between gap-2 text-[9px] text-slate-400"><span>{label}</span><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} className="accent-cyan-400" /></label>; }
