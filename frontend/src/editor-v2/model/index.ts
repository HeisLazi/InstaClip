/**
 * Editor V2 Model — Barrel export.
 *
 * Public API surface for the editor-v2 data model.
 */

// Types
export type {
  EditorProjectV2,
  EditorAsset,
  EditorTrack,
  TimelineItem,
  VideoTransform,
  AudioSettings,
  CaptionSettings,
  TransitionKind,
  TimelineTransition,
  CanvasSettings,
  ExportSettings,
  SelectionState,
  EditorViewState,
  AssetKind,
  AssetOrigin,
  Bucket,
  TrackKind,
  CreativeTreatment,
  StoryBeat,
  StoryBeatRole,
  StoryChapter,
  LongformSection,
  LongformPlan,
  NarrativeArcStage,
  LongformAssemblySegment,
  RequiredEventMatch,
  StreamContext,
  YouTubeBrandKit,
  Command,
  ClipboardEntry,
} from "./types";

export {
  itemDuration,
  itemEnd,
  DEFAULT_VIDEO_TRANSFORM,
  DEFAULT_AUDIO_SETTINGS,
  DEFAULT_CAPTION_SETTINGS,
  DEFAULT_CANVAS,
  DEFAULT_EXPORT,
} from "./types";

// IDs
export {
  uid,
  newProjectId,
  newAssetId,
  newTrackId,
  newItemId,
  newLinkedGroupId,
} from "./ids";

// Reducer
export { reduce, cloneProject } from "./reducer";
export type { ReducerResult } from "./reducer";

// Selectors
export {
  tracksByOrder,
  trackById,
  videoTracks,
  audioTracks,
  allItems,
  findItem,
  selectedItems,
  projectDuration,
  activeItemsAtTime,
  activeVideoItemsAtTime,
  activeAudioItemsAtTime,
  linkedItems,
  linkedSiblings,
  overlappingItems,
  itemsForAsset,
  usedAssetIds,
  orphanedAssets,
} from "./selectors";
export { buildYouTubePreflight, type PreflightCheck } from "./preflight";

// History
export {
  createHistory,
  applyCommand,
  undo,
  redo,
  canUndo,
  canRedo,
} from "./history";
export type { HistoryEntry, EditorHistory } from "./history";

// Serialization
export {
  CURRENT_SCHEMA_VERSION,
  serializeProject,
  deserializeProject,
  migrateProject,
} from "./serialization";

// Fixture
export { createFixtureProject } from "./fixture";
