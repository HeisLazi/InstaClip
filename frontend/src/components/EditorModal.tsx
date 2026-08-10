import {
  AudioLines,
  BoxSelect,
  Crop,
  Film,
  FolderInput,
  Image as ImageIcon,
  Layers3,
  ListVideo,
  Loader2,
  Music2,
  Pause,
  Play,
  Plus,
  Save,
  SlidersHorizontal,
  Sparkles,
  Volume2,
  Video,
  Wand2,
  X,
} from "lucide-react";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";

import {
  api,
  type Bucket,
  type ClipInfo,
  type CompilationItem,
  type EditorMediaAsset,
  type EditorPreset,
} from "@/api/client";
import {
  EditorTimeline,
  locatePlayhead,
  sequencePositions,
  type EditorLayout as Layout,
  type TimelineFx as Fx,
  type TimelineMediaKind,
  type TimelineSegment,
} from "@/components/EditorTimeline";
import { cn } from "@/lib/utils";

type Box = [number, number, number, number];
type Probe = { duration: number; width: number; height: number; fps: number; has_audio?: boolean };
type Sound = { name: string; file?: string; duration: number };
type Template = {
  label?: string;
  layout?: Layout;
  cam_box?: Box;
  content_box?: Box;
  crop_box?: Box;
  audio_normalize?: boolean;
  audio_boost_db?: number;
};
type EditSpec = {
  trim: { start: number; end: number };
  layout: Layout;
  cam_box?: Box;
  content_box?: Box;
  crop_box?: Box;
  audio_boost_db?: number;
  audio_normalize?: boolean;
  sound_fx?: Array<{ name: string; at: number; gain: number }>;
  output_stem?: string;
};

interface EditorModalProps {
  bucket: Bucket;
  stem: string;
  onClose: () => void;
  onRendered?: (editedStem: string) => void;
}

const LAYOUTS: Array<{ value: Layout; label: string }> = [
  { value: "reaction", label: "Reaction" },
  { value: "crop", label: "9:16 Crop" },
  { value: "fullcam", label: "Full Cam" },
  { value: "passthrough", label: "Original" },
];

