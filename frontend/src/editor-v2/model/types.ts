/**
 * Editor V2 — Core type definitions.
 *
 * This is the single source of truth for the multitrack editor project schema.
 * Every component (timeline UI, preview, autosave, FFmpeg renderer) must read
 * and write through these types.
 */

// ---------------------------------------------------------------------------
// Canvas and export
// ---------------------------------------------------------------------------

export type CanvasSettings = {
  width: number;
  height: number;
  fps: number;
  background: string;
};

export type ExportSettings = {
  outputName: string;
  width: number;
  height: number;
  fps: number;
  quality: "draft" | "standard" | "high";
  range: "full" | "in-out";
};

// ---------------------------------------------------------------------------
// Assets
// ---------------------------------------------------------------------------

export type AssetKind = "video" | "image" | "audio" | "caption";
export type AssetOrigin = "source" | "gallery" | "import" | "sound-bin" | "generated" | "local-vod";
export type Bucket = "output" | "positives" | "negatives" | "edited";

export type EditorAsset = {
  id: string;
  kind: AssetKind;
  origin: AssetOrigin;
  name: string;
  bucket?: Bucket;
  stem?: string;
  mediaId?: string;
  path?: string;
  duration: number;
  width?: number;
  height?: number;
  hasAudio: boolean;
  fingerprint: string;
  streamUrl: string;
  thumbnailUrl?: string;
  audioProxyUrl?: string;
  videoProxyUrl?: string;
  waveformUrl?: string;
};

// ---------------------------------------------------------------------------
// Tracks
// ---------------------------------------------------------------------------

export type TrackKind = "video" | "audio" | "caption";

export type EditorTrack = {
  id: string;
  kind: TrackKind;
  name: string;
  order: number;
  muted: boolean;
  solo: boolean;
  locked: boolean;
  hidden: boolean;
  items: TimelineItem[];
};

// ---------------------------------------------------------------------------
// Timeline items
// ---------------------------------------------------------------------------

export type VideoTransform = {
  x: number;
  y: number;
  width: number;
  height: number;
  rotation: number;
  opacity: number;
  blur?: number;
  crop: [number, number, number, number] | null;
  fit: "contain" | "cover" | "stretch";
};

export type AudioSettings = {
  volume: number;
  pan: number;
  fadeIn: number;
  fadeOut: number;
  normalize: boolean;
};

export type CaptionSettings = {
  text: string;
  fontSize: number;
  color: string;
  backgroundColor: string;
  backgroundOpacity: number;
  strokeColor: string;
  strokeWidth: number;
  position: "top" | "center" | "bottom";
  bold: boolean;
  variant?: "subtitle" | "title" | "lower_third";
  animation?: "none" | "fade";
};

export type CreativeTreatment = "cutaway" | "meme" | "pip" | "chat";

export type TransitionKind = "fade_black" | "fade_white" | "mix";

export type TimelineTransition = {
  id: string;
  fromItemId: string;
  toItemId: string;
  kind: TransitionKind;
  duration: number;
};

export type TimelineItem = {
  id: string;
  assetId: string;
  trackId: string;
  timelineStart: number;
  sourceIn: number;
  sourceOut: number;
  /** Playback speed multiplier, 0.25–4.0. */
  speed: number;
  /** Items sharing a linkedGroupId move/trim together. */
  linkedGroupId: string | null;
  enabled: boolean;
  /** Semantic editing intent used by workflow tools and timeline labels. */
  editorRole?: "flashback" | "prelude" | "youtube_intro" | "rough_cut" | "youtube_outro" | "post_credit" | "speech_caption" | "b_roll" | "meme_insert" | "title_card";
  narrativeStage?: "setup" | "rising_action" | "tension" | "climax" | "resolution" | "development";
  storyBeatIds?: string[];
  video?: VideoTransform;
  audio?: AudioSettings;
  caption?: CaptionSettings;
};

// ---------------------------------------------------------------------------
// Project
// ---------------------------------------------------------------------------

export type SelectionState = {
  itemIds: string[];
  focusedTrackId: string | null;
};

export type EditorViewState = {
  pixelsPerSecond: number;
  scrollLeft: number;
};

