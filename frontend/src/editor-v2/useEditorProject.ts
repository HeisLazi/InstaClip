import { useEffect, useRef, useState } from "react";

import { api, type Bucket, type TranscriptEditOperation } from "@/api/client";
import {
  applyCommand,
  canRedo,
  canUndo,
  createHistory,
  DEFAULT_CAPTION_SETTINGS,
  newAssetId,
  newItemId,
  newLinkedGroupId,
  newTrackId,
  itemEnd,
  projectDuration,
  redo,
  undo,
  type Command,
  type EditorAsset,
  type EditorHistory,
  type EditorProjectV2,
  type TimelineItem,
  type TrackKind,
} from "@/editor-v2/model";

export type AssetSource =
  | { type: "asset"; asset: EditorAsset }
  | { type: "clip"; bucket: Bucket; stem: string }
  | { type: "media"; mediaId: string }
  | { type: "sound"; soundName: string };

export type LayoutTemplate = {
  id?: string;
  label?: string;
  layout: "reaction" | "crop" | "fullcam" | "passthrough";
  cam_box?: [number, number, number, number];
  content_box?: [number, number, number, number];
  crop_box?: [number, number, number, number];
  audio_normalize?: boolean;
  audio_boost_db?: number;
};

export type CompilationEntry = {
  bucket: Bucket;
  stem: string;
  trim?: { start: number; end: number };
};

