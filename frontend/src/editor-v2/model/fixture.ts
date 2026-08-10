/**
 * Editor V2 — Test fixture project.
 *
 * A fully populated project with:
 *   V1 (video track, order 0): primary storyline clip
 *   V2 (video track, order 1): overlay image
 *   A1 (audio track, order 10): source audio (detached from V1)
 *   A2 (audio track, order 11): two overlapping "boom" sound FX
 *
 * This fixture is used for unit tests and serves as the EV2-01 acceptance
 * artifact: all reducer commands must be able to edit it, and it must
 * serialize/deserialize without loss.
 */

import type { EditorProjectV2, EditorAsset, EditorTrack, TimelineItem } from "./types";

// ---------------------------------------------------------------------------
// Assets
// ---------------------------------------------------------------------------

const sourceClipAsset: EditorAsset = {
  id: "ast_source_clip",
  kind: "video",
  origin: "source",
  name: "gameplay_clip.mp4",
  bucket: "output",
  stem: "gameplay_clip",
  duration: 30.0,
  width: 1920,
  height: 1080,
  hasAudio: true,
  fingerprint: "sha256_source_clip_001",
  streamUrl: "/edit/v2/assets/ast_source_clip/stream",
  thumbnailUrl: "/edit/v2/assets/ast_source_clip/thumbnail",
  audioProxyUrl: "/edit/v2/assets/ast_source_clip/audio-proxy",
  waveformUrl: "/edit/v2/assets/ast_source_clip/waveform?points=2000",
};

const overlayImageAsset: EditorAsset = {
  id: "ast_overlay_img",
  kind: "image",
  origin: "import",
  name: "overlay_banner.png",
  duration: 0, // images have no inherent duration
  width: 800,
  height: 200,
  hasAudio: false,
  fingerprint: "sha256_overlay_img_001",
  streamUrl: "/edit/v2/assets/ast_overlay_img/stream",
  thumbnailUrl: "/edit/v2/assets/ast_overlay_img/thumbnail",
};

const boomAsset: EditorAsset = {
  id: "ast_boom",
  kind: "audio",
  origin: "sound-bin",
  name: "boom.mp4",
  stem: "boom",
  duration: 4.757,
  hasAudio: true,
  fingerprint: "sha256_boom_001",
  streamUrl: "/edit/v2/assets/ast_boom/stream",
  audioProxyUrl: "/edit/v2/assets/ast_boom/audio-proxy",
  waveformUrl: "/edit/v2/assets/ast_boom/waveform?points=2000",
};

// ---------------------------------------------------------------------------
// Timeline items
// ---------------------------------------------------------------------------

const v1MainClip: TimelineItem = {
  id: "itm_v1_main",
  assetId: "ast_source_clip",
  trackId: "trk_v1",
  timelineStart: 0,
  sourceIn: 2.0,
  sourceOut: 20.0,
  speed: 1.0,
  linkedGroupId: "lnk_source_av",
  enabled: true,
  video: {
    x: 0,
    y: 0,
    width: 1920,
    height: 1080,
    rotation: 0,
    opacity: 1,
    crop: null,
    fit: "contain",
  },
  audio: {
    volume: 0, // muted because audio is detached to A1
    pan: 0,
    fadeIn: 0,
    fadeOut: 0,
    normalize: false,
  },
};

const v2OverlayImage: TimelineItem = {
  id: "itm_v2_overlay",
  assetId: "ast_overlay_img",
  trackId: "trk_v2",
  timelineStart: 3.0,
  sourceIn: 0,
  sourceOut: 5.0, // display for 5 seconds
  speed: 1.0,
  linkedGroupId: null,
  enabled: true,
  video: {
    x: 560,
    y: 50,
    width: 800,
    height: 200,
    rotation: 0,
    opacity: 0.85,
    crop: null,
    fit: "contain",
  },
};