export type EditorProjectV2 = {
  schemaVersion: 2;
  id: string;
  name: string;
  /** Durable Clip Room origin used to route rendered edits back to Discord. */
  sourceCandidateId?: string;
  contentMode?: "short_form" | "long_form";
  longformPlan?: LongformPlan;
  revision: number;
  createdAt: number;
  updatedAt: number;
  canvas: CanvasSettings;
  assets: Record<string, EditorAsset>;
  tracks: EditorTrack[];
  selection: SelectionState;
  view: EditorViewState;
  playhead: number;
  inPoint: number | null;
  outPoint: number | null;
  export: ExportSettings;
  /** Optional for backwards compatibility with projects created before transitions. */
  transitions?: TimelineTransition[];
};

export type StoryBeatRole = "setup" | "escalation" | "development" | "reaction" | "callback" | "payoff";

export type StoryBeat = {
  id: string;
  index: number;
  role: StoryBeatRole;
  title: string;
  start: number;
  end: number;
  duration: number;
  score: number;
  confidence: number;
  hookScore: number;
  payoffScore: number;
  briefRelevance: number;
  visualDependency: "unknown" | "low" | "high";
  narrativeStage?: "setup" | "rising_action" | "tension" | "climax" | "resolution" | "development";
  mediaSignals?: {
    sceneCuts: number;
    strongestSceneScore: number;
    blackSegments: number;
    visualActivity: number;
  };
  signals: string[];
  text: string;
  boundaryEvidence: {
    firstSegment: string;
    lastSegment: string;
    segmentStartIndex: number;
    segmentEndIndex: number;
  };
};

export type StoryChapter = {
  id: string;
  title: string;
  timelineStart: number;
  timelineEnd: number;
  sourceStart: number;
  sourceEnd: number;
  beatIds: string[];
  role: StoryBeatRole;
};

export type LongformSection = {
  start: number;
  end: number;
  duration: number;
  score: number;
  title: string;
  role: StoryBeatRole;
  roles: StoryBeatRole[];
  beatIds: string[];
  why: string;
  text: string;
  requiredEvents?: string[];
};

export type RequiredEventMatch = {
  query: string;
  matched: boolean;
  included?: boolean;
  beatIds: string[];
  sourceStart: number | null;
  sourceEnd: number | null;
  confidence: number;
  evidence: string;
};

export type StreamContext = {
  inferredType: string;
  selectedType: string;
  selectionMode: "inferred" | "creator_confirmed";
  confidence: number;
  evidence: string[];
  storyContract: string[];
  goal: string;
  requiredEvents: RequiredEventMatch[];
  excludedTopics: string[];
  sourceSegments: Array<{
    id: string;
    title: string;
    sourceStart: number;
    sourceEnd: number;
    anchorBeatId: string;
    role: StoryBeatRole;
    score: number;
  }>;
};

export type StoryQualityReport = {
  grade: "ready" | "review" | "blocked";
  warnings: Array<{ code: string; severity: "review" | "blocker"; message: string }>;
  metrics: { selectedSeconds: number; sourceCoverage: number; targetSeconds: number; roleCoverage: StoryBeatRole[]; arcCoverage?: string[]; requiredEventCoverage?: RequiredEventMatch[] };
};

export type NarrativeArcStage = {
  stage: "setup" | "rising_action" | "tension" | "climax" | "resolution";
  label: string;
  beatIds: string[];
  sourceStart: number;
  sourceEnd: number;
  confidence: number;
  evidence: string[];
  why: string;
};

export type LongformAssemblySegment = {
  kind: "prelude" | "intro" | "story" | "outro" | "post_credit";
  itemId: string;
  title: string;
  timelineStart: number;
  duration: number;
  sourceStart?: number;
  sourceEnd?: number;
  narrativeStage?: string;
  why?: string;
  score?: number;
};

export type YouTubeBrandKit = {
  intro_path: string;
  outro_path: string;
  intro_available?: boolean;
  outro_available?: boolean;
  prelude_enabled: boolean;
  prelude_count: number;
  prelude_clip_seconds: number;
  post_credit_mode: "auto" | "never" | "always";
  post_credit_min_score: number;
};

