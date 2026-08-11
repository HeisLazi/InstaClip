/**
 * Editor V2 — Pure selectors over EditorProjectV2.
 *
 * Every selector is a pure function: same project → same result.
 * No mutation, no side-effects.
 */

import type {
  EditorProjectV2,
  EditorTrack,
  TimelineItem,
} from "./types";
import { itemDuration, itemEnd } from "./types";

// ---------------------------------------------------------------------------
// Track queries
// ---------------------------------------------------------------------------

/** All tracks sorted by ascending order (V1 first, then V2, …, A1, A2, …). */
export function tracksByOrder(project: EditorProjectV2): EditorTrack[] {
  return [...project.tracks].sort((a, b) => a.order - b.order);
}

/** Find a track by ID. */
export function trackById(project: EditorProjectV2, trackId: string): EditorTrack | undefined {
  return project.tracks.find((t) => t.id === trackId);
}

/** All video tracks sorted by order (higher order = renders on top). */
export function videoTracks(project: EditorProjectV2): EditorTrack[] {
  return tracksByOrder(project).filter((t) => t.kind === "video");
}

/** All audio tracks sorted by order. */
export function audioTracks(project: EditorProjectV2): EditorTrack[] {
  return tracksByOrder(project).filter((t) => t.kind === "audio");
}

// ---------------------------------------------------------------------------
// Item queries
// ---------------------------------------------------------------------------

/** All items across all tracks. */
export function allItems(project: EditorProjectV2): TimelineItem[] {
  return project.tracks.flatMap((t) => t.items);
}

/** Find a specific item and its parent track. */
export function findItem(
  project: EditorProjectV2,
  itemId: string,
): { item: TimelineItem; track: EditorTrack } | undefined {
  for (const track of project.tracks) {
    const item = track.items.find((i) => i.id === itemId);
    if (item) return { item, track };
  }
  return undefined;
}

/** Get the currently selected items. */
export function selectedItems(project: EditorProjectV2): TimelineItem[] {
  const ids = new Set(project.selection.itemIds);
  return allItems(project).filter((i) => ids.has(i.id));
}

// ---------------------------------------------------------------------------
// Duration / time queries
// ---------------------------------------------------------------------------

/** Compute the timeline duration of a single item. Re-export for convenience. */
export { itemDuration, itemEnd };

/**
 * Total project duration = the latest `itemEnd()` across all tracks.
 * Returns 0 for an empty project.
 */
export function projectDuration(project: EditorProjectV2): number {
  let maxEnd = 0;
  for (const track of project.tracks) {
    for (const item of track.items) {
      const end = itemEnd(item);
      if (end > maxEnd) maxEnd = end;
    }
  }
  return maxEnd;
}

/**
 * Items that are "active" (audible/visible) at the given playhead time.
 * An item is active when `timelineStart <= time < timelineStart + duration`.
 */
export function activeItemsAtTime(
  project: EditorProjectV2,
  time: number,
): { item: TimelineItem; track: EditorTrack }[] {
  const result: { item: TimelineItem; track: EditorTrack }[] = [];
  for (const track of project.tracks) {
    for (const item of track.items) {
      if (!item.enabled) continue;
      const start = item.timelineStart;
      const end = itemEnd(item);
      if (time >= start && time < end) {
        result.push({ item, track });
      }
    }
  }
  return result;
}

/**
 * Active video items at the given time, sorted bottom-to-top for rendering
 * (lower track order first — rendered underneath higher ones).
 */
export function activeVideoItemsAtTime(
  project: EditorProjectV2,
  time: number,
): { item: TimelineItem; track: EditorTrack }[] {
  return activeItemsAtTime(project, time)
    .filter(({ track }) => track.kind === "video" && !track.hidden)
    .sort((a, b) => a.track.order - b.track.order);
}

/**
 * Active audio items at the given time, respecting mute and solo.
 */
export function activeAudioItemsAtTime(
  project: EditorProjectV2,
  time: number,
): { item: TimelineItem; track: EditorTrack }[] {
  const allAudio = activeItemsAtTime(project, time)
    .filter(({ track }) => track.kind === "audio");

  // If any audio track is soloed, only include soloed tracks
  const hasSolo = project.tracks.some((t) => t.kind === "audio" && t.solo);
  return allAudio.filter(({ track }) => {
    if (track.muted) return false;
    if (hasSolo && !track.solo) return false;
    return true;
  });
}

// ---------------------------------------------------------------------------
// Linked media queries
// ---------------------------------------------------------------------------

/**
 * Get all items sharing the same linkedGroupId.
 * Returns empty array if the item has no linked group.
 */
export function linkedItems(
  project: EditorProjectV2,
  linkedGroupId: string | null,
): TimelineItem[] {
  if (!linkedGroupId) return [];
  return allItems(project).filter((i) => i.linkedGroupId === linkedGroupId);
}

/**
 * Get the linked group members for a specific item.
 */
export function linkedSiblings(
  project: EditorProjectV2,
  itemId: string,
): TimelineItem[] {
  const found = findItem(project, itemId);
  if (!found || !found.item.linkedGroupId) return [];
  return linkedItems(project, found.item.linkedGroupId).filter(
    (i) => i.id !== itemId,
  );
}

// ---------------------------------------------------------------------------
// Overlap detection
// ---------------------------------------------------------------------------

/**
 * Check whether a proposed placement would overlap any existing item on the
 * same track. Returns the overlapping items if any.
 */
export function overlappingItems(
  track: EditorTrack,
  start: number,
  duration: number,
  excludeItemId?: string,
): TimelineItem[] {
  const end = start + duration;
  return track.items.filter((existing) => {
    if (excludeItemId && existing.id === excludeItemId) return false;
    const eStart = existing.timelineStart;
    const eEnd = itemEnd(existing);
    return start < eEnd && end > eStart;
  });
}

// ---------------------------------------------------------------------------
// Asset queries
// ---------------------------------------------------------------------------

/** Get all items referencing a given asset. */
export function itemsForAsset(
  project: EditorProjectV2,
  assetId: string,
): TimelineItem[] {
  return allItems(project).filter((i) => i.assetId === assetId);
}

/** Get all asset IDs that are actually used by at least one timeline item. */
export function usedAssetIds(project: EditorProjectV2): Set<string> {
  return new Set(allItems(project).map((i) => i.assetId));
}

/** Get assets that have no timeline items referencing them (orphaned). */
export function orphanedAssets(project: EditorProjectV2): string[] {
  const used = usedAssetIds(project);
  return Object.keys(project.assets).filter((id) => !used.has(id));
}