const a1DetachedAudio: TimelineItem = {
  id: "itm_a1_detached",
  assetId: "ast_source_clip",
  trackId: "trk_a1",
  timelineStart: 0,
  sourceIn: 2.0,
  sourceOut: 20.0,
  speed: 1.0,
  linkedGroupId: "lnk_source_av",
  enabled: true,
  audio: {
    volume: 1.0,
    pan: 0,
    fadeIn: 0.1,
    fadeOut: 0.5,
    normalize: false,
  },
};

const a2Boom1: TimelineItem = {
  id: "itm_a2_boom1",
  assetId: "ast_boom",
  trackId: "trk_a2",
  timelineStart: 5.0,
  sourceIn: 0,
  sourceOut: 4.757,
  speed: 1.0,
  linkedGroupId: null,
  enabled: true,
  audio: {
    volume: 0.8,
    pan: -0.3,
    fadeIn: 0,
    fadeOut: 0.2,
    normalize: false,
  },
};

const a2Boom2: TimelineItem = {
  id: "itm_a2_boom2",
  assetId: "ast_boom",
  trackId: "trk_a2",
  timelineStart: 7.0, // overlaps boom1 (boom1 ends at 5 + 4.757 = 9.757)
  sourceIn: 0,
  sourceOut: 4.757,
  speed: 1.0,
  linkedGroupId: null,
  enabled: true,
  audio: {
    volume: 1.0,
    pan: 0.3,
    fadeIn: 0,
    fadeOut: 0.2,
    normalize: false,
  },
};

// ---------------------------------------------------------------------------
// Tracks
// ---------------------------------------------------------------------------

const trackV1: EditorTrack = {
  id: "trk_v1",
  kind: "video",
  name: "V1",
  order: 0,
  muted: false,
  solo: false,
  locked: false,
  hidden: false,
  items: [v1MainClip],
};

const trackV2: EditorTrack = {
  id: "trk_v2",
  kind: "video",
  name: "V2",
  order: 1,
  muted: false,
  solo: false,
  locked: false,
  hidden: false,
  items: [v2OverlayImage],
};

const trackA1: EditorTrack = {
  id: "trk_a1",
  kind: "audio",
  name: "A1",
  order: 10,
  muted: false,
  solo: false,
  locked: false,
  hidden: false,
  items: [a1DetachedAudio],
};

const trackA2: EditorTrack = {
  id: "trk_a2",
  kind: "audio",
  name: "A2",
  order: 11,
  muted: false,
  solo: false,
  locked: false,
  hidden: false,
  items: [a2Boom1, a2Boom2],
};

// ---------------------------------------------------------------------------
// Fixture project factory
// ---------------------------------------------------------------------------

/**
 * Create a fresh copy of the fixture project.
 * Each call returns a new object — safe for mutation in tests.
 */
export function createFixtureProject(): EditorProjectV2 {
  const project: EditorProjectV2 = {
    schemaVersion: 2,
    id: "proj_fixture_001",
    name: "Test Fixture — Multitrack Demo",
    revision: 1,
    createdAt: 1719500000000,
    updatedAt: 1719500000000,
    canvas: {
      width: 1920,
      height: 1080,
      fps: 30,
      background: "#000000",
    },
    assets: {
      [sourceClipAsset.id]: { ...sourceClipAsset },
      [overlayImageAsset.id]: { ...overlayImageAsset },
      [boomAsset.id]: { ...boomAsset },
    },
    tracks: [
      JSON.parse(JSON.stringify(trackV1)),
      JSON.parse(JSON.stringify(trackV2)),
      JSON.parse(JSON.stringify(trackA1)),
      JSON.parse(JSON.stringify(trackA2)),
    ],
    selection: {
      itemIds: [],
      focusedTrackId: null,
    },
    view: { pixelsPerSecond: 64, scrollLeft: 0 },
    playhead: 0,
    inPoint: null,
    outPoint: null,
    export: {
      outputName: "fixture_render",
      width: 1920,
      height: 1080,
      fps: 30,
      quality: "standard",
      range: "full",
    },
    transitions: [],
  };

  return JSON.parse(JSON.stringify(project));
}