export type LongformPlan = {
  content_mode?: "long_form";
  strategy: "full_vod" | "rough_cut";
  source?: string;
  vod_stem?: string;
  vod_path?: string;
  transcript_path?: string;
  brief?: string;
  streamContext?: StreamContext;
  target_minutes?: number;
  selected_duration?: number;
  sections?: LongformSection[];
  chapters?: StoryChapter[];
  flashbackSuggestions?: Array<{
    beatId: string;
    title: string;
    role: StoryBeatRole;
    sourceStart: number;
    sourceEnd: number;
    score: number;
    why: string;
    narrativeStage?: string;
  }>;
  narrativeArc?: NarrativeArcStage[];
  assembly?: {
    format: string;
    segments: LongformAssemblySegment[];
    bodyTimelineStart: number;
    timelineDuration: number;
    preludeCount: number;
    introIncluded: boolean;
    outroIncluded: boolean;
    postCreditIncluded: boolean;
  };
  appliedFlashbacks?: string[];
  storyGraph?: {
    version: number;
    duration: number;
    brief: string;
    beats: StoryBeat[];
    narrativeArc?: NarrativeArcStage[];
    streamContext?: StreamContext;
    mediaAnalysis?: {
      version?: number;
      status?: string;
      reason?: string;
      sceneCutCount?: number;
      blackSegmentCount?: number;
      fingerprint?: string;
    };
  };
  qualityReport?: StoryQualityReport;
  youtubePackage?: {
    title: string;
    description: string;
    tags: string[];
    chapterText: string;
    qualityReport: StoryQualityReport;
    review?: {
      captionsReviewed: boolean;
      audioReviewed: boolean;
      rightsCleared: boolean;
      thumbnailReady: boolean;
      finalPlaybackReviewed: boolean;
      notes: string;
    };
  };
  captionsGenerated?: number;
};

// ---------------------------------------------------------------------------
// Computed helpers
// ---------------------------------------------------------------------------

/** The rendered timeline duration of an item: (sourceOut - sourceIn) / speed. */
export function itemDuration(item: TimelineItem): number {
  const speed = Number.isFinite(item.speed) && item.speed > 0 ? item.speed : 1;
  return Math.max(0, item.sourceOut - item.sourceIn) / speed;
}

/** The timeline end position of an item. */
export function itemEnd(item: TimelineItem): number {
  return item.timelineStart + itemDuration(item);
}

// ---------------------------------------------------------------------------
// Default factories
// ---------------------------------------------------------------------------

export const DEFAULT_VIDEO_TRANSFORM: VideoTransform = {
  x: 0,
  y: 0,
  width: 1080,
  height: 1920,
  rotation: 0,
  opacity: 1,
  blur: 0,
  crop: null,
  fit: "contain",
};

export const DEFAULT_AUDIO_SETTINGS: AudioSettings = {
  volume: 1,
  pan: 0,
  fadeIn: 0,
  fadeOut: 0,
  normalize: false,
};

export const DEFAULT_CAPTION_SETTINGS: CaptionSettings = {
  text: "NEW CAPTION",
  fontSize: 76,
  color: "#ffffff",
  backgroundColor: "#000000",
  backgroundOpacity: 0,
  strokeColor: "#000000",
  strokeWidth: 6,
  position: "bottom",
  bold: true,
  variant: "subtitle",
  animation: "none",
};

export const DEFAULT_CANVAS: CanvasSettings = {
  width: 1080,
  height: 1920,
  fps: 30,
  background: "#000000",
};

export const DEFAULT_EXPORT: ExportSettings = {
  outputName: "untitled",
  width: 1080,
  height: 1920,
  fps: 30,
  quality: "standard",
  range: "full",
};

// ---------------------------------------------------------------------------
// Commands — the full union type for the reducer
// ---------------------------------------------------------------------------