export type CompilationOptions = {
  replacePrimary: boolean;
  transitionDuration: number;
  transitionSound?: string;
};

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function useEditorProject(bucket: Bucket, stem: string, localPath?: string, projectId?: string, candidateId?: string) {
  const [history, setHistory] = useState<EditorHistory | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saveState, setSaveState] = useState<"saved" | "saving" | "error">("saved");
  const [rendering, setRendering] = useState(false);
  const [renderedStem, setRenderedStem] = useState<string | null>(null);
  const latestProject = useRef<EditorProjectV2 | null>(null);

  const project = history?.current ?? null;
  latestProject.current = project;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    (projectId ? api.edit.v2.get(projectId) : localPath ? api.edit.v2.fromLocal(localPath, stem) : api.edit.v2.fromClip(bucket, stem))
      .then(({ project: next }) => {
        if (!cancelled) {
          const linked = candidateId && next.sourceCandidateId !== candidateId
            ? { ...next, sourceCandidateId: candidateId, revision: next.revision + 1, updatedAt: Date.now() }
            : next;
          setHistory(createHistory(linked));
        }
      })
      .catch((nextError) => {
        if (!cancelled) setError(`Editor V2 could not load this clip. Restart the backend, then retry. ${errorText(nextError)}`);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [bucket, stem, localPath, projectId, candidateId]);

  useEffect(() => {
    if (!project) return;
    setSaveState("saving");
    const timer = window.setTimeout(() => {
      api.edit.v2.save(project)
        .then(() => setSaveState("saved"))
        .catch((nextError) => {
          setSaveState("error");
          setError(`Autosave failed: ${errorText(nextError)}`);
        });
    }, 650);
    return () => window.clearTimeout(timer);
  }, [project?.id, project?.revision]);

  function dispatch(command: Command) {
    setHistory((current) => current ? applyCommand(current, command) : current);
  }

  function dispatchMany(commands: Command[]) {
    setHistory((current) => {
      if (!current) return current;
      return commands.reduce((next, command) => applyCommand(next, command), current);
    });
  }

  function undoCommand() {
    setHistory((current) => current ? undo(current) : current);
  }

  function redoCommand() {
    setHistory((current) => current ? redo(current) : current);
  }

  function replaceProject(next: EditorProjectV2) {
    setHistory((current) => current
      ? { ...current, current: next }
      : createHistory(next));
  }

  async function resolveAsset(source: AssetSource): Promise<EditorAsset> {
    if (!latestProject.current) throw new Error("Editor project is not ready");
    if (source.type === "asset") return source.asset;
    const projectId = latestProject.current.id;
    const result = source.type === "clip"
      ? await api.edit.v2.addClip(projectId, source.bucket, source.stem)
      : source.type === "media"
        ? await api.edit.v2.addMedia(projectId, source.mediaId)
        : await api.edit.v2.addSound(projectId, source.soundName);
    replaceProject(result.project);
    return result.asset;
  }

  async function addSourceToTrack(source: AssetSource, trackId: string, timelineStart: number) {
    const asset = await resolveAsset(source);
    const current = latestProject.current;
    if (!current) return;
    const track = current.tracks.find((candidate) => candidate.id === trackId);
    if (!track) throw new Error("Timeline track not found");
    const wantsAudio = track.kind === "audio";
    if (wantsAudio && !asset.hasAudio) throw new Error(`${asset.name} has no audio`);
    if (!wantsAudio && asset.kind === "audio") throw new Error("Drop audio on an A track");
    const defaultDuration = asset.kind === "image" ? 5 : Math.max(0.1, asset.duration);
    const item: TimelineItem = {
      id: newItemId(),
      assetId: asset.id,
      trackId,
      timelineStart: Math.max(0, timelineStart),
      sourceIn: 0,
      sourceOut: defaultDuration,
      speed: 1,
      linkedGroupId: null,
      enabled: true,
      ...(wantsAudio ? {
        audio: { volume: 1, pan: 0, fadeIn: 0, fadeOut: 0, normalize: false },
      } : {
        video: {
          x: 0, y: 0, width: current.canvas.width, height: current.canvas.height,
          rotation: 0, opacity: 1, crop: null, fit: "contain" as const,
        },
        ...(asset.hasAudio ? {
          audio: { volume: 1, pan: 0, fadeIn: 0, fadeOut: 0, normalize: false },
        } : {}),
      }),
    };
    dispatch({ type: "ADD_ITEM", item });
    dispatch({ type: "SET_SELECTION", itemIds: [item.id], focusedTrackId: trackId });
  }

  function addTrack(kind: TrackKind) {
    const current = latestProject.current;
    if (!current) return;
    const tracks = current.tracks.filter((track) => track.kind === kind);
    const prefix = kind === "video" ? "V" : kind === "audio" ? "A" : "C";
    const order = kind === "video" ? Math.max(-1, ...tracks.map((track) => track.order)) + 1
      : kind === "audio" ? Math.max(9, ...tracks.map((track) => track.order)) + 1
        : Math.max(19, ...tracks.map((track) => track.order)) + 1;
    dispatch({
      type: "ADD_TRACK",
      track: {
        id: newTrackId(), kind, name: `${prefix}${tracks.length + 1}`, order,
        muted: false, solo: false, locked: false, hidden: false,
      },
    });
  }

  function addCaption(timelineStart: number) {
    const current = latestProject.current;
    if (!current) return;
    const existingTrack = current.tracks.find((track) => track.kind === "caption" && !track.locked);
    const trackId = existingTrack?.id ?? newTrackId();
    const assetId = newAssetId();
    const itemId = newItemId();
    const commands: Command[] = [];
    if (!existingTrack) {
      commands.push({
        type: "ADD_TRACK",
        track: {
          id: trackId, kind: "caption", name: "C1", order: 20,
          muted: false, solo: false, locked: false, hidden: false,
        },
      });
    }
    commands.push({
      type: "ADD_ASSET",
      asset: {
        id: assetId, kind: "caption", origin: "generated", name: "Caption",
        duration: 3, hasAudio: false, fingerprint: assetId,
        streamUrl: "", thumbnailUrl: "",
      },
    });
    commands.push({
      type: "ADD_ITEM",
      item: {
        id: itemId, assetId, trackId, timelineStart: Math.max(0, timelineStart),
        sourceIn: 0, sourceOut: 3, speed: 1, linkedGroupId: null, enabled: true,
        caption: { ...DEFAULT_CAPTION_SETTINGS },
      },
    });
    commands.push({ type: "SET_SELECTION", itemIds: [itemId], focusedTrackId: trackId });
    dispatchMany(commands);
  }

  function addTitleCard(timelineStart: number, text = "NEW TITLE") {
    const current = latestProject.current;
    if (!current) return;
    const existingTrack = current.tracks.find((track) => track.kind === "caption" && !track.locked);
    const trackId = existingTrack?.id ?? newTrackId();
    const assetId = newAssetId();
    const itemId = newItemId();
    const commands: Command[] = [];
    if (!existingTrack) {
      commands.push({
        type: "ADD_TRACK",
        track: { id: trackId, kind: "caption", name: "C1", order: 20, muted: false, solo: false, locked: false, hidden: false },
      });
    }
    commands.push({
      type: "ADD_ASSET",
      asset: { id: assetId, kind: "caption", origin: "generated", name: "Title card", duration: 3, hasAudio: false, fingerprint: assetId, streamUrl: "", thumbnailUrl: "" },
    });
    commands.push({
      type: "ADD_ITEM",
      item: {
        id: itemId, assetId, trackId, timelineStart: Math.max(0, timelineStart),
        sourceIn: 0, sourceOut: 3, speed: 1, linkedGroupId: null, enabled: true,
        editorRole: "title_card",
        caption: {
          ...DEFAULT_CAPTION_SETTINGS,
          text: text.trim().slice(0, 120) || "NEW TITLE",
          fontSize: current.canvas.width > current.canvas.height ? 96 : 82,
          position: "center",
          backgroundOpacity: 0.72,
          strokeWidth: 4,
          variant: "title",
          animation: "fade",
        },
      },
    });
    commands.push({ type: "SET_SELECTION", itemIds: [itemId], focusedTrackId: trackId });
    dispatchMany(commands);
  }

  function detachSelectedAudio() {
    const current = latestProject.current;
    const itemId = current?.selection.itemIds[0];
    if (!current || !itemId) return;
    const item = current.tracks.flatMap((track) => track.items).find((candidate) => candidate.id === itemId);
    const audioTrack = current.tracks.find((track) => track.kind === "audio" && !track.locked);
    if (!item?.video || !item.audio || !audioTrack) return;
    dispatch({
      type: "DETACH_AUDIO",
      itemId,
      newAudioTrackId: audioTrack.id,
      newAudioItemId: newItemId(),
      linkedGroupId: item.linkedGroupId ?? newLinkedGroupId(),
    });
  }

  function applyTemplate(template: LayoutTemplate) {
    const current = latestProject.current;
    const itemId = current?.selection.itemIds[0];
    if (!current || !itemId) throw new Error("Select a video clip before applying a template");
    const located = current.tracks
      .flatMap((track) => track.items.map((item) => ({ item, track })))
      .find(({ item }) => item.id === itemId);
    if (!located?.item.video) throw new Error("Templates can only be applied to video clips");

    const primarySibling = located.item.linkedGroupId
      ? current.tracks.flatMap((track) => track.items).find((candidate) =>
          candidate.id !== located.item.id
          && candidate.assetId === located.item.assetId
          && candidate.linkedGroupId === located.item.linkedGroupId
          && Boolean(candidate.video)
          && Boolean(candidate.audio),
        )
      : undefined;
    const base = !located.item.audio && primarySibling ? primarySibling : located.item;
    const canvas = current.canvas;
    const tuple = (value: number[] | undefined): [number, number, number, number] | null =>
      value?.length === 4 ? [value[0], value[1], value[2], value[3]] : null;
    const groupVideo = base.linkedGroupId
      ? current.tracks.flatMap((track) => track.items).find((candidate) =>
          candidate.id !== base.id
          && candidate.assetId === base.assetId
          && candidate.linkedGroupId === base.linkedGroupId
          && Boolean(candidate.video)
          && !candidate.audio,
        )
      : undefined;
    const commands: Command[] = [];
    const normalize = template.audio_normalize;
    const boost = template.audio_boost_db;
    if (base.audio && (typeof normalize === "boolean" || typeof boost === "number")) {
      commands.push({
        type: "SET_ITEM_AUDIO",
        itemId: base.id,
        audio: {
          ...(typeof normalize === "boolean" ? { normalize } : {}),
          ...(typeof boost === "number" ? { volume: Math.max(0, Math.min(4, 10 ** (boost / 20))) } : {}),
        },
      });
    }

    const needsCompanion = template.layout === "reaction" || template.layout === "fullcam";
    if (!needsCompanion && groupVideo) {
      commands.push({ type: "UNLINK_ITEMS", itemIds: [groupVideo.id] });
      commands.push({ type: "DELETE_ITEMS", itemIds: [groupVideo.id] });
    }

    if (template.layout === "reaction") {
      const contentTop = Math.round(canvas.height * 0.344);
      const camTop = Math.round(canvas.height * 0.029);
      const camHeight = Math.round(canvas.height * 0.3125);
      commands.push({
        type: "SET_ITEM_TRANSFORM",
        itemId: base.id,
        transform: { x: 0, y: contentTop, width: canvas.width, height: canvas.height - contentTop, crop: tuple(template.content_box), fit: "cover", blur: 0 },
      });
      const companionTransform = { x: 0, y: camTop, width: canvas.width, height: camHeight, crop: tuple(template.cam_box), fit: "cover" as const, rotation: 0, opacity: 1, blur: 0 };
      if (groupVideo) {
        commands.push({ type: "SET_ITEM_TRANSFORM", itemId: groupVideo.id, transform: companionTransform });
      } else {
        const overlayTrack = current.tracks.find((track) => track.kind === "video" && track.id !== base.trackId && !track.locked);
        if (!overlayTrack) throw new Error("Add an unlocked overlay video track first");
        const companionId = newItemId();
        const linkedGroupId = base.linkedGroupId ?? newLinkedGroupId();
        commands.push({
          type: "ADD_ITEM",
          item: {
            id: companionId, assetId: base.assetId, trackId: overlayTrack.id,
            timelineStart: base.timelineStart, sourceIn: base.sourceIn, sourceOut: base.sourceOut,
            speed: base.speed, linkedGroupId, enabled: true,
            video: companionTransform,
          },
        });
        commands.push({ type: "LINK_ITEMS", itemIds: base.linkedGroupId ? [companionId] : [base.id, companionId], linkedGroupId });
      }
    } else if (template.layout === "fullcam") {
      const crop = tuple(template.cam_box);
      commands.push({ type: "SET_ITEM_TRANSFORM", itemId: base.id, transform: { x: 0, y: 0, width: canvas.width, height: canvas.height, crop, fit: "cover", blur: 28 } });
      const foreground = { x: 0, y: 0, width: canvas.width, height: canvas.height, crop, fit: "contain" as const, rotation: 0, opacity: 1, blur: 0 };
      if (groupVideo) {
        commands.push({ type: "SET_ITEM_TRANSFORM", itemId: groupVideo.id, transform: foreground });
      } else {
        const overlayTrack = current.tracks.find((track) => track.kind === "video" && track.id !== base.trackId && !track.locked);
        if (!overlayTrack) throw new Error("Add an unlocked overlay video track first");
        const companionId = newItemId();
        const linkedGroupId = base.linkedGroupId ?? newLinkedGroupId();
        commands.push({ type: "ADD_ITEM", item: { id: companionId, assetId: base.assetId, trackId: overlayTrack.id, timelineStart: base.timelineStart, sourceIn: base.sourceIn, sourceOut: base.sourceOut, speed: base.speed, linkedGroupId, enabled: true, video: foreground } });
        commands.push({ type: "LINK_ITEMS", itemIds: base.linkedGroupId ? [companionId] : [base.id, companionId], linkedGroupId });
      }
    } else if (template.layout === "crop") {
      commands.push({ type: "SET_ITEM_TRANSFORM", itemId: base.id, transform: { x: 0, y: 0, width: canvas.width, height: canvas.height, crop: tuple(template.crop_box), fit: "cover", blur: 0 } });
    } else {
      commands.push({ type: "SET_ITEM_TRANSFORM", itemId: base.id, transform: { x: 0, y: 0, width: canvas.width, height: canvas.height, crop: null, fit: "contain", blur: 0 } });
    }
    commands.push({ type: "SET_SELECTION", itemIds: [base.id], focusedTrackId: base.trackId });
    dispatchMany(commands);
  }

  async function buildCompilation(entries: CompilationEntry[], options: CompilationOptions) {
    let working = latestProject.current;
    if (!working) throw new Error("Editor project is not ready");
    const assets: EditorAsset[] = [];
    for (const entry of entries) {
      const result = await api.edit.v2.addClip(working.id, entry.bucket, entry.stem);
      working = result.project;
      assets.push(result.asset);
    }
    let transitionAsset: EditorAsset | null = null;
    if (options.transitionSound && options.transitionDuration > 0) {
      const result = await api.edit.v2.addSound(working.id, options.transitionSound);
      working = result.project;
      transitionAsset = result.asset;
    }

    const videoTrack = working.tracks.find((track) => track.kind === "video" && !track.locked);
    const audioTrack = working.tracks.find((track) => track.kind === "audio" && !track.locked);
    if (!videoTrack) throw new Error("Add an unlocked video track first");
    const commands: Command[] = [];
    if (options.replacePrimary && videoTrack.items.length > 0) {
      commands.push({ type: "DELETE_ITEMS", itemIds: videoTrack.items.map((item) => item.id) });
    }
    let cursor = options.replacePrimary ? 0 : projectDuration(working);
    let firstItemId: string | null = null;
    entries.forEach((entry, index) => {
      const asset = assets[index];
      const start = Math.max(0, entry.trim?.start ?? 0);
      const end = Math.max(start + 0.1, Math.min(asset.duration, entry.trim?.end ?? asset.duration));
      const itemId = newItemId();
      firstItemId ??= itemId;
      const assetWidth = asset.width ?? working!.canvas.width;
      const assetHeight = asset.height ?? working!.canvas.height;
      const targetRatio = working!.canvas.width / working!.canvas.height;
      let crop: [number, number, number, number] | null = null;
      if (assetWidth / assetHeight >= targetRatio) {
        const width = Math.round(assetHeight * targetRatio);
        crop = [Math.round((assetWidth - width) / 2), 0, width, assetHeight];
      } else {
        const height = Math.round(assetWidth / targetRatio);
        crop = [0, Math.round((assetHeight - height) / 2), assetWidth, height];
      }
      commands.push({
        type: "ADD_ITEM",
        item: {
          id: itemId, assetId: asset.id, trackId: videoTrack.id, timelineStart: cursor,
          sourceIn: start, sourceOut: end, speed: 1, linkedGroupId: null, enabled: true,
          video: { x: 0, y: 0, width: working!.canvas.width, height: working!.canvas.height, rotation: 0, opacity: 1, blur: 0, crop, fit: "cover" },
          ...(asset.hasAudio ? { audio: { volume: 1, pan: 0, fadeIn: 0, fadeOut: 0, normalize: true } } : {}),
        },
      });
      cursor += end - start;
      if (index < entries.length - 1 && options.transitionDuration > 0) {
        if (transitionAsset && audioTrack) {
          commands.push({
            type: "ADD_ITEM",
            item: {
              id: newItemId(), assetId: transitionAsset.id, trackId: audioTrack.id,
              timelineStart: cursor, sourceIn: 0,
              sourceOut: Math.max(0.1, Math.min(transitionAsset.duration, options.transitionDuration)),
              speed: 1, linkedGroupId: null, enabled: true,
              audio: { volume: 1, pan: 0, fadeIn: 0, fadeOut: 0, normalize: false },
            },
          });
        }
        cursor += options.transitionDuration;
      }
    });
    if (firstItemId) commands.push({ type: "SET_SELECTION", itemIds: [firstItemId], focusedTrackId: videoTrack.id });

    setHistory((current) => {
      if (!current) return current;
      const withAssets = { ...current, current: working! };
      return commands.reduce((next, command) => applyCommand(next, command), withAssets);
    });
  }

  async function render() {
    const current = latestProject.current;
    if (!current) return;
    setRendering(true);
    setError("");
    try {
      await api.edit.v2.save(current);
      const result = await api.edit.v2.render(current.id);
      setRenderedStem(result.stem);
      return result;
    } catch (nextError) {
      setError(errorText(nextError));
      throw nextError;
    } finally {
      setRendering(false);
    }
  }

  async function applyTranscriptOps(ops: TranscriptEditOperation[]) {
    const current = latestProject.current;
    if (!current) throw new Error("Editor project is not ready");
    setError("");
    try {
      const result = await api.edit.v2.transcriptOps(current.id, ops, current.revision);
      replaceProject(result.project);
      setSaveState("saved");
      return result.report;
    } catch (nextError) {
      const message = errorText(nextError);
      setError(message.includes("409") || message.toLowerCase().includes("revision conflict")
        ? "This project changed in another window. Close and reopen it before applying transcript edits."
        : message);
      throw nextError;
    }
  }

  async function extendClip(before: number, after: number) {
    const current = latestProject.current;
    if (!current) throw new Error("Editor project is not ready");
    setError("");
    try {
      const result = await api.edit.v2.extend(current.id, {
        before, after, expected_revision: current.revision,
      });
      replaceProject(result.project);
      setSaveState("saved");
      return result.report;
    } catch (nextError) {
      const message = errorText(nextError);
      setError(message.toLowerCase().includes("revision conflict")
        ? "This project changed in another window. Close and reopen it before extending."
        : message);
      throw nextError;
    }
  }

  async function detectCam(sourceTime?: number) {
    const current = latestProject.current;
    if (!current) throw new Error("Editor project is not ready");
    setError("");
    try {
      return await api.edit.v2.detectCam(current.id, { source_time: sourceTime });
    } catch (nextError) {
      setError(errorText(nextError));
      throw nextError;
    }
  }

  return {
    project,
    history,
    loading,
    error,
    setError,
    saveState,
    rendering,
    renderedStem,
    dispatch,
    undo: undoCommand,
    redo: redoCommand,
    canUndo: history ? canUndo(history) : false,
    canRedo: history ? canRedo(history) : false,
    resolveAsset,
    addSourceToTrack,
    addTrack,
    addCaption,
    addTitleCard,
    detachSelectedAudio,
    applyTemplate,
    buildCompilation,
    applyTranscriptOps,
    extendClip,
    detectCam,
    render,
  };
}