const TIKTOK_CML_URL = "https://ads.tiktok.com/business/creativecenter/music/pc/en";
const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));
const newId = (prefix: string) => `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;

export function EditorModal({ bucket, stem, onClose, onRendered }: EditorModalProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const soundInputRef = useRef<HTMLInputElement>(null);
  const mediaInputRef = useRef<HTMLInputElement>(null);
  const playbackSegmentRef = useRef<string | null>(null);
  const previewRequest = useRef(0);
  const previewLastStarted = useRef(0);
  const fxAudioRef = useRef<Map<string, HTMLAudioElement>>(new Map());
  const playedFxRef = useRef<Set<string>>(new Set());
  const lastFxPreviewTimeRef = useRef(0);
  const fxRef = useRef<Fx[]>([]);
  const playingRef = useRef(false);

  const videoUrl = api.clips.videoUrl(bucket, stem);
  const thumbnailUrl = api.clips.thumbUrl(bucket, stem);
  const [probe, setProbe] = useState<Probe | null>(null);
  const [probeError, setProbeError] = useState<string | null>(null);
  const [sounds, setSounds] = useState<Sound[]>([]);
  const [templates, setTemplates] = useState<Record<string, Template>>({});
  const [customPresets, setCustomPresets] = useState<EditorPreset[]>([]);
  const [presetName, setPresetName] = useState("");
  const [presetBusy, setPresetBusy] = useState(false);
  const [soundSearch, setSoundSearch] = useState("");
  const [importingSound, setImportingSound] = useState(false);
  const [mediaAssets, setMediaAssets] = useState<EditorMediaAsset[]>([]);
  const [importingMedia, setImportingMedia] = useState(false);

  const [camBox, setCamBox] = useState<Box>([0, 0, 0, 0]);
  const [contentBox, setContentBox] = useState<Box>([0, 0, 0, 0]);
  const [cropBox, setCropBox] = useState<Box>([0, 0, 0, 0]);
  const [segments, setSegments] = useState<TimelineSegment[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [undoStack, setUndoStack] = useState<TimelineSegment[][]>([]);
  const [redoStack, setRedoStack] = useState<TimelineSegment[][]>([]);
  const [playhead, setPlayhead] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [zoom, setZoom] = useState(32);
  const [peaks, setPeaks] = useState<number[]>([]);

  const [boostDb, setBoostDb] = useState(0);
  const [normalize, setNormalize] = useState(true);
  const [fx, setFx] = useState<Fx[]>([]);
  const [outputStem, setOutputStem] = useState("");
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [renderBusy, setRenderBusy] = useState<"render" | "auto" | "compile" | null>(null);
  const [useCompilationTransition, setUseCompilationTransition] = useState(true);
  const [transitionSound, setTransitionSound] = useState("");
  const [transitionDuration, setTransitionDuration] = useState(0.8);
  const [transitionType, setTransitionType] = useState(""); // "" = black card; else xfade
  const [compilationCandidates, setCompilationCandidates] = useState<ClipInfo[]>([]);
  const [selectedCandidates, setSelectedCandidates] = useState<Set<string>>(new Set());
  const [candidateBusy, setCandidateBusy] = useState(false);
  const [trimBusy, setTrimBusy] = useState(false);
  const [trimMessage, setTrimMessage] = useState<string | null>(null);
  const [renderedStem, setRenderedStem] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const positions = useMemo(() => sequencePositions(segments), [segments]);
  const sequenceDuration = positions.reduce((total, segment) => total + segment.duration, 0);
  const location = useMemo(() => locatePlayhead(segments, playhead), [segments, playhead]);
  const selectedSegment = segments.find((segment) => segment.id === selectedId) ?? segments[0];
  const monitorSegment = location?.segment ?? selectedSegment;
  const monitorKind = (monitorSegment?.mediaKind ?? "source") as TimelineMediaKind;
  const selectedIsSource = (selectedSegment?.mediaKind ?? "source") === "source";
  const monitorBucket = monitorSegment?.clipBucket ?? bucket;
  const monitorStem = monitorSegment?.clipStem ?? stem;
  const monitorUrl = monitorSegment?.mediaUrl ?? videoUrl;
  const monitorThumbnail = monitorSegment?.thumbnailUrl ?? thumbnailUrl;
  const monitorProbe: Probe = {
    duration: monitorSegment?.mediaDuration ?? probe?.duration ?? 0,
    width: monitorSegment?.mediaWidth ?? probe?.width ?? 1920,
    height: monitorSegment?.mediaHeight ?? probe?.height ?? 1080,
    fps: probe?.fps ?? 30,
  };
  const baseWidth = probe?.width || monitorProbe.width;
  const baseHeight = probe?.height || monitorProbe.height;
  const boxForMonitor = (box: Box): Box => [
    Math.round((box[0] / baseWidth) * monitorProbe.width),
    Math.round((box[1] / baseHeight) * monitorProbe.height),
    Math.max(1, Math.round((box[2] / baseWidth) * monitorProbe.width)),
    Math.max(1, Math.round((box[3] / baseHeight) * monitorProbe.height)),
  ];
  const boxFromMonitor = (box: Box): Box => [
    Math.round((box[0] / monitorProbe.width) * baseWidth),
    Math.round((box[1] / monitorProbe.height) * baseHeight),
    Math.max(1, Math.round((box[2] / monitorProbe.width) * baseWidth)),
    Math.max(1, Math.round((box[3] / monitorProbe.height) * baseHeight)),
  ];
  const activeLayout = location?.segment.layout ?? selectedSegment?.layout ?? "reaction";

  useEffect(() => {
    let alive = true;
    setProbe(null);
    setProbeError(null);
    setRenderedStem(null);
    setError(null);
    void (async () => {
      try {
        const nextProbe = await api.edit.probe(bucket, stem);
        if (!alive) return;
        if (!nextProbe.duration) {
          setProbeError("The clip was not found or has a duration of 0 seconds.");
          return;
        }
        const width = nextProbe.width || 1920;
        const height = nextProbe.height || 1080;
        const camWidth = Math.round(width * 0.28);
        const camHeight = Math.round(height * 0.34);
        const cropWidth = Math.min(width, Math.round((height * 9) / 16));
        const firstSegment: TimelineSegment = {
          id: newId("clip"),
          sourceStart: 0,
          sourceEnd: nextProbe.duration,
          layout: "reaction",
          mediaId: "source",
          mediaKind: "source",
          mediaName: `${stem}.mp4`,
          mediaDuration: nextProbe.duration,
          mediaWidth: width,
          mediaHeight: height,
          mediaUrl: videoUrl,
          thumbnailUrl,
          clipBucket: bucket,
          clipStem: stem,
        };

        setProbe(nextProbe);
        setCamBox([width - camWidth, 0, camWidth, camHeight]);
        setContentBox([0, 0, Math.round(width * 0.76), height]);
        setCropBox([Math.round((width - cropWidth) / 2), 0, cropWidth, height]);
        setSegments([firstSegment]);
        setSelectedId(firstSegment.id);
        playbackSegmentRef.current = firstSegment.id;
        setPlayhead(0);
        setUndoStack([]);
        setRedoStack([]);
        setFx([]);
        setOutputStem(`${stem}_edit`);
      } catch (nextError) {
        if (alive) {
          setProbeError(`Could not inspect this clip. Restart the backend, then reopen the editor. ${messageFrom(nextError, "Probe failed.")}`);
        }
      }

      const [soundResult, templateResult, presetResult, mediaResult] = await Promise.allSettled([
        api.edit.sounds(),
        api.edit.templates(bucket, stem),
        api.edit.presets(bucket, stem),
        api.edit.media(),
      ]);
      if (!alive) return;
      if (soundResult.status === "fulfilled") {
        setSounds(soundResult.value.sounds);
        setTransitionSound((current) => current || soundResult.value.sounds.find((sound) => /compil|transition/i.test(sound.name))?.name || soundResult.value.sounds[0]?.name || "");
      }
      if (templateResult.status === "fulfilled") setTemplates(templateResult.value.templates);
      if (presetResult.status === "fulfilled") setCustomPresets(presetResult.value.presets);
      if (mediaResult.status === "fulfilled") setMediaAssets(mediaResult.value.assets);
    })();
    return () => { alive = false; };
  }, [bucket, stem, thumbnailUrl, videoUrl]);

  useEffect(() => {
    if (!probe) return;
    let cancelled = false;
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(videoUrl, { signal: controller.signal });
        const data = await response.arrayBuffer();
        const AudioContextClass = window.AudioContext || (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
        if (!AudioContextClass || cancelled) return;
        const context = new AudioContextClass();
        const buffer = await context.decodeAudioData(data.slice(0));
        const channel = buffer.getChannelData(0);
        const count = 1000;
        const block = Math.max(1, Math.floor(channel.length / count));
        const nextPeaks = Array.from({ length: count }, (_, index) => {
          let peak = 0;
          const start = index * block;
          const end = Math.min(channel.length, start + block);
          for (let sample = start; sample < end; sample += Math.max(1, Math.floor(block / 40))) {
            peak = Math.max(peak, Math.abs(channel[sample] ?? 0));
          }
          return peak;
        });
        await context.close();
        if (!cancelled) setPeaks(nextPeaks);
      } catch {
        if (!cancelled) setPeaks([]);
      }
    })();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [probe, videoUrl]);

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      const tag = (event.target as HTMLElement | null)?.tagName.toLowerCase() ?? "";
      const typing = ["input", "textarea", "select"].includes(tag);
      if (event.key === "Escape") onClose();
      if (!typing && event.code === "Space") {
        event.preventDefault();
        void togglePlayback();
      }
      if (!typing && event.key.toLowerCase() === "s") {
        event.preventDefault();
        splitAtPlayhead();
      }
      if (!typing && (event.key === "Delete" || event.key === "Backspace")) {
        event.preventDefault();
        deleteSelected();
      }
      if (!typing && event.ctrlKey && event.key.toLowerCase() === "z") {
        event.preventDefault();
        if (event.shiftKey) redo(); else undo();
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  });

  useEffect(() => {
    if (segments.length && !segments.some((segment) => segment.id === selectedId)) {
      setSelectedId(segments[0].id);
    }
    if (playhead > sequenceDuration) seekSequence(sequenceDuration);
  }, [segments, selectedId, sequenceDuration]);

  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  useEffect(() => () => {
    for (const audio of fxAudioRef.current.values()) {
      audio.pause();
      audio.src = "";
    }
    fxAudioRef.current.clear();
  }, []);

  useEffect(() => {
    fxRef.current = fx;
  }, [fx]);

  function buildSpec(segment: TimelineSegment, segmentFx: Fx[] = [], includeOutput = false): EditSpec {
    const imported = (segment.mediaKind ?? "source") !== "source";
    const width = segment.mediaWidth ?? probe?.width ?? 1920;
    const height = segment.mediaHeight ?? probe?.height ?? 1080;
    const baseWidth = probe?.width || width;
    const baseHeight = probe?.height || height;
    const sourceBox = (box: Box): Box => [
      Math.round((box[0] / baseWidth) * width),
      Math.round((box[1] / baseHeight) * height),
      Math.max(1, Math.round((box[2] / baseWidth) * width)),
      Math.max(1, Math.round((box[3] / baseHeight) * height)),
    ];
    const cropWidth = width / height >= 9 / 16 ? Math.round(height * 9 / 16) : width;
    const cropHeight = width / height >= 9 / 16 ? height : Math.round(width * 16 / 9);
    const defaultCrop: Box = [
      Math.max(0, Math.round((width - cropWidth) / 2)),
      Math.max(0, Math.round((height - cropHeight) / 2)),
      cropWidth,
      cropHeight,
    ];
    const next: EditSpec = {
      layout: segment.layout,
      trim: { start: segment.sourceStart, end: segment.sourceEnd },
    };
    if (segment.layout === "reaction") {
      next.cam_box = imported ? [0, 0, width, height] : sourceBox(camBox);
      next.content_box = imported ? [0, 0, width, height] : sourceBox(contentBox);
    } else if (segment.layout === "crop") {
      next.crop_box = imported ? defaultCrop : sourceBox(cropBox);
    } else if (segment.layout === "fullcam") {
      next.cam_box = imported ? [0, 0, width, height] : sourceBox(camBox);
    }
    if (normalize) next.audio_normalize = true;
    if (boostDb !== 0) next.audio_boost_db = boostDb;
    if (segmentFx.length) next.sound_fx = segmentFx.map(({ name, at, gain }) => ({ name, at, gain }));
    if (includeOutput && outputStem.trim()) next.output_stem = outputStem.trim();
    return next;
  }

  const previewSpec = useMemo(() => {
    const segment = location?.segment ?? selectedSegment;
    if (!segment) return null;
    return buildSpec(segment, []);
  }, [
    location?.segment.id,
    location?.segment.layout,
    location?.segment.sourceStart,
    location?.segment.sourceEnd,
    selectedSegment?.id,
    selectedSegment?.layout,
    selectedSegment?.sourceStart,
    selectedSegment?.sourceEnd,
    camBox,
    contentBox,
    cropBox,
    normalize,
    boostDb,
  ]);

  useEffect(() => {
    if (!probe || !previewSpec || !location || (location.segment.mediaKind ?? "source") !== "source") return;
    const requestId = ++previewRequest.current;
    const wait = Math.max(0, 350 - (Date.now() - previewLastStarted.current));
    const timer = window.setTimeout(async () => {
      previewLastStarted.current = Date.now();
      setPreviewBusy(true);
      try {
        const blob = await api.edit.previewBlob(
          monitorBucket,
          monitorStem,
          previewSpec,
          clamp(location.sourceTime, 0, Math.max(0, monitorProbe.duration - 0.05)),
        );
        if (requestId === previewRequest.current) setPreviewUrl(URL.createObjectURL(blob));
      } catch (nextError) {
        if (requestId === previewRequest.current) setError(messageFrom(nextError, "Preview failed."));
      } finally {
        if (requestId === previewRequest.current) setPreviewBusy(false);
      }
    }, wait);
    return () => {
      window.clearTimeout(timer);
      if (previewRequest.current === requestId) previewRequest.current += 1;
    };
  }, [monitorBucket, monitorStem, monitorProbe.duration, probe, previewSpec, location?.sourceTime, location?.segment.mediaId, location?.segment.mediaKind]);

  function pushHistory(next: TimelineSegment[]) {
    setUndoStack((current) => [...current.slice(-39), segments]);
    setRedoStack([]);
    setSegments(next);
  }

  function undo() {
    const previous = undoStack[undoStack.length - 1];
    if (!previous) return;
    setRedoStack((current) => [segments, ...current].slice(0, 40));
    setUndoStack((current) => current.slice(0, -1));
    setSegments(previous);
  }

  function redo() {
    const next = redoStack[0];
    if (!next) return;
    setUndoStack((current) => [...current.slice(-39), segments]);
    setRedoStack((current) => current.slice(1));
    setSegments(next);
  }

  function stopFxPreview() {
    for (const audio of fxAudioRef.current.values()) {
      audio.pause();
      audio.currentTime = 0;
    }
    fxAudioRef.current.clear();
  }

  function playFxAudio(item: Fx) {
    const previous = fxAudioRef.current.get(item.id);
    if (previous) {
      previous.pause();
      previous.currentTime = 0;
    }
    const audio = new Audio(api.edit.soundUrl(item.name));
    audio.preload = "auto";
    audio.volume = clamp(item.gain, 0, 1);
    audio.onended = () => fxAudioRef.current.delete(item.id);
    audio.onerror = () => fxAudioRef.current.delete(item.id);
    fxAudioRef.current.set(item.id, audio);
    void audio.play().catch((nextError) => {
      fxAudioRef.current.delete(item.id);
      setError(messageFrom(nextError, `Could not preview ${item.name}.`));
    });
  }

  function prepareFxPreview(at: number) {
    stopFxPreview();
    playedFxRef.current = new Set(
      fxRef.current.filter((item) => item.at < at - 0.06).map((item) => item.id),
    );
    lastFxPreviewTimeRef.current = Math.max(0, at - 0.06);
  }

  function syncFxPreview(nextTime: number, force = false) {
    if (!force && !playingRef.current) {
      lastFxPreviewTimeRef.current = nextTime;
      return;
    }
    const previousTime = lastFxPreviewTimeRef.current;
    if (nextTime < previousTime - 0.15) {
      prepareFxPreview(nextTime);
      return;
    }
    for (const item of fxRef.current) {
      if (playedFxRef.current.has(item.id)) continue;
      if (item.at >= previousTime - 0.01 && item.at <= nextTime + 0.08) {
        playedFxRef.current.add(item.id);
        playFxAudio(item);
      }
    }
    lastFxPreviewTimeRef.current = nextTime;
  }

  function handleEditorPlay() {
    playingRef.current = true;
    prepareFxPreview(playhead);
    syncFxPreview(playhead, true);
    setPlaying(true);
  }

  function handleEditorPause() {
    playingRef.current = false;
    stopFxPreview();
    setPlaying(false);
  }

  function seekSequence(nextTime: number, select = false) {
    const nextLocation = locatePlayhead(segments, clamp(nextTime, 0, sequenceDuration));
    if (!nextLocation) return;
    playbackSegmentRef.current = nextLocation.segment.id;
    prepareFxPreview(nextLocation.sequenceTime);
    setPlayhead(nextLocation.sequenceTime);
    if (select) setSelectedId(nextLocation.segment.id);
    const nextKind = nextLocation.segment.mediaKind ?? "source";
    if (nextKind === "image") {
      videoRef.current?.pause();
      playingRef.current = false;
      setPlaying(false);
    } else if (videoRef.current && (monitorSegment?.mediaId ?? "source") === (nextLocation.segment.mediaId ?? "source")) {
      videoRef.current.currentTime = nextLocation.sourceTime;
    }
  }

  async function togglePlayback() {
    if (!segments.length) return;
    if (monitorKind === "image") {
      setPlaying((current) => {
        const next = !current;
        playingRef.current = next;
        if (next) {
          prepareFxPreview(playhead);
          syncFxPreview(playhead, true);
        } else {
          stopFxPreview();
        }
        return next;
      });
      return;
    }
    const video = videoRef.current;
    if (!video) return;
    if (!video.paused) {
      video.pause();
      return;
    }
    if (playhead >= sequenceDuration - 0.02) seekSequence(0);
    try {
      await video.play();
    } catch (nextError) {
      setError(messageFrom(nextError, "Playback could not start."));
    }
  }

  useEffect(() => {
    if (!playing || monitorKind !== "image" || !location) return;
    const active = location.segment;
    const startedAt = performance.now();
    const initialPlayhead = location.sequenceTime;
    let frame = 0;
    const update = (now: number) => {
      const nextTime = initialPlayhead + (now - startedAt) / 1000;
      const end = active.sequenceStart + active.duration;
      if (nextTime < end) {
        syncFxPreview(nextTime);
        setPlayhead(nextTime);
        frame = requestAnimationFrame(update);
        return;
      }
      const index = positions.findIndex((segment) => segment.id === active.id);
      const next = positions[index + 1];
      if (!next) {
        playingRef.current = false;
        stopFxPreview();
        setPlayhead(end);
        setPlaying(false);
        return;
      }
      playbackSegmentRef.current = next.id;
      setSelectedId(next.id);
      setPlayhead(next.sequenceStart);
      if ((next.mediaKind ?? "source") !== "image") {
        playingRef.current = false;
        stopFxPreview();
        setPlaying(false);
      }
    };
    frame = requestAnimationFrame(update);
    return () => cancelAnimationFrame(frame);
  }, [playing, monitorKind, monitorSegment?.id, positions]);

  function handleVideoTimeUpdate() {
    const video = videoRef.current;
    if (!video) return;
    const index = positions.findIndex((segment) => segment.id === playbackSegmentRef.current);
    const position = positions[index >= 0 ? index : 0];
    if (!position) return;
    if (video.currentTime >= position.sourceEnd - 0.025) {
      syncFxPreview(position.sequenceStart + position.duration);
      const next = positions[index + 1];
      if (next && !video.paused) {
        video.pause();
        playbackSegmentRef.current = next.id;
        setSelectedId(next.id);
        setPlayhead(next.sequenceStart);
      } else {
        video.pause();
        setPlayhead(position.sequenceStart + position.duration);
      }
      return;
    }
    const nextPlayhead = position.sequenceStart + clamp(video.currentTime - position.sourceStart, 0, position.duration);
    syncFxPreview(nextPlayhead);
    setPlayhead(nextPlayhead);
  }

  function splitAtPlayhead() {
    const current = locatePlayhead(segments, playhead);
    if (!current) return;
    const sourceAt = current.sourceTime;
    if (sourceAt <= current.segment.sourceStart + 0.1 || sourceAt >= current.segment.sourceEnd - 0.1) {
      setError("Move the playhead away from a clip edge before splitting.");
      return;
    }
    const index = segments.findIndex((segment) => segment.id === current.segment.id);
    const left = { ...current.segment, id: newId("clip"), sourceEnd: sourceAt };
    const right = { ...current.segment, id: newId("clip"), sourceStart: sourceAt };
    const next = [...segments];
    next.splice(index, 1, left, right);
    pushHistory(next);
    setSelectedId(right.id);
    playbackSegmentRef.current = right.id;
  }

  function deleteSelected() {
    if (segments.length <= 1) {
      setError("A sequence needs at least one video segment.");
      return;
    }
    const index = segments.findIndex((segment) => segment.id === selectedId);
    if (index < 0) return;
    const next = segments.filter((segment) => segment.id !== selectedId);
    pushHistory(next);
    const replacement = next[Math.min(index, next.length - 1)];
    setSelectedId(replacement.id);
    playbackSegmentRef.current = replacement.id;
    setPlayhead(Math.min(playhead, next.reduce((total, item) => total + item.sourceEnd - item.sourceStart, 0)));
  }

  function duplicateSelected() {
    const index = segments.findIndex((segment) => segment.id === selectedId);
    if (index < 0) return;
    const copy = { ...segments[index], id: newId("clip") };
    const next = [...segments];
    next.splice(index + 1, 0, copy);
    pushHistory(next);
    setSelectedId(copy.id);
  }

  function trimSegment(id: string, sourceStart: number, sourceEnd: number) {
    setSegments((current) => current.map((segment) => segment.id === id ? { ...segment, sourceStart, sourceEnd } : segment));
  }

  function updateSelectedLayout(layout: Layout) {
    if (!selectedSegment) return;
    pushHistory(segments.map((segment) => segment.id === selectedSegment.id ? { ...segment, layout } : segment));
  }

  function applyTemplate(template: Template) {
    if (template.layout) updateSelectedLayout(template.layout);
    if (template.cam_box) setCamBox(template.cam_box);
    if (template.content_box) setContentBox(template.content_box);
    if (template.crop_box) setCropBox(template.crop_box);
    if (typeof template.audio_normalize === "boolean") setNormalize(template.audio_normalize);
    if (typeof template.audio_boost_db === "number") setBoostDb(template.audio_boost_db);
  }

  async function saveCustomPreset() {
    if (!selectedSegment || !selectedIsSource || !presetName.trim()) return;
    setPresetBusy(true);
    setError(null);
    try {
      const spec = buildSpec(selectedSegment);
      await api.edit.savePreset(
        selectedSegment.clipBucket ?? bucket,
        selectedSegment.clipStem ?? stem,
        presetName.trim(),
        spec,
      );
      const refreshed = await api.edit.presets(bucket, stem);
      setCustomPresets(refreshed.presets);
      setPresetName("");
    } catch (nextError) {
      setError(messageFrom(nextError, "Could not save custom preset."));
    } finally {
      setPresetBusy(false);
    }
  }

  async function deleteCustomPreset(presetId: string) {
    setPresetBusy(true);
    setError(null);
    try {
      await api.edit.deletePreset(presetId);
      setCustomPresets((current) => current.filter((preset) => preset.id !== presetId));
    } catch (nextError) {
      setError(messageFrom(nextError, "Could not delete custom preset."));
    } finally {
      setPresetBusy(false);
    }
  }

  function addFx(name: string) {
    const item = { id: newId("fx"), name, at: playhead, gain: 0.9 };
    setFx((current) => [...current, item]);
    playFxAudio(item);
  }

  function updateFx(id: string, patch: Partial<Pick<Fx, "at" | "gain">>) {
    const activeAudio = fxAudioRef.current.get(id);
    if (activeAudio && typeof patch.gain === "number") {
      activeAudio.volume = clamp(patch.gain, 0, 1);
    }
    setFx((current) => current.map((item) => item.id === id ? { ...item, ...patch } : item));
  }

  function removeFx(id: string) {
    const activeAudio = fxAudioRef.current.get(id);
    if (activeAudio) {
      activeAudio.pause();
      fxAudioRef.current.delete(id);
    }
    setFx((current) => current.filter((entry) => entry.id !== id));
  }

  async function importSound(file: File | undefined) {
    if (!file) return;
    setImportingSound(true);
    setError(null);
    try {
      const result = await api.edit.importSound(file);
      setSounds((current) => [...current, result.sound].sort((a, b) => a.name.localeCompare(b.name)));
    } catch (nextError) {
      setError(messageFrom(nextError, "Sound import failed."));
    } finally {
      setImportingSound(false);
      if (soundInputRef.current) soundInputRef.current.value = "";
    }
  }

  function segmentFromAsset(asset: EditorMediaAsset): TimelineSegment {
    const duration = asset.kind === "image" ? 3 : Math.max(0.1, asset.duration);
    return {
      id: newId("media"),
      sourceStart: 0,
      sourceEnd: duration,
      layout: asset.kind === "video" ? "crop" : "passthrough",
      mediaId: asset.id,
      mediaKind: asset.kind,
      mediaName: asset.name,
      mediaDuration: asset.kind === "image" ? 300 : duration,
      mediaWidth: asset.width,
      mediaHeight: asset.height,
      mediaUrl: api.edit.mediaUrl(asset.id),
      thumbnailUrl: api.edit.mediaThumbnailUrl(asset.id),
    };
  }

  function addMediaToTimeline(asset: EditorMediaAsset) {
    const segment = segmentFromAsset(asset);
    pushHistory([...segments, segment]);
    setSelectedId(segment.id);
    playbackSegmentRef.current = segment.id;
  }

  async function importMedia(files: FileList | null) {
    if (!files?.length) return;
    setImportingMedia(true);
    setError(null);
    try {
      const imported: EditorMediaAsset[] = [];
      for (const file of Array.from(files)) {
        const result = await api.edit.importMedia(file);
        imported.push(result.asset);
      }
      setMediaAssets((current) => {
        const byId = new Map([...current, ...imported].map((asset) => [asset.id, asset]));
        return [...byId.values()].sort((a, b) => a.name.localeCompare(b.name));
      });
      const added = imported.map(segmentFromAsset);
      pushHistory([...segments, ...added]);
      const last = added[added.length - 1];
      if (last) {
        setSelectedId(last.id);
        playbackSegmentRef.current = last.id;
      }
    } catch (nextError) {
      setError(messageFrom(nextError, "Media import failed."));
    } finally {
      setImportingMedia(false);
      if (mediaInputRef.current) mediaInputRef.current.value = "";
    }
  }

  const compilationCandidateKey = (clip: Pick<ClipInfo, "bucket" | "stem">) => `${clip.bucket}:${clip.stem}`;

  async function loadCompilationCandidates(mode: "keepers" | "suggested") {
    setCandidateBusy(true);
    setError(null);
    try {
      const goodPromise = api.clips.list("positives", {
        limit: 200,
        minDuration: 4,
        sortBy: "score",
        order: "desc",
      });
      const lists = mode === "suggested"
        ? await Promise.all([
            goodPromise,
            api.clips.list("output", {
              limit: 200,
              minDuration: 4,
              minScore: 0.7,
              sortBy: "score",
              order: "desc",
            }),
          ])
        : [await goodPromise];
      const byKey = new Map<string, ClipInfo>();
      for (const clip of lists.flat()) {
        if (clip.hazard_flags.length) continue;
        byKey.set(compilationCandidateKey(clip), clip);
      }
      const ranked = [...byKey.values()]
        .sort((left, right) => (right.score ?? right.quality_score ?? 0) - (left.score ?? left.quality_score ?? 0))
        .slice(0, 40);
      setCompilationCandidates(ranked);
      setSelectedCandidates(mode === "suggested"
        ? new Set(ranked.slice(0, 8).map(compilationCandidateKey))
        : new Set());
    } catch (nextError) {
      setError(messageFrom(nextError, "Could not load compilation candidates."));
    } finally {
      setCandidateBusy(false);
    }
  }

  function toggleCompilationCandidate(clip: ClipInfo) {
    const key = compilationCandidateKey(clip);
    setSelectedCandidates((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  async function addCompilationCandidates() {
    const chosen = compilationCandidates.filter((clip) => selectedCandidates.has(compilationCandidateKey(clip)));
    if (!chosen.length) {
      setError("Select at least one keeper or suggested clip first.");
      return;
    }
    setCandidateBusy(true);
    setError(null);
    try {
      const existing = new Set(segments.map((segment) => `${segment.clipBucket ?? bucket}:${segment.clipStem ?? stem}`));
      const results = await Promise.allSettled(chosen.map(async (clip) => ({
        clip,
        probe: await api.edit.probe(clip.bucket, clip.stem),
      })));
      const added: TimelineSegment[] = [];
      for (const result of results) {
        if (result.status !== "fulfilled") continue;
        const { clip, probe: clipProbe } = result.value;
        const key = compilationCandidateKey(clip);
        if (existing.has(key) || clipProbe.duration <= 0) continue;
        existing.add(key);
        added.push({
          id: newId("compilation"),
          sourceStart: 0,
          sourceEnd: clipProbe.duration,
          layout: "crop",
          mediaId: `clip:${key}`,
          mediaKind: "source",
          mediaName: clip.name,
          mediaDuration: clipProbe.duration,
          mediaWidth: clipProbe.width,
          mediaHeight: clipProbe.height,
          mediaUrl: api.clips.videoUrl(clip.bucket, clip.stem),
          thumbnailUrl: api.clips.thumbUrl(clip.bucket, clip.stem),
          clipBucket: clip.bucket,
          clipStem: clip.stem,
        });
      }
      if (!added.length) {
        setError("Those clips are already on the timeline or could not be inspected.");
        return;
      }
      pushHistory([...segments, ...added]);
      setSelectedId(added[0].id);
      playbackSegmentRef.current = added[0].id;
      setSelectedCandidates(new Set());
    } finally {
      setCandidateBusy(false);
    }
  }

  async function tightenSelectedToPayoff() {
    if (!selectedSegment || (selectedSegment.mediaKind ?? "source") !== "source") {
      setError("AI payoff trim is available for project clips, not imported media.");
      return;
    }
    const clipBucket = selectedSegment.clipBucket ?? bucket;
    const clipStem = selectedSegment.clipStem ?? stem;
    setTrimBusy(true);
    setTrimMessage(null);
    setError(null);
    try {
      const suggestion = await api.edit.suggestTrim(clipBucket, clipStem);
      trimSegment(selectedSegment.id, suggestion.start, suggestion.end);
      setTrimMessage(`${suggestion.reason} (${Math.round(suggestion.confidence * 100)}% confidence)`);
    } catch (nextError) {
      setError(messageFrom(nextError, "AI payoff trim failed."));
    } finally {
      setTrimBusy(false);
    }
  }

  function compilationItems(automaticImported: boolean): CompilationItem[] {
    return positions.map((position) => {
      const segmentFx = fx
        .filter((item) => item.at >= position.sequenceStart && item.at <= position.sequenceStart + position.duration)
        .map((item) => ({ ...item, at: item.at - position.sequenceStart }));
      const kind = position.mediaKind ?? "source";
      return {
        source_type: kind === "source" ? "clip" : "media",
        bucket: kind === "source" ? (position.clipBucket ?? bucket) : undefined,
        stem: kind === "source" ? (position.clipStem ?? stem) : undefined,
        media_id: kind === "source" ? undefined : position.mediaId,
        spec: buildSpec(position, segmentFx),
        automatic: automaticImported && kind !== "image",
        still_duration: kind === "image" ? position.duration : undefined,
      };
    });
  }

  async function render(mode: "render" | "auto" | "compile") {
    if (!probe || !segments.length) return;
    setRenderBusy(mode);
    setError(null);
    try {
      let result: { stem: string };
      const containsImportedMedia = segments.some((segment) => (segment.mediaKind ?? "source") !== "source");
      const containsExternalClips = segments.some((segment) =>
        (segment.mediaKind ?? "source") === "source"
        && ((segment.clipBucket ?? bucket) !== bucket || (segment.clipStem ?? stem) !== stem),
      );
      if (mode === "compile") {
        result = await api.edit.compile(
          compilationItems(true),
          outputStem.trim() || undefined,
          useCompilationTransition ? (transitionSound || undefined) : undefined,
          useCompilationTransition ? transitionDuration : 0,
          useCompilationTransition ? (transitionType || undefined) : undefined,
        );
      } else if (mode === "auto") {
        const autoSegment = selectedSegment ?? segments[0];
        result = await api.edit.auto(
          autoSegment.clipBucket ?? bucket,
          autoSegment.clipStem ?? stem,
          buildSpec(autoSegment),
        );
      } else if (containsImportedMedia || containsExternalClips) {
        result = await api.edit.compile(
          compilationItems(containsExternalClips),
          outputStem.trim() || undefined,
        );
      } else if (segments.length === 1) {
        result = await api.edit.render(bucket, stem, buildSpec(segments[0], fx, true));
      } else {
        const specs = positions.map((position) => {
          const segmentFx = fx
            .filter((item) => item.at >= position.sequenceStart && item.at <= position.sequenceStart + position.duration)
            .map((item) => ({ ...item, at: item.at - position.sequenceStart }));
          return buildSpec(position, segmentFx);
        });
        result = await api.edit.renderSegments(bucket, stem, specs, outputStem.trim() || undefined);
      }
      setRenderedStem(result.stem);
      onRendered?.(result.stem);
    } catch (nextError) {
      setError(messageFrom(nextError, "Render failed."));
    } finally {
      setRenderBusy(null);
    }
  }

  const visibleSounds = sounds.filter((sound) => sound.name.toLowerCase().includes(soundSearch.toLowerCase()));

  return (
    <div className="fixed inset-0 z-[60] bg-[hsl(228_24%_2%/0.94)] backdrop-blur-lg" onClick={onClose}>
      <div className="flex h-full w-full flex-col overflow-hidden bg-[hsl(226_20%_6%)]" onClick={(event) => event.stopPropagation()}>
        <header className="flex h-12 shrink-0 items-center border-b border-border/70 bg-[hsl(224_18%_9%)] px-3">
          <div className="flex min-w-0 items-center gap-2">
            <div className="grid h-7 w-7 place-items-center rounded bg-primary text-primary-foreground"><Film className="h-4 w-4" /></div>
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-xs font-semibold"><span>InstaClip Studio</span><span className="text-muted-foreground">/</span><span className="truncate text-muted-foreground">{stem}</span></div>
              <div className="text-[9px] uppercase tracking-[0.18em] text-primary">Editing workspace</div>
            </div>
          </div>
          <nav className="ml-8 hidden h-full items-center gap-5 text-[11px] text-muted-foreground lg:flex">
            <span className="border-b-2 border-primary px-1 pt-0.5 text-foreground">Edit</span>
            <span>Effects</span><span>Audio</span><span>Captions</span><span>Export</span>
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <span className="hidden text-[10px] tabular-nums text-muted-foreground sm:block">{formatTime(playhead)} / {formatTime(sequenceDuration)}</span>
            <button type="button" onClick={onClose} className="rounded p-2 text-muted-foreground hover:bg-accent hover:text-foreground" aria-label="Close editor"><X className="h-4 w-4" /></button>
          </div>
        </header>

        {probeError ? (
          <div className="grid flex-1 place-items-center p-8"><div className="surface-1 max-w-xl rounded-xl border border-destructive/30 p-6 text-center text-sm leading-6 text-muted-foreground"><strong className="mb-2 block text-destructive">Editor could not load</strong>{probeError}</div></div>
        ) : !probe ? (
          <div className="flex flex-1 items-center justify-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin text-primary" /> Loading media and sequence</div>
        ) : (
          <>
            <div className="grid h-[51%] min-h-[360px] shrink-0 grid-cols-[210px_minmax(420px,1fr)_300px]">
              <aside className="flex min-h-0 flex-col overflow-hidden border-r border-border/60 bg-[hsl(224_18%_8%)]">
                <PaneTitle title="Project media" icon={<FolderInput className="h-3.5 w-3.5" />} />
                <div className="border-b border-border/50 p-2">
                  <div className="overflow-hidden rounded border border-primary/45 bg-primary/10">
                    <div className="flex items-center gap-2 p-1.5">
                      <img src={thumbnailUrl} alt="Source clip" className="h-10 w-16 rounded object-cover" />
                      <div className="min-w-0 text-[9px]"><div className="truncate font-medium">{stem}.mp4</div><div className="mt-0.5 text-muted-foreground">{formatTime(probe.duration)} / source</div></div>
                    </div>
                  </div>
                  <input ref={mediaInputRef} type="file" accept="video/*,image/*,.mkv,.webm,.mov" multiple className="hidden" onChange={(event) => void importMedia(event.target.files)} />
                  <button type="button" onClick={() => mediaInputRef.current?.click()} disabled={importingMedia} className="premium-control mt-2 flex w-full items-center justify-center gap-1.5 rounded px-2 py-1.5 text-[10px] disabled:opacity-50">
                    {importingMedia ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />} Import pictures / videos
                  </button>
                  {mediaAssets.length > 0 && (
                    <div className="mt-2 max-h-24 space-y-1 overflow-y-auto">
                      {mediaAssets.map((asset) => (
                        <button key={asset.id} type="button" onClick={() => addMediaToTimeline(asset)} className="flex w-full items-center gap-2 rounded border border-border/45 bg-secondary/20 p-1 text-left text-[9px] text-muted-foreground hover:border-primary/45 hover:text-foreground" title="Add to end of timeline">
                          <img src={api.edit.mediaThumbnailUrl(asset.id)} alt="" className="h-8 w-10 rounded object-cover" />
                          {asset.kind === "image" ? <ImageIcon className="h-3 w-3 text-emerald-300" /> : <Video className="h-3 w-3 text-sky-300" />}
                          <span className="min-w-0 flex-1 truncate">{asset.name}</span>
                          <Plus className="h-3 w-3" />
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                <div className="flex min-h-0 flex-1 flex-col">
                  <div className="flex items-center justify-between px-3 py-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground"><span>Layer FX at playhead</span><span>{sounds.length}</span></div>
                  <div className="px-2">
                    <input value={soundSearch} onChange={(event) => setSoundSearch(event.target.value)} placeholder="Search sounds..." className="w-full rounded border border-border/60 bg-secondary/35 px-2 py-1.5 text-[10px] outline-none" />
                  </div>
                  <div className="mt-2 min-h-0 flex-1 overflow-y-auto px-2 pb-2">
                    {visibleSounds.map((sound) => (
                      <button key={sound.name} type="button" onClick={() => addFx(sound.name)} className="mb-1 flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-[10px] text-muted-foreground hover:bg-accent hover:text-foreground" title="Add at playhead">
                        <AudioLines className="h-3.5 w-3.5 text-amber-300" /><span className="min-w-0 flex-1 truncate">{sound.name}</span><span className="tabular-nums">{sound.duration.toFixed(1)}s</span>
                      </button>
                    ))}
                  </div>
                  <div className="border-t border-border/50 p-2">
                    <input ref={soundInputRef} type="file" accept="audio/*,.mp4" className="hidden" onChange={(event) => void importSound(event.target.files?.[0])} />
                    <button type="button" onClick={() => soundInputRef.current?.click()} disabled={importingSound} className="premium-control flex w-full items-center justify-center gap-1.5 rounded px-2 py-1.5 text-[10px] disabled:opacity-50">
                      {importingSound ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FolderInput className="h-3.5 w-3.5" />} Import licensed audio
                    </button>
                    <a href={TIKTOK_CML_URL} target="_blank" rel="noreferrer" className="mt-1.5 block text-center text-[9px] text-primary hover:underline">Browse TikTok Commercial Music Library</a>
                  </div>
                </div>
              </aside>

              <main className="flex min-h-0 flex-col bg-[hsl(228_24%_3%)]">
                <PaneTitle title="Program monitor" detail={`${activeLayout} / segment ${Math.max(1, positions.findIndex((item) => item.id === location?.segment.id) + 1)}`} />
                <div className="flex min-h-0 flex-1 items-center justify-center p-3">
                  <SourceStage
                    videoRef={videoRef}
                    mediaUrl={monitorUrl}
                    mediaKind={monitorKind}
                    source={monitorProbe}
                    layout={activeLayout}
                    startAt={location?.sourceTime ?? selectedSegment?.sourceStart ?? 0}
                    shouldPlay={playing}
                    camBox={boxForMonitor(camBox)}
                    setCamBox={(box) => setCamBox(boxFromMonitor(box))}
                    contentBox={boxForMonitor(contentBox)}
                    setContentBox={(box) => setContentBox(boxFromMonitor(box))}
                    cropBox={boxForMonitor(cropBox)}
                    setCropBox={(box) => setCropBox(boxFromMonitor(box))}
                    onTimeUpdate={handleVideoTimeUpdate}
                    onPlay={handleEditorPlay}
                    onPause={handleEditorPause}
                  />
                </div>
                <div className="flex h-11 shrink-0 items-center justify-center gap-3 border-t border-border/50 bg-[hsl(224_18%_8%)] px-3">
                  <span className="w-20 text-right text-[10px] tabular-nums text-primary">{formatTime(playhead)}</span>
                  <button type="button" onClick={() => seekSequence(Math.max(0, playhead - 1))} className="rounded px-2 py-1 text-[10px] text-muted-foreground hover:bg-accent">-1s</button>
                  <button type="button" onClick={() => void togglePlayback()} className="grid h-8 w-8 place-items-center rounded-full bg-foreground text-background">
                    {playing ? <Pause className="h-4 w-4" /> : <Play className="ml-0.5 h-4 w-4" />}
                  </button>
                  <button type="button" onClick={() => seekSequence(Math.min(sequenceDuration, playhead + 1))} className="rounded px-2 py-1 text-[10px] text-muted-foreground hover:bg-accent">+1s</button>
                  <span className="w-20 text-[10px] tabular-nums text-muted-foreground">{formatTime(sequenceDuration)}</span>
                </div>
              </main>

              <aside className="min-h-0 overflow-y-auto border-l border-border/60 bg-[hsl(224_18%_8%)]">
                <PaneTitle title="Inspector" icon={<SlidersHorizontal className="h-3.5 w-3.5" />} detail={selectedSegment ? `selected clip ${segments.findIndex((item) => item.id === selectedSegment.id) + 1}` : ""} />
                <div className="space-y-3 p-3">
                  <InspectorSection title="Live vertical output" icon={<Crop className="h-3.5 w-3.5" />}>
                    <div className="relative mx-auto aspect-[9/16] max-h-[220px] overflow-hidden rounded border border-border/60 bg-black">
                      {monitorKind !== "source" ? <img src={monitorThumbnail} alt="Imported media preview" className="h-full w-full object-contain" /> : previewUrl ? <img src={previewUrl} alt="Vertical output preview" className="h-full w-full object-contain" /> : <div className="grid h-full place-items-center text-[10px] text-muted-foreground">Rendering preview</div>}
                      {monitorKind === "source" && previewBusy && <div className="absolute inset-0 grid place-items-center bg-black/35"><Loader2 className="h-4 w-4 animate-spin text-primary" /></div>}
                    </div>
                  </InspectorSection>

                  <InspectorSection title="Selected segment" icon={<BoxSelect className="h-3.5 w-3.5" />}>
                    <div className="grid grid-cols-2 gap-1">
                      {LAYOUTS.map((option) => (
                        <button key={option.value} type="button" onClick={() => updateSelectedLayout(option.value)} className={cn("rounded border px-2 py-1.5 text-[10px]", selectedSegment?.layout === option.value ? "border-primary bg-primary/15 text-primary" : "border-border/60 text-muted-foreground hover:text-foreground")}>{option.label}</button>
                      ))}
                    </div>
                    {selectedSegment && <div className="mt-2 flex justify-between text-[9px] tabular-nums text-muted-foreground"><span>Source in {formatTime(selectedSegment.sourceStart)}</span><span>out {formatTime(selectedSegment.sourceEnd)}</span></div>}
                    {selectedIsSource && (
                      <button type="button" disabled={trimBusy} onClick={() => void tightenSelectedToPayoff()} className="premium-control mt-2 flex w-full items-center justify-center gap-1.5 rounded px-2 py-1.5 text-[9px] disabled:opacity-50">
                        {trimBusy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Wand2 className="h-3 w-3" />} AI tighten to payoff
                      </button>
                    )}
                    {trimMessage && <p className="mt-1 text-[8px] leading-3 text-emerald-300">{trimMessage}</p>}
                    {selectedSegment?.mediaKind === "image" && (
                      <label className="mt-2 flex items-center gap-2 text-[9px] text-muted-foreground">
                        <span>Still duration</span>
                        <input type="number" min={0.5} max={300} step={0.5} value={Number((selectedSegment.sourceEnd - selectedSegment.sourceStart).toFixed(1))} onChange={(event) => trimSegment(selectedSegment.id, 0, clamp(Number(event.target.value), 0.5, 300))} className="min-w-0 flex-1 rounded border border-border/60 bg-secondary/35 px-2 py-1 text-foreground outline-none" />
                        <span>sec</span>
                      </label>
                    )}
                  </InspectorSection>

                  <InspectorSection title="Presets" icon={<Sparkles className="h-3.5 w-3.5" />}>
                    <div className="flex flex-wrap gap-1">
                      {Object.entries(templates).map(([key, template]) => <button key={key} type="button" onClick={() => applyTemplate(template)} className="rounded-full border border-primary/25 bg-primary/10 px-2 py-1 text-[9px] text-primary hover:bg-primary/20">{template.label ?? key}</button>)}
                      {customPresets.map((preset) => (
                        <div key={preset.id} className="flex overflow-hidden rounded-full border border-amber-300/35 bg-amber-300/10 text-[9px] text-amber-200">
                          <button type="button" onClick={() => applyTemplate(preset)} className="px-2 py-1 hover:bg-amber-300/15">{preset.label}</button>
                          <button type="button" disabled={presetBusy} onClick={() => void deleteCustomPreset(preset.id)} className="border-l border-amber-300/25 px-1.5 hover:bg-destructive/20 hover:text-destructive" aria-label={`Delete ${preset.label} preset`}><X className="h-2.5 w-2.5" /></button>
                        </div>
                      ))}
                    </div>
                    <div className="mt-2 flex gap-1">
                      <input value={presetName} onChange={(event) => setPresetName(event.target.value)} placeholder="Clip Room + chat" className="min-w-0 flex-1 rounded border border-border/60 bg-secondary/35 px-2 py-1 text-[9px] outline-none" />
                      <button type="button" disabled={presetBusy || !selectedIsSource || !presetName.trim()} onClick={() => void saveCustomPreset()} className="rounded border border-border/60 px-2 text-[9px] text-muted-foreground hover:border-primary/45 hover:text-foreground disabled:opacity-40">Save current</button>
                    </div>
                  </InspectorSection>

                  <InspectorSection title="Audio mix" icon={<Volume2 className="h-3.5 w-3.5" />}>
                    <label className="flex items-center justify-between text-[10px]"><span>Normalize loudness</span><input type="checkbox" checked={normalize} onChange={(event) => setNormalize(event.target.checked)} className="accent-cyan-400" /></label>
                    <div className="mt-2 flex items-center gap-2 text-[10px]"><span>Boost</span><input type="range" min={-6} max={18} value={boostDb} onChange={(event) => setBoostDb(Number(event.target.value))} className="min-w-0 flex-1 accent-cyan-400" /><span className="w-10 text-right tabular-nums text-primary">{boostDb} dB</span></div>
                    {fx.length > 0 && (
                      <div className="mt-2 space-y-1.5 border-t border-border/50 pt-2">
                        {fx.map((item) => (
                          <div key={item.id} className="rounded border border-amber-300/20 bg-amber-300/5 p-1.5 text-[9px]">
                            <div className="flex items-center gap-1">
                              <Music2 className="h-3 w-3 text-amber-300" />
                              <span className="min-w-0 flex-1 truncate">{item.name}</span>
                              <button type="button" onClick={() => removeFx(item.id)} className="text-muted-foreground hover:text-destructive" aria-label={`Remove ${item.name}`}><X className="h-3 w-3" /></button>
                            </div>
                            <div className="mt-1 grid grid-cols-[1fr_1.4fr] items-center gap-2 text-[8px] text-muted-foreground">
                              <label className="flex items-center gap-1">At <input type="number" min={0} max={sequenceDuration} step={0.1} value={Number(item.at.toFixed(1))} onChange={(event) => updateFx(item.id, { at: clamp(Number(event.target.value), 0, sequenceDuration) })} className="min-w-0 flex-1 rounded border border-border/50 bg-secondary/40 px-1 py-0.5 text-foreground" /></label>
                              <label className="flex items-center gap-1">Gain <input type="range" min={0} max={2} step={0.05} value={item.gain} onChange={(event) => updateFx(item.id, { gain: Number(event.target.value) })} className="min-w-0 flex-1 accent-amber-400" /><span className="w-5 text-right">{item.gain.toFixed(1)}</span></label>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </InspectorSection>

                  <InspectorSection title="Quick compilation" icon={<ListVideo className="h-3.5 w-3.5" />}>
                    <p className="mb-2 text-[9px] leading-4 text-muted-foreground">Auto-frame each timeline item, with an optional black sound card between clips.</p>
                    <label className="mb-2 flex items-center justify-between rounded border border-border/50 bg-black/15 px-2 py-1.5 text-[9px] text-muted-foreground">
                      <span>Black-screen separator</span>
                      <input type="checkbox" checked={useCompilationTransition} onChange={(event) => setUseCompilationTransition(event.target.checked)} className="accent-amber-400" />
                    </label>
                    <div className="grid grid-cols-2 gap-1">
                      <button type="button" disabled={candidateBusy} onClick={() => void loadCompilationCandidates("keepers")} className="premium-control rounded px-2 py-1.5 text-[9px] disabled:opacity-50">Load keepers</button>
                      <button type="button" disabled={candidateBusy} onClick={() => void loadCompilationCandidates("suggested")} className="rounded border border-emerald-300/35 bg-emerald-300/10 px-2 py-1.5 text-[9px] text-emerald-200 disabled:opacity-50">AI score picks</button>
                    </div>
                    {compilationCandidates.length > 0 && (
                      <div className="mt-2">
                        <div className="max-h-32 space-y-1 overflow-y-auto rounded border border-border/50 bg-black/15 p-1">
                          {compilationCandidates.map((clip) => {
                            const key = compilationCandidateKey(clip);
                            return (
                              <label key={key} className="flex cursor-pointer items-center gap-1.5 rounded px-1.5 py-1 text-[8px] text-muted-foreground hover:bg-accent/40 hover:text-foreground">
                                <input type="checkbox" checked={selectedCandidates.has(key)} onChange={() => toggleCompilationCandidate(clip)} className="accent-emerald-400" />
                                <span className="min-w-0 flex-1 truncate">{clip.name}</span>
                                <span className="tabular-nums text-emerald-300">{clip.score != null ? `${Math.round(clip.score * 100)}%` : "rated"}</span>
                                <span className="tabular-nums">{clip.duration_seconds != null ? `${clip.duration_seconds.toFixed(1)}s` : "?"}</span>
                              </label>
                            );
                          })}
                        </div>
                        <button type="button" disabled={candidateBusy || selectedCandidates.size === 0} onClick={() => void addCompilationCandidates()} className="premium-control mt-1.5 flex w-full items-center justify-center gap-1 rounded px-2 py-1.5 text-[9px] disabled:opacity-40">{candidateBusy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />} Add selected ({selectedCandidates.size})</button>
                      </div>
                    )}
                    <label className={cn("block text-[9px] text-muted-foreground", !useCompilationTransition && "opacity-45")}>Transition style
                      <select disabled={!useCompilationTransition} value={transitionType} onChange={(event) => setTransitionType(event.target.value)} className="mt-1 w-full rounded border border-border/60 bg-secondary/35 px-2 py-1.5 text-[10px] text-foreground outline-none disabled:cursor-not-allowed">
                        <option value="">Black card (with sound)</option>
                        <option value="mix">Mix / crossfade</option>
                        <option value="fade_black">Fade through black</option>
                        <option value="fade_white">Fade through white</option>
                        <option value="bw">Fade to black &amp; white</option>
                      </select>
                    </label>
                    <label className={cn("block text-[9px] text-muted-foreground", (!useCompilationTransition || transitionType !== "") && "opacity-45")}>Compilation sound
                      <select disabled={!useCompilationTransition || transitionType !== ""} value={transitionSound} onChange={(event) => setTransitionSound(event.target.value)} className="mt-1 w-full rounded border border-border/60 bg-secondary/35 px-2 py-1.5 text-[10px] text-foreground outline-none disabled:cursor-not-allowed">
                        <option value="">Silent transition</option>
                        {sounds.map((sound) => <option key={sound.name} value={sound.name}>{sound.name}</option>)}
                      </select>
                    </label>
                    <div className={cn("mt-2 flex items-center gap-2 text-[9px] text-muted-foreground", !useCompilationTransition && "opacity-45")}><span>Black screen</span><input disabled={!useCompilationTransition} type="range" min={0.2} max={3} step={0.1} value={transitionDuration} onChange={(event) => setTransitionDuration(Number(event.target.value))} className="min-w-0 flex-1 accent-amber-400 disabled:cursor-not-allowed" /><span className="w-8 text-right tabular-nums text-amber-300">{transitionDuration.toFixed(1)}s</span></div>
                    <button type="button" disabled={renderBusy !== null} onClick={() => void render("compile")} className="mt-2 flex w-full items-center justify-center gap-1.5 rounded bg-amber-400 px-2 py-2 text-[10px] font-semibold text-black disabled:opacity-50">{renderBusy === "compile" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ListVideo className="h-3.5 w-3.5" />} Build compilation ({segments.length} items)</button>
                  </InspectorSection>

                  <InspectorSection title="Export" icon={<Save className="h-3.5 w-3.5" />}>
                    <input value={outputStem} onChange={(event) => setOutputStem(event.target.value)} className="w-full rounded border border-border/60 bg-secondary/35 px-2 py-1.5 text-[10px] outline-none" />
                    <div className="mt-2 grid grid-cols-2 gap-1.5">
                      <button type="button" disabled={renderBusy !== null || !selectedIsSource} onClick={() => void render("auto")} className="premium-control flex items-center justify-center gap-1 rounded px-2 py-1.5 text-[10px] disabled:opacity-50" title={selectedIsSource ? "Auto edit the source clip" : "Auto edit is available for the original source clip"}>{renderBusy === "auto" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wand2 className="h-3.5 w-3.5" />} Auto</button>
                      <button type="button" disabled={renderBusy !== null} onClick={() => void render("render")} className="flex items-center justify-center gap-1 rounded bg-primary px-2 py-1.5 text-[10px] font-semibold text-primary-foreground disabled:opacity-50">{renderBusy === "render" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Layers3 className="h-3.5 w-3.5" />} Render {segments.length} clip{segments.length === 1 ? "" : "s"}</button>
                    </div>
                    {error && <div className="mt-2 rounded border border-destructive/30 bg-destructive/10 p-2 text-[9px] leading-4 text-destructive">{error}</div>}
                    {renderedStem && <video src={api.edit.videoUrl(renderedStem)} controls className="mt-2 max-h-48 w-full rounded bg-black" />}
                  </InspectorSection>
                </div>
              </aside>
            </div>

            <EditorTimeline
              sourceDuration={probe.duration}
              segments={segments}
              selectedId={selectedId}
              playhead={playhead}
              zoom={zoom}
              fx={fx}
              peaks={peaks}
              thumbnailUrl={thumbnailUrl}
              canUndo={undoStack.length > 0}
              canRedo={redoStack.length > 0}
              onSelect={setSelectedId}
              onSeek={(at) => seekSequence(at, true)}
              onTrim={trimSegment}
              onSplit={splitAtPlayhead}
              onDelete={deleteSelected}
              onDuplicate={duplicateSelected}
              onUndo={undo}
              onRedo={redo}
              onZoom={setZoom}
              onFxMove={(id, at) => setFx((current) => current.map((item) => item.id === id ? { ...item, at } : item))}
            />
          </>
        )}
      </div>
    </div>
  );
}

function PaneTitle({ title, icon, detail }: { title: string; icon?: React.ReactNode; detail?: string }) {
  return <div className="flex h-9 shrink-0 items-center gap-2 border-b border-border/60 bg-[hsl(224_18%_10%)] px-3 text-[10px] font-semibold text-foreground">{icon}<span>{title}</span>{detail && <span className="ml-auto truncate font-normal text-muted-foreground">{detail}</span>}</div>;
}

function InspectorSection({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return <section className="rounded-lg border border-border/55 bg-secondary/15 p-2.5"><div className="mb-2 flex items-center gap-1.5 text-[9px] font-semibold uppercase tracking-[0.14em] text-muted-foreground"><span className="text-primary">{icon}</span>{title}</div>{children}</section>;
}

function SourceStage({
  videoRef,
  mediaUrl,
  mediaKind,
  source,
  layout,
  startAt,
  shouldPlay,
  camBox,
  setCamBox,
  contentBox,
  setContentBox,
  cropBox,
  setCropBox,
  onTimeUpdate,
  onPlay,
  onPause,
}: {
  videoRef: React.RefObject<HTMLVideoElement>;
  mediaUrl: string;
  mediaKind: TimelineMediaKind;
  source: Probe;
  layout: Layout;
  startAt: number;
  shouldPlay: boolean;
  camBox: Box;
  setCamBox: (box: Box) => void;
  contentBox: Box;
  setContentBox: (box: Box) => void;
  cropBox: Box;
  setCropBox: (box: Box) => void;
  onTimeUpdate: () => void;
  onPlay: () => void;
  onPause: () => void;
}) {
  const stageRef = useRef<HTMLDivElement>(null);
  const [stageSize, setStageSize] = useState({ width: 1, height: 1 });
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const update = () => setStageSize({ width: stage.clientWidth, height: stage.clientHeight });
    update();
    const observer = new ResizeObserver(update);
    observer.observe(stage);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={stageRef} className="relative max-h-full max-w-full overflow-hidden bg-black shadow-[0_20px_70px_rgba(0,0,0,.55)]" style={{ width: `min(100%, calc((51vh - 120px) * ${source.width / source.height}))`, aspectRatio: `${source.width}/${source.height}` }}>
      {mediaKind === "image" ? (
        <img src={mediaUrl} alt="Imported timeline still" className="absolute inset-0 h-full w-full object-contain" />
      ) : (
        <video
          key={mediaUrl}
          ref={videoRef}
          src={mediaUrl}
          crossOrigin="anonymous"
          preload="metadata"
          playsInline
          className="absolute inset-0 h-full w-full object-fill"
          onLoadedMetadata={(event) => {
            event.currentTarget.currentTime = startAt;
            if (shouldPlay) void event.currentTarget.play().catch(() => onPause());
          }}
          onTimeUpdate={onTimeUpdate}
          onPlay={onPlay}
          onPause={onPause}
        />
      )}
      {mediaKind === "source" && layout === "reaction" && <><OverlayBox label="Facecam" color="orange" box={camBox} setBox={setCamBox} source={source} stageSize={stageSize} /><OverlayBox label="Content" color="blue" box={contentBox} setBox={setContentBox} source={source} stageSize={stageSize} /></>}
      {mediaKind === "source" && layout === "crop" && <OverlayBox label="9:16 crop" color="green" box={cropBox} setBox={setCropBox} source={source} stageSize={stageSize} />}
      {mediaKind === "source" && layout === "fullcam" && <OverlayBox label="Facecam" color="orange" box={camBox} setBox={setCamBox} source={source} stageSize={stageSize} />}
    </div>
  );
}

function OverlayBox({ label, color, box, setBox, source, stageSize }: { label: string; color: "orange" | "blue" | "green"; box: Box; setBox: (box: Box) => void; source: Probe; stageSize: { width: number; height: number } }) {
  const scaleX = stageSize.width / source.width;
  const scaleY = stageSize.height / source.height;
  const palette = { orange: "border-orange-400 bg-orange-400/10 text-orange-100", blue: "border-sky-400 bg-sky-400/10 text-sky-100", green: "border-emerald-400 bg-emerald-400/10 text-emerald-100" }[color];
  const handleColor = { orange: "bg-orange-300", blue: "bg-sky-300", green: "bg-emerald-300" }[color];

  function beginDrag(event: ReactPointerEvent, handle?: "nw" | "ne" | "sw" | "se") {
    event.preventDefault();
    event.stopPropagation();
    const pointer = { x: event.clientX, y: event.clientY };
    const original = [...box] as Box;
    const move = (next: PointerEvent) => {
      const dx = (next.clientX - pointer.x) / Math.max(scaleX, 0.0001);
      const dy = (next.clientY - pointer.y) / Math.max(scaleY, 0.0001);
      const [x, y, width, height] = original;
      if (!handle) {
        setBox([Math.round(clamp(x + dx, 0, source.width - width)), Math.round(clamp(y + dy, 0, source.height - height)), width, height]);
        return;
      }
      let left = x, top = y, right = x + width, bottom = y + height;
      if (handle.includes("w")) left = clamp(x + dx, 0, right - 80);
      if (handle.includes("e")) right = clamp(x + width + dx, left + 80, source.width);
      if (handle.includes("n")) top = clamp(y + dy, 0, bottom - 80);
      if (handle.includes("s")) bottom = clamp(y + height + dy, top + 80, source.height);
      setBox([Math.round(left), Math.round(top), Math.round(right - left), Math.round(bottom - top)]);
    };
    const stop = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", stop); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop, { once: true });
  }

  return (
    <div className={cn("absolute cursor-move touch-none border-2 shadow-lg", palette)} style={{ left: box[0] * scaleX, top: box[1] * scaleY, width: Math.max(1, box[2] * scaleX), height: Math.max(1, box[3] * scaleY) }} onPointerDown={(event) => beginDrag(event)}>
      <span className="absolute left-1 top-1 rounded bg-black/75 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider">{label}</span>
      {(["nw", "ne", "sw", "se"] as const).map((handle) => <button key={handle} type="button" onPointerDown={(event) => beginDrag(event, handle)} className={cn("absolute h-3 w-3 rounded-sm border border-black/70", handle.includes("n") ? "-top-1.5" : "-bottom-1.5", handle.includes("w") ? "-left-1.5" : "-right-1.5", handleColor)} aria-label={`Resize ${label} ${handle}`} />)}
    </div>
  );
}

function formatTime(value: number) {
  const safe = Number.isFinite(value) ? Math.max(0, value) : 0;
  const minutes = Math.floor(safe / 60);
  const seconds = safe - minutes * 60;
  return `${minutes}:${seconds.toFixed(1).padStart(4, "0")}`;
}

function messageFrom(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}