export type Command =
  | { type: "ADD_ASSET"; asset: EditorAsset }
  | { type: "ADD_TRACK"; track: Omit<EditorTrack, "items"> }
  | { type: "REMOVE_TRACK"; trackId: string }
  | { type: "REORDER_TRACK"; trackId: string; newOrder: number }
  | { type: "ADD_ITEM"; item: TimelineItem }
  | { type: "MOVE_ITEMS"; itemIds: string[]; deltaTime: number; targetTrackId?: string }
  | { type: "TRIM_ITEM"; itemId: string; edge: "start" | "end"; delta: number }
  | { type: "SPLIT_ITEMS"; itemIds: string[]; time: number }
  | { type: "DELETE_ITEMS"; itemIds: string[] }
  | { type: "COPY_ITEMS"; itemIds: string[] }
  | { type: "CUT_ITEMS"; itemIds: string[] }
  | { type: "PASTE_ITEMS"; time: number; targetTrackId?: string }
  | { type: "DUPLICATE_ITEMS"; itemIds: string[] }
  | { type: "SET_ITEM_SPEED"; itemId: string; speed: number }
  | { type: "SET_ITEM_TRANSFORM"; itemId: string; transform: Partial<VideoTransform> }
  | { type: "SET_ITEM_AUDIO"; itemId: string; audio: Partial<AudioSettings> }
  | { type: "SET_ITEM_CAPTION"; itemId: string; caption: Partial<CaptionSettings> }
  | { type: "APPLY_CREATIVE_TREATMENT"; itemId: string; treatment: CreativeTreatment; targetTrackId?: string }
  | { type: "SET_CHAPTER_TITLE"; chapterId: string; title: string }
  | { type: "SET_YOUTUBE_PACKAGE"; changes: Partial<Pick<NonNullable<LongformPlan["youtubePackage"]>, "title" | "description" | "tags">> }
  | { type: "SET_YOUTUBE_REVIEW"; changes: Partial<NonNullable<NonNullable<LongformPlan["youtubePackage"]>["review"]>> }
  | { type: "SET_ITEM_ENABLED"; itemId: string; enabled: boolean }
  | { type: "SET_TRANSITION"; fromItemId: string; toItemId: string; kind: TransitionKind | null; duration: number }
  | { type: "CREATE_FLASHBACK"; itemId: string; rangeStart: number; rangeEnd: number; insertAt?: number; separatorDuration?: number }
  | { type: "CREATE_SOURCE_FLASHBACK"; assetId: string; trackId: string; sourceIn: number; sourceOut: number; beatId?: string; insertAt?: number; separatorDuration?: number }
  | { type: "DETACH_AUDIO"; itemId: string; newAudioTrackId: string; newAudioItemId: string; linkedGroupId: string }
  | { type: "LINK_ITEMS"; itemIds: string[]; linkedGroupId: string }
  | { type: "UNLINK_ITEMS"; itemIds: string[] }
  | { type: "SET_TRACK_MUTE"; trackId: string; muted: boolean }
  | { type: "SET_TRACK_SOLO"; trackId: string; solo: boolean }
  | { type: "SET_TRACK_LOCK"; trackId: string; locked: boolean }
  | { type: "SET_TRACK_VISIBILITY"; trackId: string; hidden: boolean }
  | { type: "RIPPLE_DELETE"; itemIds: string[]; trackId: string }
  | { type: "INSERT_GAP"; trackId: string; time: number; duration: number }
  | { type: "SET_PLAYHEAD"; time: number }
  | { type: "SET_SELECTION"; itemIds: string[]; focusedTrackId: string | null }
  | { type: "SET_IN_OUT"; inPoint: number | null; outPoint: number | null }
  | { type: "SET_CANVAS"; canvas: Partial<CanvasSettings> }
  | { type: "SET_EXPORT"; export: Partial<ExportSettings> }
  | { type: "SET_VIEW"; view: Partial<EditorViewState> };

// ---------------------------------------------------------------------------
// Clipboard state (not persisted, runtime-only)
// ---------------------------------------------------------------------------

export type ClipboardEntry = {
  /** Snapshot of copied items with original IDs — paste generates new IDs. */
  items: TimelineItem[];
  /** The earliest timelineStart in the copied set, used as the anchor offset. */
  anchorTime: number;
  /** Track IDs of the copied items for relative track offset calculation. */
  trackIds: string[];
};
