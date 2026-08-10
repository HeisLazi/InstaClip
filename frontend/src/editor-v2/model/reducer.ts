/**
 * Editor V2 — Pure command reducer.
 *
 * Every command is deterministic: same (project, command) → same result.
 * Commands never read runtime state (DOM, audio nodes, network).
 * Undo/redo is handled externally by snapshotting the project before each
 * command (see history.ts).
 */

import type {
  EditorProjectV2,
  EditorTrack,
  TimelineItem,
  Command,
  ClipboardEntry,
} from "./types";
import { itemDuration, itemEnd } from "./types";

// ---------------------------------------------------------------------------
// Helper: deep-clone a project (structuredClone-safe)
// ---------------------------------------------------------------------------

export function cloneProject(project: EditorProjectV2): EditorProjectV2 {
  return JSON.parse(JSON.stringify(project));
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function findTrack(project: EditorProjectV2, trackId: string): EditorTrack {
  const t = project.tracks.find((t) => t.id === trackId);
  if (!t) throw new Error(`Track not found: ${trackId}`);
  return t;
}

function findItemInProject(
  project: EditorProjectV2,
  itemId: string,
): { item: TimelineItem; track: EditorTrack } {
  for (const track of project.tracks) {
    const item = track.items.find((i) => i.id === itemId);
    if (item) return { item, track };
  }
  throw new Error(`Item not found: ${itemId}`);
}

function removeItemFromTrack(track: EditorTrack, itemId: string): void {
  track.items = track.items.filter((i) => i.id !== itemId);
}

function clampSpeed(speed: number): number {
  return Math.max(0.25, Math.min(4.0, speed));
}

function chapterClock(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`
    : `${minutes}:${String(secs).padStart(2, "0")}`;
}

function refreshChapterText(project: EditorProjectV2): void {
  const chapters = [...(project.longformPlan?.chapters ?? [])]
    .sort((left, right) => left.timelineStart - right.timelineStart);
  if (project.longformPlan?.youtubePackage) {
    project.longformPlan.youtubePackage.chapterText = chapters
      .map((chapter) => `${chapterClock(chapter.timelineStart)} ${chapter.title}`)
      .join("\n");
  }
}

function shiftLongformChapters(project: EditorProjectV2, insertAt: number, delta: number): void {
  const chapters = project.longformPlan?.chapters ?? [];
  for (const chapter of chapters) {
    if (chapter.timelineStart >= insertAt) {
      chapter.timelineStart += delta;
      chapter.timelineEnd += delta;
    }
  }
  refreshChapterText(project);
}

function upsertColdOpenChapter(
  project: EditorProjectV2,
  insertAt: number,
  insertedDuration: number,
  sourceStart: number,
  sourceEnd: number,
  beatId?: string,
): void {
  const chapters = project.longformPlan?.chapters;
  if (!chapters) return;
  const existing = chapters.find((chapter) => chapter.id === "chapter_cold_open");
  if (existing && insertAt <= existing.timelineEnd + 0.01) {
    existing.timelineEnd += insertedDuration;
    if (beatId && !existing.beatIds.includes(beatId)) existing.beatIds.push(beatId);
  } else if (!existing && insertAt <= 0.01) {
    chapters.push({
      id: "chapter_cold_open",
      title: "Cold open",
      timelineStart: 0,
      timelineEnd: insertedDuration,
      sourceStart,
      sourceEnd,
      beatIds: beatId ? [beatId] : [],
      role: "payoff",
    });
  }
  chapters.sort((left, right) => left.timelineStart - right.timelineStart);
  refreshChapterText(project);
}

function allItems(project: EditorProjectV2): TimelineItem[] {
  return project.tracks.flatMap((track) => track.items);
}

function expandLinkedItemIds(project: EditorProjectV2, itemIds: string[]): string[] {
  const expanded = new Set(itemIds);
  const groups = new Set<string>();
  for (const id of itemIds) {
    const found = allItems(project).find((item) => item.id === id);
    if (found?.linkedGroupId) groups.add(found.linkedGroupId);
  }
  for (const item of allItems(project)) {
    if (item.linkedGroupId && groups.has(item.linkedGroupId)) expanded.add(item.id);
  }
  return [...expanded];
}

function isCompatible(track: EditorTrack, item: TimelineItem): boolean {
  if (track.kind === "video") return Boolean(item.video);
  if (track.kind === "audio") return Boolean(item.audio) && !item.video;
  return Boolean(item.caption);
}

function requireEditable(track: EditorTrack): void {
  if (track.locked) throw new Error(`Track is locked: ${track.id}`);
}

function requireCompatible(track: EditorTrack, item: TimelineItem): void {
  if (!isCompatible(track, item)) {
    throw new Error(`Item ${item.id} is incompatible with ${track.kind} track ${track.id}`);
  }
}

function clearSingletonLinks(project: EditorProjectV2): void {
  const counts = new Map<string, number>();
  for (const item of allItems(project)) {
    if (item.linkedGroupId) counts.set(item.linkedGroupId, (counts.get(item.linkedGroupId) ?? 0) + 1);
  }
  for (const item of allItems(project)) {
    if (item.linkedGroupId && (counts.get(item.linkedGroupId) ?? 0) < 2) item.linkedGroupId = null;
  }
}

// ---------------------------------------------------------------------------
// Reducer
// ---------------------------------------------------------------------------

export type ReducerResult = {
  project: EditorProjectV2;
  /** Updated clipboard — only changed by COPY_ITEMS, CUT_ITEMS. */
  clipboard: ClipboardEntry | null;
};

/**
 * Apply a command to a project, returning a new project.
 * The input project is NOT mutated — we clone before modifying.
 */
export function reduce(
  project: EditorProjectV2,
  command: Command,
  clipboard: ClipboardEntry | null = null,
): ReducerResult {
  // Clone so the reducer is pure (no mutation of input)
  const p = cloneProject(project);
  let cb = clipboard;
  let generatedSequence = 0;
  const generatedIds = new Set([
    ...Object.keys(p.assets),
    ...p.tracks.map((track) => track.id),
    ...allItems(p).map((item) => item.id),
    ...allItems(p).flatMap((item) => item.linkedGroupId ? [item.linkedGroupId] : []),
  ]);
  const nextId = (prefix: "itm" | "lnk"): string => {
    let candidate: string;
    do {
      candidate = `${prefix}_r${project.revision + 1}_${generatedSequence++}`;
    } while (generatedIds.has(candidate));
    generatedIds.add(candidate);
    return candidate;
  };

  switch (command.type) {
    // ----- Assets -----
    case "ADD_ASSET": {
      p.assets[command.asset.id] = { ...command.asset };
      break;
    }

    // ----- Tracks -----
    case "ADD_TRACK": {
      if (p.tracks.some((track) => track.id === command.track.id)) {
        throw new Error(`Track already exists: ${command.track.id}`);
      }
      p.tracks.push({ ...command.track, items: [] });
      break;
    }

    case "REMOVE_TRACK": {
      requireEditable(findTrack(p, command.trackId));
      p.tracks = p.tracks.filter((t) => t.id !== command.trackId);
      // Remove selection for items on the removed track
      const removedIds = new Set(
        project.tracks
          .find((t) => t.id === command.trackId)
          ?.items.map((i) => i.id) ?? [],
      );
      p.selection.itemIds = p.selection.itemIds.filter((id) => !removedIds.has(id));
      if (p.selection.focusedTrackId === command.trackId) {
        p.selection.focusedTrackId = null;
      }
      clearSingletonLinks(p);
      break;
    }

    case "REORDER_TRACK": {
      const track = findTrack(p, command.trackId);
      requireEditable(track);
      track.order = command.newOrder;
      break;
    }

    // ----- Items -----
    case "ADD_ITEM": {
      const track = findTrack(p, command.item.trackId);
      requireEditable(track);
      if (!p.assets[command.item.assetId]) throw new Error(`Asset not found: ${command.item.assetId}`);
      if (allItems(p).some((item) => item.id === command.item.id)) throw new Error(`Item already exists: ${command.item.id}`);
      requireCompatible(track, command.item);
      track.items.push({ ...command.item });
      break;
    }

    case "MOVE_ITEMS": {
      const explicitIds = new Set(command.itemIds);
      const itemIds = expandLinkedItemIds(p, command.itemIds);
      const starts = itemIds.map((id) => findItemInProject(p, id).item.timelineStart);
      const deltaTime = starts.length > 0
        ? Math.max(command.deltaTime, -Math.min(...starts))
        : command.deltaTime;
      for (const itemId of itemIds) {
        const { item, track } = findItemInProject(p, itemId);
        requireEditable(track);

        if (explicitIds.has(itemId) && command.targetTrackId && command.targetTrackId !== track.id) {
          // Move to a different track
          removeItemFromTrack(track, itemId);
          const targetTrack = findTrack(p, command.targetTrackId);
          requireEditable(targetTrack);
          requireCompatible(targetTrack, item);
          item.trackId = command.targetTrackId;
          item.timelineStart += deltaTime;
          targetTrack.items.push(item);
        } else {
          item.timelineStart += deltaTime;
        }
      }
      break;
    }

    case "TRIM_ITEM": {
      const { item, track } = findItemInProject(p, command.itemId);
      requireEditable(track);
      const asset = p.assets[item.assetId];
      let appliedDelta = command.delta;
      if (command.edge === "start") {
        const maxDelta = item.sourceOut - item.sourceIn - 0.001; // don't collapse to zero
        const minDelta = Math.max(-item.sourceIn, -item.timelineStart * item.speed);
        appliedDelta = Math.max(minDelta, Math.min(command.delta, maxDelta));
      } else {
        const minOut = item.sourceIn + 0.001;
        const maxOut = item.caption ? Number.POSITIVE_INFINITY
          : asset?.duration && asset.duration > 0 ? asset.duration : Number.POSITIVE_INFINITY;
        appliedDelta = Math.max(minOut - item.sourceOut, Math.min(command.delta, maxOut - item.sourceOut));
      }

      for (const linkedId of expandLinkedItemIds(p, [command.itemId])) {
        const linked = findItemInProject(p, linkedId);
        requireEditable(linked.track);
        if (command.edge === "start") {
          const maxDelta = linked.item.sourceOut - linked.item.sourceIn - 0.001;
          const minDelta = Math.max(-linked.item.sourceIn, -linked.item.timelineStart * linked.item.speed);
          const delta = Math.max(minDelta, Math.min(appliedDelta, maxDelta));
          linked.item.sourceIn += delta;
          linked.item.timelineStart += delta / linked.item.speed;
        } else {
          const linkedAsset = p.assets[linked.item.assetId];
          const maxOut = linked.item.caption ? Number.POSITIVE_INFINITY
            : linkedAsset?.duration && linkedAsset.duration > 0 ? linkedAsset.duration : Number.POSITIVE_INFINITY;
          linked.item.sourceOut = Math.max(
            linked.item.sourceIn + 0.001,
            Math.min(linked.item.sourceOut + appliedDelta, maxOut),
          );
        }
      }
      break;
    }

    case "SPLIT_ITEMS": {
      const rightLinkIds = new Map<string, string>();
      for (const itemId of expandLinkedItemIds(p, command.itemIds)) {
        const { item, track } = findItemInProject(p, itemId);
        requireEditable(track);
        const dur = itemDuration(item);
        const splitAt = command.time;

        // Only split if the time is within the item bounds
        if (splitAt <= item.timelineStart || splitAt >= item.timelineStart + dur) {
          continue;
        }

        // Compute source time at the split point
        const localTime = (splitAt - item.timelineStart) * item.speed;
        const splitSourceTime = item.sourceIn + localTime;

        // Create the right half
        const rightItem: TimelineItem = {
          ...JSON.parse(JSON.stringify(item)),
          id: nextId("itm"),
          sourceIn: splitSourceTime,
          timelineStart: splitAt,
        };

        if (item.linkedGroupId) {
          if (!rightLinkIds.has(item.linkedGroupId)) rightLinkIds.set(item.linkedGroupId, nextId("lnk"));
          rightItem.linkedGroupId = rightLinkIds.get(item.linkedGroupId)!;
        }

        // Trim the left half
        item.sourceOut = splitSourceTime;

        track.items.push(rightItem);
      }
      break;
    }

    case "DELETE_ITEMS": {
      const deleteSet = new Set(expandLinkedItemIds(p, command.itemIds));
      for (const track of p.tracks) {
        if (track.items.some((item) => deleteSet.has(item.id))) requireEditable(track);
        track.items = track.items.filter((i) => !deleteSet.has(i.id));
      }
      p.selection.itemIds = p.selection.itemIds.filter((id) => !deleteSet.has(id));
      p.transitions = (p.transitions ?? []).filter((transition) =>
        !deleteSet.has(transition.fromItemId) && !deleteSet.has(transition.toItemId));
      clearSingletonLinks(p);
      break;
    }

    // ----- Clipboard -----
    case "COPY_ITEMS": {
      const items = expandLinkedItemIds(project, command.itemIds)
        .map((id) => {
          try { return findItemInProject(project, id).item; } catch { return null; }
        })
        .filter((i): i is TimelineItem => i !== null);

      if (items.length > 0) {
        const anchorTime = Math.min(...items.map((i) => i.timelineStart));
        cb = {
          items: JSON.parse(JSON.stringify(items)),
          anchorTime,
          trackIds: items.map((i) => i.trackId),
        };
      }
      break;
    }

    case "CUT_ITEMS": {
      // Copy first
      const cutIds = expandLinkedItemIds(project, command.itemIds);
      const items = cutIds
        .map((id) => {
          try { return findItemInProject(project, id).item; } catch { return null; }
        })
        .filter((i): i is TimelineItem => i !== null);

      if (items.length > 0) {
        const anchorTime = Math.min(...items.map((i) => i.timelineStart));
        cb = {
          items: JSON.parse(JSON.stringify(items)),
          anchorTime,
          trackIds: items.map((i) => i.trackId),
        };
      }

      // Then delete
      const deleteSet = new Set(cutIds);
      for (const track of p.tracks) {
        if (track.items.some((item) => deleteSet.has(item.id))) requireEditable(track);
        track.items = track.items.filter((i) => !deleteSet.has(i.id));
      }
      p.selection.itemIds = p.selection.itemIds.filter((id) => !deleteSet.has(id));
      clearSingletonLinks(p);
      break;
    }

    case "PASTE_ITEMS": {
      if (!cb || cb.items.length === 0) break;

      // Build a map from original linked group IDs to new ones
      const linkMap = new Map<string, string>();
      const newIds: string[] = [];

      for (const original of cb.items) {
        const newId = nextId("itm");
        newIds.push(newId);

        // Determine linked group
        let newLinkId: string | null = null;
        if (original.linkedGroupId) {
          if (!linkMap.has(original.linkedGroupId)) {
            linkMap.set(original.linkedGroupId, nextId("lnk"));
          }
          newLinkId = linkMap.get(original.linkedGroupId)!;
        }

        const timeOffset = original.timelineStart - cb.anchorTime;
        const targetTrackId = command.targetTrackId || original.trackId;

        const pasted: TimelineItem = {
          ...JSON.parse(JSON.stringify(original)),
          id: newId,
          trackId: targetTrackId,
          timelineStart: command.time + timeOffset,
          linkedGroupId: newLinkId,
        };

        // Place on the target track (create if missing)
        let track = p.tracks.find((t) => t.id === targetTrackId);
        if (!track) {
          track = p.tracks.find((t) => t.id === original.trackId);
        }
        if (track) {
          requireEditable(track);
          requireCompatible(track, pasted);
          track.items.push(pasted);
        }
      }

      p.selection.itemIds = newIds;
      break;
    }

    case "DUPLICATE_ITEMS": {
      const newIds: string[] = [];
      const linkMap = new Map<string, string>();

      for (const itemId of expandLinkedItemIds(p, command.itemIds)) {
        const { item, track } = findItemInProject(p, itemId);
        requireEditable(track);
        const dur = itemDuration(item);
        const newId = nextId("itm");
        newIds.push(newId);

        let newLinkId: string | null = null;
        if (item.linkedGroupId) {
          if (!linkMap.has(item.linkedGroupId)) {
            linkMap.set(item.linkedGroupId, nextId("lnk"));
          }
          newLinkId = linkMap.get(item.linkedGroupId)!;
        }

        const duplicate: TimelineItem = {
          ...JSON.parse(JSON.stringify(item)),
          id: newId,
          timelineStart: item.timelineStart + dur,
          linkedGroupId: newLinkId,
        };

        track.items.push(duplicate);
      }

      p.selection.itemIds = newIds;
      break;
    }

    // ----- Item properties -----
    case "SET_ITEM_SPEED": {
      for (const itemId of expandLinkedItemIds(p, [command.itemId])) {
        const { item, track } = findItemInProject(p, itemId);
        requireEditable(track);
        item.speed = clampSpeed(command.speed);
      }
      break;
    }

    case "SET_ITEM_TRANSFORM": {
      const { item, track } = findItemInProject(p, command.itemId);
      requireEditable(track);
      if (!item.video) {
        item.video = {
          x: 0, y: 0, width: p.canvas.width, height: p.canvas.height,
          rotation: 0, opacity: 1, crop: null, fit: "contain",
        };
      }
      Object.assign(item.video, command.transform);
      break;
    }

    case "SET_ITEM_AUDIO": {
      const { item, track } = findItemInProject(p, command.itemId);
      requireEditable(track);
      if (!item.audio) {
        item.audio = { volume: 1, pan: 0, fadeIn: 0, fadeOut: 0, normalize: false };
      }
      Object.assign(item.audio, command.audio);
      break;
    }

    case "SET_ITEM_CAPTION": {
      const { item, track } = findItemInProject(p, command.itemId);
      requireEditable(track);
      if (track.kind !== "caption" || !item.caption) throw new Error("Caption item required");
      Object.assign(item.caption, command.caption);
      item.caption.fontSize = Math.max(12, Math.min(240, item.caption.fontSize));
      item.caption.backgroundOpacity = Math.max(0, Math.min(1, item.caption.backgroundOpacity));
      item.caption.strokeWidth = Math.max(0, Math.min(12, item.caption.strokeWidth));
      break;
    }

    case "APPLY_CREATIVE_TREATMENT": {
      const located = findItemInProject(p, command.itemId);
      requireEditable(located.track);
      if (located.track.kind !== "video" || !located.item.video) {
        throw new Error("Creative treatments require a video or image item");
      }
      let targetTrack = located.track;
      if (command.targetTrackId && command.targetTrackId !== located.track.id) {
        targetTrack = findTrack(p, command.targetTrackId);
        requireEditable(targetTrack);
        if (targetTrack.kind !== "video") throw new Error("Creative media must stay on a video track");
        removeItemFromTrack(located.track, located.item.id);
        located.item.trackId = targetTrack.id;
        targetTrack.items.push(located.item);
      }
      const width = p.canvas.width;
      const height = p.canvas.height;
      if (command.treatment === "cutaway") {
        Object.assign(located.item.video, { x: 0, y: 0, width, height, rotation: 0, opacity: 1, fit: "cover" });
        located.item.editorRole = "b_roll";
        if (located.item.audio) located.item.audio.volume = 0;
      } else if (command.treatment === "meme") {
        const boxWidth = Math.round(width * 0.68);
        const boxHeight = Math.round(height * 0.72);
        Object.assign(located.item.video, { x: Math.round((width - boxWidth) / 2), y: Math.round(height * 0.12), width: boxWidth, height: boxHeight, rotation: 0, opacity: 1, fit: "contain" });
        located.item.editorRole = "meme_insert";
      } else if (command.treatment === "pip") {
        const boxWidth = Math.round(width * 0.36);
        const boxHeight = Math.round(height * 0.36);
        Object.assign(located.item.video, { x: Math.round(width * 0.62), y: Math.round(height * 0.04), width: boxWidth, height: boxHeight, rotation: 0, opacity: 1, fit: "contain" });
        located.item.editorRole = "b_roll";
        if (located.item.audio) located.item.audio.volume = 0;
      } else {
        Object.assign(located.item.video, { x: 0, y: 0, width: Math.round(width * 0.32), height, rotation: 0, opacity: 1, fit: "cover" });
        located.item.editorRole = "b_roll";
        if (located.item.audio) located.item.audio.volume = 0;
      }
      p.selection.focusedTrackId = targetTrack.id;
      break;
    }

    case "SET_CHAPTER_TITLE": {
      const chapter = p.longformPlan?.chapters?.find((candidate) => candidate.id === command.chapterId);
      if (!chapter) throw new Error("Story chapter not found");
      chapter.title = command.title.trimStart().slice(0, 120);
      if (p.longformPlan?.youtubePackage) {
        p.longformPlan.youtubePackage.chapterText = (p.longformPlan.chapters ?? [])
          .map((candidate) => `${chapterClock(candidate.timelineStart)} ${candidate.title}`)
          .join("\n");
      }
      break;
    }

    case "SET_YOUTUBE_PACKAGE": {
      const youtubePackage = p.longformPlan?.youtubePackage;
      if (!youtubePackage) throw new Error("YouTube package not found");
      if (command.changes.title !== undefined) youtubePackage.title = command.changes.title.slice(0, 100);
      if (command.changes.description !== undefined) youtubePackage.description = command.changes.description.slice(0, 5000);
      if (command.changes.tags !== undefined) {
        youtubePackage.tags = command.changes.tags.map((tag) => tag.trim()).filter(Boolean).slice(0, 15);
      }
      break;
    }

    case "SET_YOUTUBE_REVIEW": {
      const youtubePackage = p.longformPlan?.youtubePackage;
      if (!youtubePackage) throw new Error("YouTube package not found");
      youtubePackage.review = {
        captionsReviewed: false,
        audioReviewed: false,
        rightsCleared: false,
        thumbnailReady: false,
        finalPlaybackReviewed: false,
        notes: "",
        ...(youtubePackage.review ?? {}),
        ...command.changes,
      };
      break;
    }

    case "SET_ITEM_ENABLED": {
      const { item, track } = findItemInProject(p, command.itemId);
      requireEditable(track);
      item.enabled = command.enabled;
      break;
    }

    case "SET_TRANSITION": {
      const from = findItemInProject(p, command.fromItemId);
      const to = findItemInProject(p, command.toItemId);
      requireEditable(from.track);
      requireEditable(to.track);
      if (from.track.id !== to.track.id || from.track.kind !== "video" || !from.item.video || !to.item.video) {
        throw new Error("Transitions require two video clips on the same track");
      }
      const existing = (p.transitions ?? []).find((transition) =>
        transition.fromItemId === from.item.id && transition.toItemId === to.item.id);
      p.transitions = (p.transitions ?? []).filter((transition) =>
        transition.fromItemId !== from.item.id && transition.toItemId !== to.item.id);
      const cut = itemEnd(from.item);
      if (existing?.kind === "mix" || command.kind !== "mix") to.item.timelineStart = cut;
      if (command.kind) {
        const maxDuration = Math.max(0.1, Math.min(itemDuration(from.item), itemDuration(to.item), 5));
        const duration = Math.max(0.1, Math.min(command.duration, maxDuration));
        if (command.kind === "mix") to.item.timelineStart = Math.max(0, cut - duration);
        p.transitions.push({
          id: `trn_${from.item.id}_${to.item.id}`,
          fromItemId: from.item.id,
          toItemId: to.item.id,
          kind: command.kind,
          duration,
        });
      }
      break;
    }

    case "CREATE_FLASHBACK": {
      const { item, track } = findItemInProject(p, command.itemId);
      requireEditable(track);
      if (track.kind !== "video" || !item.video) {
        throw new Error("Flashbacks require one selected video clip");
      }

      const rangeStart = Math.max(item.timelineStart, command.rangeStart);
      const rangeEnd = Math.min(itemEnd(item), command.rangeEnd);
      if (rangeEnd - rangeStart < 0.1) {
        throw new Error("Mark an In/Out range of at least 0.1 seconds inside the selected clip");
      }

      const originalTimelineStart = item.timelineStart;
      const insertAt = Math.max(0, command.insertAt ?? 0);
      const separatorDuration = Math.max(0, Math.min(2, command.separatorDuration ?? 0.2));
      const teaserDuration = rangeEnd - rangeStart;
      const insertedDuration = teaserDuration + separatorDuration;
      const sourceIn = item.sourceIn + (rangeStart - originalTimelineStart) * item.speed;
      const sourceOut = sourceIn + teaserDuration * item.speed;
      const originalLinkId = item.linkedGroupId;
      const detachedAudio = originalLinkId
        ? allItems(p).find((candidate) =>
          candidate.id !== item.id
          && candidate.linkedGroupId === originalLinkId
          && Boolean(candidate.audio)
          && !candidate.video)
        : undefined;

      for (const candidate of allItems(p)) {
        if (candidate.timelineStart >= insertAt) candidate.timelineStart += insertedDuration;
      }
      shiftLongformChapters(p, insertAt, insertedDuration);
      upsertColdOpenChapter(p, insertAt, insertedDuration, sourceIn, sourceOut);

      const teaserLinkId = detachedAudio ? nextId("lnk") : null;
      const teaser: TimelineItem = {
        ...JSON.parse(JSON.stringify(item)),
        id: nextId("itm"),
        timelineStart: insertAt,
        sourceIn,
        sourceOut,
        linkedGroupId: teaserLinkId,
        editorRole: "flashback",
      };
      track.items.push(teaser);

      const selectedIds = [teaser.id];
      if (detachedAudio) {
        const audioTrack = findTrack(p, detachedAudio.trackId);
        requireEditable(audioTrack);
        const audioSourceIn = detachedAudio.sourceIn + (rangeStart - originalTimelineStart) * detachedAudio.speed;
        const audioTeaser: TimelineItem = {
          ...JSON.parse(JSON.stringify(detachedAudio)),
          id: nextId("itm"),
          timelineStart: insertAt,
          sourceIn: audioSourceIn,
          sourceOut: audioSourceIn + teaserDuration * detachedAudio.speed,
          linkedGroupId: teaserLinkId,
          editorRole: "flashback",
        };
        audioTrack.items.push(audioTeaser);
        selectedIds.push(audioTeaser.id);
      }

      p.selection.itemIds = selectedIds;
      p.selection.focusedTrackId = track.id;
      p.inPoint = rangeStart + insertedDuration;
      p.outPoint = rangeEnd + insertedDuration;
      break;
    }

    case "CREATE_SOURCE_FLASHBACK": {
      const track = findTrack(p, command.trackId);
      requireEditable(track);
      const asset = p.assets[command.assetId];
      if (track.kind !== "video" || !asset || asset.kind !== "video") {
        throw new Error("A source video asset and editable video track are required");
      }
      const template = track.items.find((candidate) => candidate.assetId === command.assetId && candidate.video)
        ?? track.items.find((candidate) => candidate.video);
      if (!template?.video) throw new Error("The video track has no source clip to copy");
      const sourceIn = Math.max(0, command.sourceIn);
      const sourceOut = Math.min(asset.duration, command.sourceOut);
      if (sourceOut - sourceIn < 0.1) throw new Error("The suggested flashback is too short");
      const insertAt = Math.max(0, command.insertAt ?? 0);
      const separatorDuration = Math.max(0, Math.min(2, command.separatorDuration ?? 0.2));
      const teaserDuration = (sourceOut - sourceIn) / template.speed;
      const insertedDuration = teaserDuration + separatorDuration;
      for (const candidate of allItems(p)) {
        if (candidate.timelineStart >= insertAt) candidate.timelineStart += insertedDuration;
      }
      shiftLongformChapters(p, insertAt, insertedDuration);
      upsertColdOpenChapter(p, insertAt, insertedDuration, sourceIn, sourceOut, command.beatId);
      const teaser: TimelineItem = {
        ...JSON.parse(JSON.stringify(template)),
        id: nextId("itm"),
        assetId: command.assetId,
        trackId: track.id,
        timelineStart: insertAt,
        sourceIn,
        sourceOut,
        linkedGroupId: null,
        editorRole: "flashback",
      };
      track.items.push(teaser);
      if (command.beatId && p.longformPlan) {
        p.longformPlan.appliedFlashbacks = [...new Set([...(p.longformPlan.appliedFlashbacks ?? []), command.beatId])];
      }
      p.selection.itemIds = [teaser.id];
      p.selection.focusedTrackId = track.id;
      p.inPoint = insertAt;
      p.outPoint = insertAt + teaserDuration;
      break;
    }

    // ----- Linking / Detach -----
    case "DETACH_AUDIO": {
      const { item, track } = findItemInProject(p, command.itemId);
      requireEditable(track);
      const asset = p.assets[item.assetId];
      if (!asset || !asset.hasAudio || !item.video) break;

      const existingDetached = allItems(p).some((candidate) =>
        candidate.id !== item.id
        && candidate.assetId === item.assetId
        && !candidate.video
        && Boolean(candidate.audio)
        && candidate.linkedGroupId !== null
        && candidate.linkedGroupId === item.linkedGroupId,
      );
      if (existingDetached) break;

      // Mute the video item's audio (set volume to 0, or remove audio block)
      if (item.audio) {
        item.audio.volume = 0;
      } else {
        item.audio = { volume: 0, pan: 0, fadeIn: 0, fadeOut: 0, normalize: false };
      }

      // Link both items
      item.linkedGroupId = command.linkedGroupId;

      // Create an audio item on the specified audio track
      const audioItem: TimelineItem = {
        id: command.newAudioItemId,
        assetId: item.assetId,
        trackId: command.newAudioTrackId,
        timelineStart: item.timelineStart,
        sourceIn: item.sourceIn,
        sourceOut: item.sourceOut,
        speed: item.speed,
        linkedGroupId: command.linkedGroupId,
        enabled: true,
        audio: {
          volume: 1,
          pan: 0,
          fadeIn: 0,
          fadeOut: 0,
          normalize: false,
        },
      };

      const audioTrack = findTrack(p, command.newAudioTrackId);
      requireEditable(audioTrack);
      requireCompatible(audioTrack, audioItem);
      audioTrack.items.push(audioItem);
      break;
    }

    case "LINK_ITEMS": {
      for (const itemId of command.itemIds) {
        const { item, track } = findItemInProject(p, itemId);
        requireEditable(track);
        item.linkedGroupId = command.linkedGroupId;
      }
      break;
    }

    case "UNLINK_ITEMS": {
      for (const itemId of command.itemIds) {
        const { item, track } = findItemInProject(p, itemId);
        requireEditable(track);
        item.linkedGroupId = null;
      }
      break;
    }

    // ----- Track properties -----
    case "SET_TRACK_MUTE": {
      const track = findTrack(p, command.trackId);
      track.muted = command.muted;
      break;
    }

    case "SET_TRACK_SOLO": {
      const track = findTrack(p, command.trackId);
      track.solo = command.solo;
      break;
    }

    case "SET_TRACK_LOCK": {
      const track = findTrack(p, command.trackId);
      track.locked = command.locked;
      break;
    }

    case "SET_TRACK_VISIBILITY": {
      const track = findTrack(p, command.trackId);
      track.hidden = command.hidden;
      break;
    }

    // ----- Timeline operations -----
    case "RIPPLE_DELETE": {
      const track = findTrack(p, command.trackId);
      requireEditable(track);
      const deleteSet = new Set(expandLinkedItemIds(p, command.itemIds));

      // Find the items being deleted and their time span
      const deletedItems = track.items.filter((i) => deleteSet.has(i.id));
      if (deletedItems.length === 0) break;

      const deleteStart = Math.min(...deletedItems.map((i) => i.timelineStart));
      const deleteEnd = Math.max(...deletedItems.map((i) => itemEnd(i)));
      const gap = deleteEnd - deleteStart;

      // Remove the deleted items
      track.items = track.items.filter((i) => !deleteSet.has(i.id));

      // Shift downstream items left by the gap
      for (const item of track.items) {
        if (item.timelineStart >= deleteEnd) {
          item.timelineStart -= gap;
        }
      }

      p.selection.itemIds = p.selection.itemIds.filter((id) => !deleteSet.has(id));
      clearSingletonLinks(p);
      break;
    }

    case "INSERT_GAP": {
      const track = findTrack(p, command.trackId);
      requireEditable(track);
      for (const item of track.items) {
        if (item.timelineStart >= command.time) {
          item.timelineStart += command.duration;
        }
      }
      break;
    }

    case "SET_PLAYHEAD": {
      p.playhead = Math.max(0, command.time);
      break;
    }

    case "SET_SELECTION": {
      p.selection.itemIds = [...command.itemIds];
      p.selection.focusedTrackId = command.focusedTrackId;
      break;
    }

    case "SET_IN_OUT": {
      const inPoint = command.inPoint === null ? null : Math.max(0, command.inPoint);
      const outPoint = command.outPoint === null ? null : Math.max(0, command.outPoint);
      p.inPoint = inPoint;
      p.outPoint = inPoint !== null && outPoint !== null && outPoint < inPoint ? inPoint : outPoint;
      break;
    }

    case "SET_CANVAS": {
      Object.assign(p.canvas, command.canvas);
      p.canvas.width = Math.max(16, Math.round(p.canvas.width));
      p.canvas.height = Math.max(16, Math.round(p.canvas.height));
      p.canvas.fps = Math.max(1, Math.min(120, p.canvas.fps));
      break;
    }

    case "SET_EXPORT": {
      Object.assign(p.export, command.export);
      p.export.width = Math.max(16, Math.round(p.export.width));
      p.export.height = Math.max(16, Math.round(p.export.height));
      p.export.fps = Math.max(1, Math.min(120, p.export.fps));
      break;
    }

    case "SET_VIEW": {
      Object.assign(p.view, command.view);
      p.view.pixelsPerSecond = Math.max(12, Math.min(400, p.view.pixelsPerSecond));
      p.view.scrollLeft = Math.max(0, p.view.scrollLeft);
      break;
    }

    default: {
      // Exhaustiveness check
      const _exhaustive: never = command;
      throw new Error(`Unknown command: ${(_exhaustive as Command).type}`);
    }
  }

  const nonEditorialCommands = new Set<Command["type"]>([
    "COPY_ITEMS", "SET_PLAYHEAD", "SET_SELECTION", "SET_VIEW", "SET_YOUTUBE_REVIEW",
  ]);
  if (!nonEditorialCommands.has(command.type) && p.longformPlan?.youtubePackage?.review) {
    p.longformPlan.youtubePackage.review.finalPlaybackReviewed = false;
  }

  // Bump revision and timestamp
  p.revision = project.revision + 1;
  p.updatedAt = Math.max(project.updatedAt + 1, project.createdAt);

  return { project: p, clipboard: cb };
}
