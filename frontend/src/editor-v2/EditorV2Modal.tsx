import { useEffect, useRef, useState } from "react";
import { Copy, Download, Loader2, Redo2, Rewind, Save, ScanLine, Scissors, Type, Undo2, X } from "lucide-react";

import { api, type Bucket, type LayoutScanResult, type TrimSuggestion } from "@/api/client";
import { Inspector, type InspectorTab } from "@/editor-v2/Inspector";
import { mapLayoutSwitches } from "@/editor-v2/layoutSwitches";
import { MediaBin } from "@/editor-v2/MediaBin";
import { Preview } from "@/editor-v2/Preview";
import { Timeline } from "@/editor-v2/Timeline";
import { allItems, findItem, itemEnd, projectDuration, type LongformPlan } from "@/editor-v2/model";
import type { AssetSource, CompilationEntry, CompilationOptions, LayoutTemplate } from "@/editor-v2/useEditorProject";
import { useEditorProject } from "@/editor-v2/useEditorProject";
import { cn } from "@/lib/utils";

type FlashbackSuggestion = NonNullable<LongformPlan["flashbackSuggestions"]>[number];

export function EditorV2Modal({
  bucket,
  stem,
  onClose,
  onLegacy,
  onRendered,
  localPath,
  projectId,
  candidateId,
  onOpenProject,
}: {
  bucket: Bucket;
  stem: string;
  onClose: () => void;
  onLegacy?: () => void;
  onRendered?: () => void;
  localPath?: string;
  projectId?: string;
  candidateId?: string;
  onOpenProject?: (projectId: string, name: string) => void;
}) {
  const editor = useEditorProject(bucket, stem, localPath, projectId, candidateId);
  const [playhead, setPlayhead] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [tab, setTab] = useState<InspectorTab>("edit");
  const [layoutScan, setLayoutScan] = useState<LayoutScanResult | null>(null);
  const [scanningLayout, setScanningLayout] = useState(false);
  const loadedProjectId = useRef<string | null>(null);
  const playheadRef = useRef(0);
  playheadRef.current = playhead;

  useEffect(() => {
    if (editor.project && loadedProjectId.current !== editor.project.id) {
      loadedProjectId.current = editor.project.id;
      setPlayhead(editor.project.playhead);
    }
  }, [editor.project]);



  useEffect(() => {
    if (!playing || !editor.project) return;
    const startedAt = performance.now();
    const startTime = playheadRef.current;
    const duration = projectDuration(editor.project);
    let frame = 0;
    const tick = (now: number) => {
      const next = startTime + (now - startedAt) / 1000;
      if (next >= duration) {
        setPlayhead(duration);
        setPlaying(false);
        return;
      }
      setPlayhead(next);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, editor.project?.id, editor.project?.revision]);

  useEffect(() => {
    function keyboard(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target?.matches("input, textarea, select, [contenteditable=true]")) return;
      const command = event.ctrlKey || event.metaKey;
      if (event.key === " ") {
        event.preventDefault();
        setPlaying((current) => !current);
      } else if (command && event.key.toLowerCase() === "z") {
        event.preventDefault();
        event.shiftKey ? editor.redo() : editor.undo();
      } else if (command && event.key.toLowerCase() === "y") {
        event.preventDefault();
        editor.redo();
      } else if (command && event.key.toLowerCase() === "c") {
        editor.dispatch({ type: "COPY_ITEMS", itemIds: editor.project?.selection.itemIds ?? [] });
      } else if (command && event.key.toLowerCase() === "x") {
        editor.dispatch({ type: "CUT_ITEMS", itemIds: editor.project?.selection.itemIds ?? [] });
      } else if (command && event.key.toLowerCase() === "v") {
        editor.dispatch({ type: "PASTE_ITEMS", time: playhead, targetTrackId: editor.project?.selection.focusedTrackId ?? undefined });
      } else if (command && event.key.toLowerCase() === "d") {
        editor.dispatch({ type: "DUPLICATE_ITEMS", itemIds: editor.project?.selection.itemIds ?? [] });
      } else if (event.key.toLowerCase() === "s") {
        editor.dispatch({ type: "SPLIT_ITEMS", itemIds: editor.project?.selection.itemIds ?? [], time: playhead });
      } else if (event.key === "Delete" || event.key === "Backspace") {
        editor.dispatch({ type: "DELETE_ITEMS", itemIds: editor.project?.selection.itemIds ?? [] });
      } else if (event.key.toLowerCase() === "i" && editor.project) {
        editor.dispatch({ type: "SET_IN_OUT", inPoint: playhead, outPoint: editor.project.outPoint });
      } else if (event.key.toLowerCase() === "o" && editor.project) {
        editor.dispatch({ type: "SET_IN_OUT", inPoint: editor.project.inPoint, outPoint: playhead });
      }
    }
    window.addEventListener("keydown", keyboard);
    return () => window.removeEventListener("keydown", keyboard);
  }, [editor, playhead]);

  async function quickAdd(source: AssetSource) {
    try {
      const asset = await editor.resolveAsset(source);
      const project = editor.project;
      if (!project) return;
      const kind = asset.kind === "audio" ? "audio" : "video";
      const matching = project.tracks.filter((candidate) => candidate.kind === kind && !candidate.locked);
      const track = asset.origin === "import" && kind === "video"
        ? [...matching].sort((left, right) => right.order - left.order)[0]
        : matching[0];
      if (!track) throw new Error(`Add an unlocked ${kind} track first`);
      await editor.addSourceToTrack({ type: "asset", asset }, track.id, playhead);
    } catch (error) {
      editor.setError(error instanceof Error ? error.message : String(error));
    }
  }

  async function dropSource(source: AssetSource, trackId: string, time: number) {
    try {
      await editor.addSourceToTrack(source, trackId, time);
    } catch (error) {
      editor.setError(error instanceof Error ? error.message : String(error));
    }
  }

  async function dropFiles(files: FileList, trackId: string, time: number) {
    try {
      for (const file of Array.from(files)) {
        const isAudio = file.type.startsWith("audio/") || /\.(wav|mp3|m4a|aac|ogg)$/i.test(file.name);
        if (isAudio) {
          const result = await api.edit.importSound(file);
          await editor.addSourceToTrack({ type: "sound", soundName: result.sound.name }, trackId, time);
        } else {
          const result = await api.edit.importMedia(file);
          await editor.addSourceToTrack({ type: "media", mediaId: result.asset.id }, trackId, time);
        }
      }
    } catch (error) {
      editor.setError(error instanceof Error ? error.message : String(error));
    }
  }

  async function render() {
    const result = await editor.render();
    if (!result) return;
    onRendered?.();
    // The public edition keeps rendered clips local; no external delivery is performed.
  }

  function selectedSource() {
    const project = editor.project;
    const selectedId = project?.selection.itemIds[0];
    const item = project && selectedId ? findItem(project, selectedId)?.item : undefined;
    const asset = item && project ? project.assets[item.assetId] : undefined;
    if (!project || !item || !asset || !asset.bucket || !asset.stem || !["source", "gallery"].includes(asset.origin)) {
      throw new Error("Select a Gallery video clip first");
    }
    return { project, item, asset };
  }

  function applyTemplate(template: LayoutTemplate) {
    try {
      editor.applyTemplate(template);
    } catch (error) {
      editor.setError(error instanceof Error ? error.message : String(error));
    }
  }

  async function suggestTrim(): Promise<TrimSuggestion> {
    const { item, asset } = selectedSource();
    const suggestion = await api.edit.suggestTrim(asset.bucket!, asset.stem!);
    const startDelta = suggestion.start - item.sourceIn;
    editor.dispatch({ type: "TRIM_ITEM", itemId: item.id, edge: "start", delta: startDelta });
    editor.dispatch({ type: "MOVE_ITEMS", itemIds: [item.id], deltaTime: -startDelta / item.speed });
    editor.dispatch({ type: "TRIM_ITEM", itemId: item.id, edge: "end", delta: suggestion.end - item.sourceOut });
    return suggestion;
  }

  async function autoEditSelected() {
    const { project, asset } = selectedSource();
    const result = await api.edit.auto(asset.bucket!, asset.stem!, {});
    const target = project.tracks.find((track) => track.kind === "video" && !track.locked);
    if (!target) throw new Error("Add an unlocked video track first");
    await editor.addSourceToTrack({ type: "clip", bucket: result.bucket as Bucket, stem: result.stem }, target.id, projectDuration(project) + 0.1);
  }

  async function buildCompilation(entries: CompilationEntry[], options: CompilationOptions) {
    await editor.buildCompilation(entries, options);
    setPlayhead(0);
    setPlaying(false);
  }

  async function scanLayouts() {
    if (!editor.project) return;
    setScanningLayout(true);
    try {
      const result = await api.edit.v2.layoutScan(editor.project.id);
      setLayoutScan(result);
      if (!result.has_layout_switch) editor.setError("Layout scan finished: no camera-layout switches were detected.");
    } catch (error) {
      editor.setError(error instanceof Error ? error.message : String(error));
    } finally {
      setScanningLayout(false);
    }
  }

  function layoutSwitchPoints() {
    return editor.project ? mapLayoutSwitches(editor.project, layoutScan) : [];
  }

  function splitAtLayoutSwitches() {
    const points = layoutSwitchPoints();
    if (points.length === 0) {
      editor.setError("Run layout scan first, then split at detected switches.");
      return;
    }
    [...points].sort((left, right) => right.time - left.time).forEach((point) => {
      editor.dispatch({ type: "SPLIT_ITEMS", itemIds: [point.itemId], time: point.time });
    });
  }

  function createFlashback() {
    const project = editor.project;
    const selectedId = project?.selection.itemIds[0];
    const selected = project && selectedId ? findItem(project, selectedId) : undefined;
    if (!project || !selected || selected.track.kind !== "video" || !selected.item.video) {
      editor.setError("Select the source video clip before creating a flashback");
      return;
    }
    if (project.inPoint === null || project.outPoint === null || project.outPoint <= project.inPoint) {
      editor.setError("Mark In and Mark Out around the later moment first");
      return;
    }
    try {
      const existingFlashbacks = allItems(project).filter((item) => item.video && item.editorRole === "flashback");
      const mainVideoStarts = allItems(project).filter((item) => item.video && item.editorRole !== "flashback").map((item) => item.timelineStart);
      const insertAt = existingFlashbacks.length > 0 && mainVideoStarts.length > 0 ? Math.min(...mainVideoStarts) : 0;
      editor.dispatch({
        type: "CREATE_FLASHBACK",
        itemId: selected.item.id,
        rangeStart: project.inPoint,
        rangeEnd: project.outPoint,
        insertAt,
        separatorDuration: 0.2,
      });
      setPlayhead(0);
      setPlaying(false);
    } catch (error) {
      editor.setError(error instanceof Error ? error.message : String(error));
    }
  }

  function addSuggestedFlashback(suggestion: FlashbackSuggestion) {
    const project = editor.project;
    if (!project) return;
    const asset = Object.values(project.assets).find((candidate) => candidate.origin === "local-vod" && candidate.kind === "video");
    const track = asset && project.tracks.find((candidate) => candidate.kind === "video" && candidate.items.some((item) => item.assetId === asset.id));
    if (!asset || !track) {
      editor.setError("The original long-form source is unavailable for this flashback");
      return;
    }
    const existingFlashbacks = allItems(project).filter((item) => item.video && item.editorRole === "flashback");
    const mainStarts = allItems(project).filter((item) => item.video && item.editorRole !== "flashback").map((item) => item.timelineStart);
    const insertAt = existingFlashbacks.length > 0 && mainStarts.length > 0 ? Math.min(...mainStarts) : 0;
    try {
      editor.dispatch({
        type: "CREATE_SOURCE_FLASHBACK",
        assetId: asset.id,
        trackId: track.id,
        sourceIn: suggestion.sourceStart,
        sourceOut: suggestion.sourceEnd,
        beatId: suggestion.beatId,
        insertAt,
        separatorDuration: 0.2,
      });
      setPlayhead(0);
      setPlaying(false);
    } catch (error) {
      editor.setError(error instanceof Error ? error.message : String(error));
    }
  }

  const selectedId = editor.project?.selection.itemIds[0];
  const selected = editor.project && selectedId ? findItem(editor.project, selectedId) : undefined;
  const canCreateFlashback = Boolean(
    editor.project
    && selected?.track.kind === "video"
    && selected.item.video
    && editor.project.inPoint !== null
    && editor.project.outPoint !== null
    && editor.project.outPoint > editor.project.inPoint
    && editor.project.inPoint >= selected.item.timelineStart
    && editor.project.outPoint <= itemEnd(selected.item),
  );

  return (
    <div
      className="fixed inset-0 z-[80] bg-[#07090c]/95 p-2 text-slate-100 backdrop-blur-md"
      onMouseDown={(event) => event.stopPropagation()}
      onClick={(event) => event.stopPropagation()}
    >
      <div className="mx-auto flex h-full max-w-[1800px] flex-col overflow-hidden rounded-lg border border-white/10 bg-[#0b0e12] shadow-2xl">
        <header className="flex h-11 shrink-0 items-center gap-2 border-b border-white/10 bg-[#151a20] px-3">
          <div className="mr-3 min-w-0"><div className="truncate text-xs font-semibold">{stem}</div><div className="text-[8px] uppercase tracking-[0.2em] text-cyan-400">InstaClip Editor V2</div></div>
          <ToolbarButton title="Undo (Ctrl+Z)" disabled={!editor.canUndo} onClick={editor.undo}><Undo2 /></ToolbarButton>
          <ToolbarButton title="Redo (Ctrl+Y)" disabled={!editor.canRedo} onClick={editor.redo}><Redo2 /></ToolbarButton>
          <ToolbarButton title="Copy selected (Ctrl+C)" disabled={!editor.project?.selection.itemIds.length} onClick={() => editor.dispatch({ type: "COPY_ITEMS", itemIds: editor.project?.selection.itemIds ?? [] })}><Copy /></ToolbarButton>
          <ToolbarButton title="Split selected at playhead (S)" disabled={!editor.project?.selection.itemIds.length} onClick={() => editor.dispatch({ type: "SPLIT_ITEMS", itemIds: editor.project?.selection.itemIds ?? [], time: playhead })}><Scissors /></ToolbarButton>
          <div className="mx-1 h-5 w-px bg-white/10" />
          <button type="button" onClick={() => editor.project && editor.dispatch({ type: "SET_IN_OUT", inPoint: playhead, outPoint: editor.project.outPoint })} className="editor-v2-tool px-2 text-[9px]">Mark In</button>
          <button type="button" onClick={() => editor.project && editor.dispatch({ type: "SET_IN_OUT", inPoint: editor.project.inPoint, outPoint: playhead })} className="editor-v2-tool px-2 text-[9px]">Mark Out</button>
          <button type="button" disabled={!canCreateFlashback} onClick={createFlashback} title="Duplicate the selected In/Out range into the opening teaser, preserve the later payoff, and add a 0.2s black separator" className="editor-v2-tool gap-1 px-2 text-[9px] disabled:opacity-25"><Rewind className="h-3 w-3" /> Flashback</button>
          <button type="button" onClick={() => editor.addTitleCard(playhead, editor.project?.longformPlan?.youtubePackage?.title ?? "NEW TITLE")} title="Add a three-second editable title card at the playhead" className="editor-v2-tool gap-1 px-2 text-[9px]"><Type className="h-3 w-3" /> Title</button>
          <button type="button" disabled={scanningLayout} onClick={() => void scanLayouts()} title="Detect full-cam, small-cam, and no-face layout switches" className="editor-v2-tool gap-1 px-2 text-[9px] disabled:opacity-40">{scanningLayout ? <Loader2 className="h-3 w-3 animate-spin" /> : <ScanLine className="h-3 w-3" />} Scan layout</button>
          {layoutScan?.has_layout_switch && <button type="button" onClick={splitAtLayoutSwitches} title="Split source clips at every detected camera-layout switch" className="editor-v2-tool px-2 text-[9px]">Split {layoutSwitchPoints().length} switches</button>}
          <div className="flex-1" />
          <span className={cn("flex items-center gap-1 text-[9px]", editor.saveState === "error" ? "text-rose-400" : editor.saveState === "saving" ? "text-amber-300" : "text-emerald-400")}><Save className="h-3 w-3" />{editor.saveState}</span>
          {onLegacy && <button type="button" onClick={onLegacy} className="rounded border border-white/10 px-2 py-1 text-[9px] text-slate-500 hover:text-slate-200">Legacy editor</button>}
          <button type="button" onClick={onClose} className="editor-v2-tool" title="Close"><X /></button>
        </header>

        {editor.loading && <div className="grid flex-1 place-items-center"><div className="flex items-center gap-2 text-xs text-slate-500"><Loader2 className="h-4 w-4 animate-spin text-cyan-400" /> Loading persistent project</div></div>}
        {!editor.loading && editor.error && !editor.project && <div className="grid flex-1 place-items-center p-8 text-center"><div className="max-w-lg rounded border border-rose-400/30 bg-rose-400/5 p-5 text-xs text-rose-300">{editor.error}</div></div>}
        {editor.project && <>
          {editor.error && <div className="flex shrink-0 items-center justify-between border-b border-rose-400/20 bg-rose-400/10 px-3 py-1.5 text-[10px] text-rose-300"><span className="truncate">{editor.error}</span><button type="button" onClick={() => editor.setError("")}><X className="h-3 w-3" /></button></div>}
          <div className="grid min-h-0 flex-[3] grid-cols-[220px_minmax(360px,1fr)_270px]">
            <MediaBin project={editor.project} onRegister={editor.resolveAsset} onQuickAdd={quickAdd} onError={editor.setError} />
            <Preview project={editor.project} playhead={playhead} playing={playing} onPlayingChange={setPlaying} onSeek={(time) => { setPlayhead(time); setPlaying(false); }} onTransform={(itemId, transform) => editor.dispatch({ type: "SET_ITEM_TRANSFORM", itemId, transform })} />
            <Inspector
              project={editor.project}
              tab={tab}
              onTab={setTab}
              dispatch={editor.dispatch}
              detachAudio={editor.detachSelectedAudio}
              rendering={editor.rendering}
              renderedStem={editor.renderedStem}
              onRender={render}
              sourceBucket={bucket}
              sourceStem={stem}
              onApplyTemplate={applyTemplate}
              onSuggestTrim={suggestTrim}
              onAutoEdit={autoEditSelected}
              onBuildCompilation={buildCompilation}
              onSeek={(time) => { setPlayhead(time); setPlaying(false); }}
              onOpenProject={onOpenProject}
              onAddFlashback={addSuggestedFlashback}
              onApplyTranscriptOps={editor.applyTranscriptOps}
              onDetectCam={editor.detectCam}
              onExtend={editor.extendClip}
              onOpenLegacy={onLegacy}
              onError={editor.setError}
            />
          </div>
          <div className="flex min-h-[260px] min-w-0 flex-[2] overflow-hidden">
            <Timeline project={editor.project} playhead={playhead} followPlayhead={playing} layoutMarkers={layoutSwitchPoints().map(({ time, label }) => ({ time, label }))} onPlayhead={(time) => { setPlayhead(time); setPlaying(false); }} dispatch={editor.dispatch} onDropSource={dropSource} onDropFiles={dropFiles} onAddTrack={editor.addTrack} onAddCaption={() => editor.addCaption(playhead)} />
          </div>
          <footer className="flex h-6 shrink-0 items-center gap-3 border-t border-white/10 bg-[#11161b] px-3 text-[8px] text-slate-600">
            <span>{allItems(editor.project).length} timeline items</span><span>{Object.keys(editor.project.assets).length} assets</span><span>{projectDuration(editor.project).toFixed(2)} sec</span><span className="ml-auto">Space play · S split · I/O range · Ctrl+C/X/V · Delete</span>
          </footer>
        </>}
      </div>
    </div>
  );
}

function ToolbarButton({ title, disabled, onClick, children }: { title: string; disabled?: boolean; onClick: () => void; children: React.ReactNode }) {
  return <button type="button" title={title} disabled={disabled} onClick={onClick} className="editor-v2-tool disabled:opacity-25">{children}</button>;
}
