/**
 * Editor V2 — Comprehensive unit tests for EV2-01.
 *
 * Covers:
 *   - Fixture project validity
 *   - Item duration and project duration selectors
 *   - Active items at time
 *   - Track ordering and video stacking
 *   - Overlap detection (two booms on A2)
 *   - All reducer commands
 *   - Copy / cut / paste / duplicate
 *   - Speed changes (0.25x–4x) and duration math
 *   - Audio detachment and linked group behavior
 *   - Undo / redo
 *   - Serialization round-trip
 *   - Schema migration
 */

import { describe, it, expect } from "vitest";
import {
  createFixtureProject,
  reduce,
  cloneProject,
  itemDuration,
  itemEnd,
  projectDuration,
  activeItemsAtTime,
  activeVideoItemsAtTime,
  activeAudioItemsAtTime,
  tracksByOrder,
  videoTracks,
  audioTracks,
  findItem,
  linkedItems,
  linkedSiblings,
  overlappingItems,
  itemsForAsset,
  usedAssetIds,
  orphanedAssets,
  trackById,
  selectedItems,
  createHistory,
  applyCommand,
  undo,
  redo,
  canUndo,
  canRedo,
  serializeProject,
  deserializeProject,
  migrateProject,
  CURRENT_SCHEMA_VERSION,
  allItems,
} from "..";
import type { EditorProjectV2, Command, TimelineItem } from "..";

// ============================================================================
// Fixture validation
// ============================================================================

describe("Fixture project", () => {
  it("creates a valid V2 project with all required tracks", () => {
    const p = createFixtureProject();
    expect(p.schemaVersion).toBe(2);
    expect(p.tracks).toHaveLength(4);
    expect(p.tracks.map((t) => t.name).sort()).toEqual(["A1", "A2", "V1", "V2"]);
  });

  it("has 3 assets (source clip, overlay image, boom)", () => {
    const p = createFixtureProject();
    expect(Object.keys(p.assets)).toHaveLength(3);
    expect(p.assets["ast_source_clip"]).toBeDefined();
    expect(p.assets["ast_overlay_img"]).toBeDefined();
    expect(p.assets["ast_boom"]).toBeDefined();
  });

  it("V1 has one clip, V2 has one overlay, A1 has detached audio, A2 has two booms", () => {
    const p = createFixtureProject();
    const v1 = p.tracks.find((t) => t.name === "V1")!;
    const v2 = p.tracks.find((t) => t.name === "V2")!;
    const a1 = p.tracks.find((t) => t.name === "A1")!;
    const a2 = p.tracks.find((t) => t.name === "A2")!;

    expect(v1.items).toHaveLength(1);
    expect(v2.items).toHaveLength(1);
    expect(a1.items).toHaveLength(1);
    expect(a2.items).toHaveLength(2);
  });

  it("two boom items reference the same asset", () => {
    const p = createFixtureProject();
    const a2 = p.tracks.find((t) => t.name === "A2")!;
    expect(a2.items[0].assetId).toBe("ast_boom");
    expect(a2.items[1].assetId).toBe("ast_boom");
    expect(a2.items[0].id).not.toBe(a2.items[1].id);
  });

  it("two boom items overlap in time", () => {
    const p = createFixtureProject();
    const a2 = p.tracks.find((t) => t.name === "A2")!;
    const boom1End = itemEnd(a2.items[0]); // 5.0 + 4.757 = 9.757
    const boom2Start = a2.items[1].timelineStart; // 7.0
    expect(boom1End).toBeGreaterThan(boom2Start);
  });

  it("V1 video and A1 audio share a linked group", () => {
    const p = createFixtureProject();
    const v1Item = p.tracks.find((t) => t.name === "V1")!.items[0];
    const a1Item = p.tracks.find((t) => t.name === "A1")!.items[0];
    expect(v1Item.linkedGroupId).toBe("lnk_source_av");
    expect(a1Item.linkedGroupId).toBe("lnk_source_av");
  });

  it("V1 video has audio muted (volume 0) because audio is detached", () => {
    const p = createFixtureProject();
    const v1Item = p.tracks.find((t) => t.name === "V1")!.items[0];
    expect(v1Item.audio?.volume).toBe(0);
  });

  it("returns a new deep copy each call (safe for mutation)", () => {
    const a = createFixtureProject();
    const b = createFixtureProject();
    expect(a).not.toBe(b);
    a.name = "mutated";
    expect(b.name).not.toBe("mutated");
  });
});

// ============================================================================
// Selectors: Duration
// ============================================================================

describe("Duration selectors", () => {
  it("itemDuration = (sourceOut - sourceIn) / speed", () => {
    const item: TimelineItem = {
      id: "t", assetId: "a", trackId: "trk", timelineStart: 0,
      sourceIn: 2, sourceOut: 12, speed: 2,
      linkedGroupId: null, enabled: true,
    };
    expect(itemDuration(item)).toBe(5); // (12-2)/2
  });

  it("itemEnd = timelineStart + itemDuration", () => {
    const item: TimelineItem = {
      id: "t", assetId: "a", trackId: "trk", timelineStart: 3,
      sourceIn: 0, sourceOut: 10, speed: 1,
      linkedGroupId: null, enabled: true,
    };
    expect(itemEnd(item)).toBe(13);
  });

  it("projectDuration is the max itemEnd across all tracks", () => {
    const p = createFixtureProject();
    // V1: start=0, sourceIn=2, sourceOut=20, speed=1 → dur=18, end=18
    // V2: start=3, sourceIn=0, sourceOut=5, speed=1 → dur=5, end=8
    // A1: start=0, sourceIn=2, sourceOut=20, speed=1 → dur=18, end=18
    // A2 boom1: start=5, dur=4.757, end=9.757
    // A2 boom2: start=7, dur=4.757, end=11.757
    expect(projectDuration(p)).toBe(18);
  });

  it("empty project has duration 0", () => {
    const p = createFixtureProject();
    p.tracks = [];
    expect(projectDuration(p)).toBe(0);
  });
});

// ============================================================================
// Selectors: Active items at time
// ============================================================================

describe("Active items at time", () => {
  it("returns items spanning the given time", () => {
    const p = createFixtureProject();
    // At t=6: V1 active (0–18), V2 active (3–8), A1 active (0–18),
    //         boom1 active (5–9.757), boom2 not yet active (starts at 7)
    const active = activeItemsAtTime(p, 6.0);
    const ids = active.map((a) => a.item.id).sort();
    expect(ids).toEqual(["itm_a1_detached", "itm_a2_boom1", "itm_v1_main", "itm_v2_overlay"]);
  });

  it("at t=8 both booms are active (overlap)", () => {
    const p = createFixtureProject();
    const active = activeItemsAtTime(p, 8.0);
    const boomIds = active
      .filter((a) => a.item.assetId === "ast_boom")
      .map((a) => a.item.id)
      .sort();
    expect(boomIds).toEqual(["itm_a2_boom1", "itm_a2_boom2"]);
  });

  it("at t=10 only boom2 is active (boom1 ended at 9.757)", () => {
    const p = createFixtureProject();
    const active = activeItemsAtTime(p, 10.0);
    const boomIds = active
      .filter((a) => a.item.assetId === "ast_boom")
      .map((a) => a.item.id);
    expect(boomIds).toEqual(["itm_a2_boom2"]);
  });

  it("disabled items are excluded", () => {
    const p = createFixtureProject();
    const v1 = p.tracks.find((t) => t.name === "V1")!;
    v1.items[0].enabled = false;
    const active = activeItemsAtTime(p, 5.0);
    expect(active.find((a) => a.item.id === "itm_v1_main")).toBeUndefined();
  });
});

// ============================================================================
// Selectors: Track ordering
// ============================================================================

describe("Track ordering", () => {
  it("video tracks sorted by order (V1=0, V2=1)", () => {
    const p = createFixtureProject();
    const vtracks = videoTracks(p);
    expect(vtracks.map((t) => t.name)).toEqual(["V1", "V2"]);
  });

  it("higher video track order renders above lower (V2 above V1)", () => {
    const p = createFixtureProject();
    const active = activeVideoItemsAtTime(p, 5.0);
    // Should be sorted bottom-to-top: V1 first (order 0), V2 second (order 1)
    expect(active[0].track.name).toBe("V1");
    expect(active[1].track.name).toBe("V2");
  });

  it("audio tracks sorted by order", () => {
    const p = createFixtureProject();
    const atracks = audioTracks(p);
    expect(atracks.map((t) => t.name)).toEqual(["A1", "A2"]);
  });

  it("tracksByOrder returns all tracks in order", () => {
    const p = createFixtureProject();
    const ordered = tracksByOrder(p);
    const orders = ordered.map((t) => t.order);
    expect(orders).toEqual([0, 1, 10, 11]);
  });
});

// ============================================================================
// Selectors: Overlap detection
// ============================================================================

describe("Overlap detection", () => {
  it("detects overlapping booms on A2", () => {
    const p = createFixtureProject();
    const a2 = p.tracks.find((t) => t.name === "A2")!;
    const boom1 = a2.items[0];
    // Check if boom2 overlaps with boom1's time range
    const overlaps = overlappingItems(a2, 7.0, 4.757, undefined);
    expect(overlaps.length).toBeGreaterThanOrEqual(1);
    expect(overlaps.some((i) => i.id === "itm_a2_boom1")).toBe(true);
  });

  it("no overlap when placing after both booms end", () => {
    const p = createFixtureProject();
    const a2 = p.tracks.find((t) => t.name === "A2")!;
    // boom2 ends at 7 + 4.757 = 11.757
    const overlaps = overlappingItems(a2, 12.0, 1.0);
    expect(overlaps).toHaveLength(0);
  });

  it("excludes self when checking overlap", () => {
    const p = createFixtureProject();
    const a2 = p.tracks.find((t) => t.name === "A2")!;
    const boom1 = a2.items[0];
    const overlaps = overlappingItems(a2, 5.0, 4.757, boom1.id);
    // boom1 excluded, but boom2 overlaps (starts at 7, within 5–9.757)
    expect(overlaps.some((i) => i.id === "itm_a2_boom1")).toBe(false);
    expect(overlaps.some((i) => i.id === "itm_a2_boom2")).toBe(true);
  });
});

// ============================================================================
// Selectors: Linked media
// ============================================================================

describe("Linked media", () => {
  it("finds linked items by group ID", () => {
    const p = createFixtureProject();
    const linked = linkedItems(p, "lnk_source_av");
    expect(linked).toHaveLength(2);
    expect(linked.map((i) => i.id).sort()).toEqual(["itm_a1_detached", "itm_v1_main"]);
  });

  it("linkedSiblings excludes the queried item", () => {
    const p = createFixtureProject();
    const siblings = linkedSiblings(p, "itm_v1_main");
    expect(siblings).toHaveLength(1);
    expect(siblings[0].id).toBe("itm_a1_detached");
  });

  it("returns empty for items with no linked group", () => {
    const p = createFixtureProject();
    const siblings = linkedSiblings(p, "itm_v2_overlay");
    expect(siblings).toHaveLength(0);
  });
});

// ============================================================================
// Selectors: Asset queries
// ============================================================================

describe("Asset queries", () => {
  it("itemsForAsset finds all items using boom", () => {
    const p = createFixtureProject();
    const items = itemsForAsset(p, "ast_boom");
    expect(items).toHaveLength(2);
  });

  it("usedAssetIds returns the set of referenced assets", () => {
    const p = createFixtureProject();
    const used = usedAssetIds(p);
    expect(used.size).toBe(3);
    expect(used.has("ast_source_clip")).toBe(true);
    expect(used.has("ast_boom")).toBe(true);
    expect(used.has("ast_overlay_img")).toBe(true);
  });

  it("orphanedAssets finds unused assets", () => {
    const p = createFixtureProject();
    // Add an unused asset
    p.assets["ast_orphan"] = {
      id: "ast_orphan", kind: "audio", origin: "import", name: "orphan.wav",
      duration: 1, hasAudio: true, fingerprint: "x", streamUrl: "/x",
    };
    const orphans = orphanedAssets(p);
    expect(orphans).toEqual(["ast_orphan"]);
  });
});

// ============================================================================
// Reducer: ADD_ASSET
// ============================================================================

describe("Reducer: ADD_ASSET", () => {
  it("adds a new asset to the project", () => {
    const p = createFixtureProject();
    const asset = {
      id: "ast_new", kind: "audio" as const, origin: "import" as const,
      name: "new.wav", duration: 2, hasAudio: true, fingerprint: "f", streamUrl: "/s",
    };
    const { project } = reduce(p, { type: "ADD_ASSET", asset });
    expect(project.assets["ast_new"]).toBeDefined();
    expect(project.assets["ast_new"].name).toBe("new.wav");
  });

  it("does not mutate the original project", () => {
    const p = createFixtureProject();
    const origAssetCount = Object.keys(p.assets).length;
    reduce(p, {
      type: "ADD_ASSET",
      asset: {
        id: "ast_x", kind: "audio", origin: "import", name: "x.wav",
        duration: 1, hasAudio: true, fingerprint: "f", streamUrl: "/s",
      },
    });
    expect(Object.keys(p.assets).length).toBe(origAssetCount);
  });
});

// ============================================================================
// Reducer: Tracks
// ============================================================================

describe("Reducer: Track operations", () => {
  it("ADD_TRACK adds a new track", () => {
    const p = createFixtureProject();
    const { project } = reduce(p, {
      type: "ADD_TRACK",
      track: {
        id: "trk_a3", kind: "audio", name: "A3", order: 12,
        muted: false, solo: false, locked: false, hidden: false,
      },
    });
    expect(project.tracks).toHaveLength(5);
    expect(project.tracks.find((t) => t.id === "trk_a3")).toBeDefined();
  });

  it("REMOVE_TRACK removes a track and its items from selection", () => {
    const p = createFixtureProject();
    p.selection.itemIds = ["itm_a2_boom1"];
    const { project } = reduce(p, { type: "REMOVE_TRACK", trackId: "trk_a2" });
    expect(project.tracks).toHaveLength(3);
    expect(project.tracks.find((t) => t.id === "trk_a2")).toBeUndefined();
    expect(project.selection.itemIds).not.toContain("itm_a2_boom1");
  });

  it("REORDER_TRACK changes track order", () => {
    const p = createFixtureProject();
    const { project } = reduce(p, { type: "REORDER_TRACK", trackId: "trk_v2", newOrder: -1 });
    const v2 = project.tracks.find((t) => t.id === "trk_v2")!;
    expect(v2.order).toBe(-1);
  });

  it("SET_TRACK_MUTE toggles mute", () => {
    const p = createFixtureProject();
    const { project } = reduce(p, { type: "SET_TRACK_MUTE", trackId: "trk_a2", muted: true });
    expect(project.tracks.find((t) => t.id === "trk_a2")!.muted).toBe(true);
  });

  it("SET_TRACK_SOLO toggles solo", () => {
    const p = createFixtureProject();
    const { project } = reduce(p, { type: "SET_TRACK_SOLO", trackId: "trk_a1", solo: true });
    expect(project.tracks.find((t) => t.id === "trk_a1")!.solo).toBe(true);
  });

  it("SET_TRACK_LOCK toggles lock", () => {
    const p = createFixtureProject();
    const { project } = reduce(p, { type: "SET_TRACK_LOCK", trackId: "trk_v1", locked: true });
    expect(project.tracks.find((t) => t.id === "trk_v1")!.locked).toBe(true);
  });

  it("SET_TRACK_VISIBILITY toggles hidden", () => {
    const p = createFixtureProject();
    const { project } = reduce(p, { type: "SET_TRACK_VISIBILITY", trackId: "trk_v1", hidden: true });
    expect(project.tracks.find((t) => t.id === "trk_v1")!.hidden).toBe(true);
  });

  it("muted audio tracks are excluded from activeAudioItemsAtTime", () => {
    const p = createFixtureProject();
    p.tracks.find((t) => t.name === "A2")!.muted = true;
    const active = activeAudioItemsAtTime(p, 8.0);
    const a2Items = active.filter((a) => a.track.name === "A2");
    expect(a2Items).toHaveLength(0);
  });

  it("solo audio track excludes non-solo tracks", () => {
    const p = createFixtureProject();
    p.tracks.find((t) => t.name === "A2")!.solo = true;
    const active = activeAudioItemsAtTime(p, 5.0);
    // Only A2 items should appear, A1 should be excluded
    expect(active.every((a) => a.track.name === "A2")).toBe(true);
  });
});

// ============================================================================
// Reducer: ADD_ITEM
// ============================================================================

describe("Reducer: ADD_ITEM", () => {
  it("adds an item to the specified track", () => {
    const p = createFixtureProject();
    const newItem: TimelineItem = {
      id: "itm_new", assetId: "ast_boom", trackId: "trk_a2",
      timelineStart: 15, sourceIn: 0, sourceOut: 4.757, speed: 1,
      linkedGroupId: null, enabled: true,
      audio: { volume: 1, pan: 0, fadeIn: 0, fadeOut: 0, normalize: false },
    };
    const { project } = reduce(p, { type: "ADD_ITEM", item: newItem });
    const a2 = project.tracks.find((t) => t.id === "trk_a2")!;
    expect(a2.items).toHaveLength(3);
    expect(a2.items.find((i) => i.id === "itm_new")).toBeDefined();
  });
});

// ============================================================================
// Reducer: MOVE_ITEMS
// ============================================================================

describe("Reducer: MOVE_ITEMS", () => {
  it("moves items by deltaTime", () => {
    const p = createFixtureProject();
    const { project } = reduce(p, {
      type: "MOVE_ITEMS", itemIds: ["itm_a2_boom1"], deltaTime: 3,
    });
    const a2 = project.tracks.find((t) => t.id === "trk_a2")!;
    const boom1 = a2.items.find((i) => i.id === "itm_a2_boom1")!;
    expect(boom1.timelineStart).toBe(8); // was 5, +3 = 8
  });

  it("clamps timelineStart to 0 on negative delta", () => {
    const p = createFixtureProject();
    const { project } = reduce(p, {
      type: "MOVE_ITEMS", itemIds: ["itm_a2_boom1"], deltaTime: -10,
    });
    const a2 = project.tracks.find((t) => t.id === "trk_a2")!;
    const boom1 = a2.items.find((i) => i.id === "itm_a2_boom1")!;
    expect(boom1.timelineStart).toBe(0);
  });

  it("moves item to a different track", () => {
    const p = createFixtureProject();
    const { project } = reduce(p, {
      type: "MOVE_ITEMS", itemIds: ["itm_a2_boom1"],
      deltaTime: 0, targetTrackId: "trk_a1",
    });
    const a1 = project.tracks.find((t) => t.id === "trk_a1")!;
    const a2 = project.tracks.find((t) => t.id === "trk_a2")!;
    expect(a1.items.find((i) => i.id === "itm_a2_boom1")).toBeDefined();
    expect(a2.items.find((i) => i.id === "itm_a2_boom1")).toBeUndefined();
  });
});

// ============================================================================
// Reducer: TRIM_ITEM
// ============================================================================

describe("Reducer: TRIM_ITEM", () => {
  it("trims the start — sourceIn and timelineStart adjust", () => {
    const p = createFixtureProject();
    // V1: sourceIn=2, sourceOut=20, timelineStart=0, speed=1
    const { project } = reduce(p, {
      type: "TRIM_ITEM", itemId: "itm_v1_main", edge: "start", delta: 3,
    });
    const item = findItem(project, "itm_v1_main")!.item;
    expect(item.sourceIn).toBe(5); // 2 + 3
    expect(item.timelineStart).toBe(3); // 0 + 3/1
  });

  it("trims the end — sourceOut adjusts", () => {
    const p = createFixtureProject();
    const { project } = reduce(p, {
      type: "TRIM_ITEM", itemId: "itm_v1_main", edge: "end", delta: -5,
    });
    const item = findItem(project, "itm_v1_main")!.item;
    expect(item.sourceOut).toBe(15); // 20 - 5
  });

  it("does not collapse to zero duration", () => {
    const p = createFixtureProject();
    const { project } = reduce(p, {
      type: "TRIM_ITEM", itemId: "itm_v1_main", edge: "start", delta: 100,
    });
    const item = findItem(project, "itm_v1_main")!.item;
    expect(item.sourceOut - item.sourceIn).toBeGreaterThan(0);
  });
});

// ============================================================================
// Reducer: SPLIT_ITEMS
// ============================================================================

describe("Reducer: SPLIT_ITEMS", () => {
  it("splits an item into two at the given time", () => {
    const p = createFixtureProject();
    // V1: timelineStart=0, dur=18 (sourceIn=2, sourceOut=20, speed=1)
    const { project } = reduce(p, {
      type: "SPLIT_ITEMS", itemIds: ["itm_v1_main"], time: 9,
    });
    const v1 = project.tracks.find((t) => t.id === "trk_v1")!;
    expect(v1.items).toHaveLength(2);

    const left = v1.items.find((i) => i.id === "itm_v1_main")!;
    const right = v1.items.find((i) => i.id !== "itm_v1_main")!;

    // Left: sourceIn=2, sourceOut should be 2 + 9*1 = 11
    expect(left.sourceIn).toBe(2);
    expect(left.sourceOut).toBe(11);
    expect(left.timelineStart).toBe(0);

    // Right: sourceIn=11, sourceOut=20, timelineStart=9
    expect(right.sourceIn).toBe(11);
    expect(right.sourceOut).toBe(20);
    expect(right.timelineStart).toBe(9);
  });

  it("does not split if time is outside item bounds", () => {
    const p = createFixtureProject();
    const { project } = reduce(p, {
      type: "SPLIT_ITEMS", itemIds: ["itm_v1_main"], time: 50,
    });
    const v1 = project.tracks.find((t) => t.id === "trk_v1")!;
    expect(v1.items).toHaveLength(1);
  });
});

// ============================================================================
// Reducer: DELETE_ITEMS
// ============================================================================

describe("Reducer: DELETE_ITEMS", () => {
  it("removes items from tracks", () => {
    const p = createFixtureProject();
    const { project } = reduce(p, {
      type: "DELETE_ITEMS", itemIds: ["itm_a2_boom1", "itm_a2_boom2"],
    });
    const a2 = project.tracks.find((t) => t.id === "trk_a2")!;
    expect(a2.items).toHaveLength(0);
  });

  it("clears deleted items from selection", () => {
    const p = createFixtureProject();
    p.selection.itemIds = ["itm_a2_boom1", "itm_v1_main"];
    const { project } = reduce(p, {
      type: "DELETE_ITEMS", itemIds: ["itm_a2_boom1"],
    });
    expect(project.selection.itemIds).toEqual(["itm_v1_main"]);
  });
});

// ============================================================================
// Reducer: COPY / CUT / PASTE / DUPLICATE
// ============================================================================

describe("Reducer: Copy/Cut/Paste/Duplicate", () => {
  it("COPY_ITEMS captures items into clipboard", () => {
    const p = createFixtureProject();
    const { clipboard } = reduce(p, {
      type: "COPY_ITEMS", itemIds: ["itm_a2_boom1", "itm_a2_boom2"],
    });
    expect(clipboard).not.toBeNull();
    expect(clipboard!.items).toHaveLength(2);
    expect(clipboard!.anchorTime).toBe(5.0); // earliest boom starts at 5
  });

  it("CUT_ITEMS copies and removes items", () => {
    const p = createFixtureProject();
    const { project, clipboard } = reduce(p, {
      type: "CUT_ITEMS", itemIds: ["itm_a2_boom1"],
    });
    expect(clipboard!.items).toHaveLength(1);
    const a2 = project.tracks.find((t) => t.id === "trk_a2")!;
    expect(a2.items.find((i) => i.id === "itm_a2_boom1")).toBeUndefined();
    expect(a2.items).toHaveLength(1); // boom2 remains
  });

  it("PASTE_ITEMS creates new items at playhead with new IDs", () => {
    const p = createFixtureProject();
    // First copy
    const { clipboard } = reduce(p, {
      type: "COPY_ITEMS", itemIds: ["itm_a2_boom1", "itm_a2_boom2"],
    });
    // Then paste at t=15
    const { project } = reduce(p, { type: "PASTE_ITEMS", time: 15 }, clipboard);
    const a2 = project.tracks.find((t) => t.id === "trk_a2")!;
    // Original 2 + pasted 2 = 4
    expect(a2.items).toHaveLength(4);
    // Pasted items have new IDs
    const newItems = a2.items.filter(
      (i) => i.id !== "itm_a2_boom1" && i.id !== "itm_a2_boom2",
    );
    expect(newItems).toHaveLength(2);
    // Relative timing preserved: anchor was 5, boom1 at 5 (offset 0), boom2 at 7 (offset 2)
    const starts = newItems.map((i) => i.timelineStart).sort((a, b) => a - b);
    expect(starts[0]).toBe(15); // 15 + 0
    expect(starts[1]).toBe(17); // 15 + 2
  });

  it("PASTE_ITEMS with no clipboard does nothing", () => {
    const p = createFixtureProject();
    const { project } = reduce(p, { type: "PASTE_ITEMS", time: 10 }, null);
    expect(allItems(project).length).toBe(allItems(p).length);
  });

  it("PASTE_ITEMS preserves linked group IDs with new values", () => {
    const p = createFixtureProject();
    // Copy the linked V1 + A1 items
    const { clipboard } = reduce(p, {
      type: "COPY_ITEMS", itemIds: ["itm_v1_main", "itm_a1_detached"],
    });
    const { project } = reduce(p, { type: "PASTE_ITEMS", time: 20 }, clipboard);
    const allI = allItems(project);
    const pasted = allI.filter(
      (i) => i.id !== "itm_v1_main" && i.id !== "itm_a1_detached"
        && i.linkedGroupId !== null && i.linkedGroupId !== "lnk_source_av",
    );
    // Both pasted items should share a new linked group ID
    if (pasted.length >= 2) {
      expect(pasted[0].linkedGroupId).toBe(pasted[1].linkedGroupId);
      expect(pasted[0].linkedGroupId).not.toBe("lnk_source_av");
    }
  });

  it("DUPLICATE_ITEMS places copies after originals", () => {
    const p = createFixtureProject();
    const { project } = reduce(p, {
      type: "DUPLICATE_ITEMS", itemIds: ["itm_a2_boom1"],
    });
    const a2 = project.tracks.find((t) => t.id === "trk_a2")!;
    expect(a2.items).toHaveLength(3);
    // Duplicate starts right after boom1 ends
    const dup = a2.items.find(
      (i) => i.id !== "itm_a2_boom1" && i.id !== "itm_a2_boom2",
    )!;
    expect(dup.timelineStart).toBeCloseTo(5.0 + 4.757, 2); // boom1 end
    expect(dup.assetId).toBe("ast_boom");
  });

  it("DUPLICATE updates selection to new items", () => {
    const p = createFixtureProject();
    const { project } = reduce(p, {
      type: "DUPLICATE_ITEMS", itemIds: ["itm_a2_boom1"],
    });
    // Selection should contain only the new duplicated item
    expect(project.selection.itemIds).toHaveLength(1);
    expect(project.selection.itemIds[0]).not.toBe("itm_a2_boom1");
  });
});

// ============================================================================
// Reducer: SET_ITEM_SPEED
// ============================================================================

describe("Reducer: SET_ITEM_SPEED", () => {
  it("changes speed and affects duration", () => {
    const p = createFixtureProject();
    // V1: sourceIn=2, sourceOut=20, speed=1 → dur=18
    const { project } = reduce(p, {
      type: "SET_ITEM_SPEED", itemId: "itm_v1_main", speed: 2,
    });
    const item = findItem(project, "itm_v1_main")!.item;
    expect(item.speed).toBe(2);
    expect(itemDuration(item)).toBe(9); // 18/2
  });

  it("speed 0.25x quadruples duration", () => {
    const p = createFixtureProject();
    const origDur = itemDuration(findItem(p, "itm_v1_main")!.item);
    const { project } = reduce(p, {
      type: "SET_ITEM_SPEED", itemId: "itm_v1_main", speed: 0.25,
    });
    const item = findItem(project, "itm_v1_main")!.item;
    expect(itemDuration(item)).toBeCloseTo(origDur * 4, 5);
  });

  it("speed 4x quarters duration", () => {
    const p = createFixtureProject();
    const origDur = itemDuration(findItem(p, "itm_v1_main")!.item);
    const { project } = reduce(p, {
      type: "SET_ITEM_SPEED", itemId: "itm_v1_main", speed: 4,
    });
    const item = findItem(project, "itm_v1_main")!.item;
    expect(itemDuration(item)).toBeCloseTo(origDur / 4, 5);
  });

  it("clamps speed to 0.25–4.0 range", () => {
    const p = createFixtureProject();
    const { project: p1 } = reduce(p, {
      type: "SET_ITEM_SPEED", itemId: "itm_v1_main", speed: 0.1,
    });
    expect(findItem(p1, "itm_v1_main")!.item.speed).toBe(0.25);

    const { project: p2 } = reduce(p, {
      type: "SET_ITEM_SPEED", itemId: "itm_v1_main", speed: 10,
    });
    expect(findItem(p2, "itm_v1_main")!.item.speed).toBe(4);
  });

  it("preserves sourceIn/sourceOut when speed changes", () => {
    const p = createFixtureProject();
    const orig = findItem(p, "itm_v1_main")!.item;
    const { project } = reduce(p, {
      type: "SET_ITEM_SPEED", itemId: "itm_v1_main", speed: 3,
    });
    const item = findItem(project, "itm_v1_main")!.item;
    expect(item.sourceIn).toBe(orig.sourceIn);
    expect(item.sourceOut).toBe(orig.sourceOut);
  });
});

// ============================================================================
// Reducer: DETACH_AUDIO
// ============================================================================

describe("Reducer: DETACH_AUDIO", () => {
  it("mutes video item and creates audio item on target track", () => {
    const p = createFixtureProject();
    // Add a fresh video item with audio to test detach
    const testItem: TimelineItem = {
      id: "itm_test_video", assetId: "ast_source_clip", trackId: "trk_v1",
      timelineStart: 20, sourceIn: 0, sourceOut: 10, speed: 1,
      linkedGroupId: null, enabled: true,
      video: {
        x: 0, y: 0, width: 1920, height: 1080,
        rotation: 0, opacity: 1, crop: null, fit: "contain",
      },
      audio: { volume: 1, pan: 0, fadeIn: 0, fadeOut: 0, normalize: false },
    };
    const { project: p1 } = reduce(p, { type: "ADD_ITEM", item: testItem });

    const { project: p2 } = reduce(p1, {
      type: "DETACH_AUDIO",
      itemId: "itm_test_video",
      newAudioTrackId: "trk_a1",
      newAudioItemId: "itm_detached_audio",
      linkedGroupId: "lnk_detach_test",
    });

    // Video item should have volume 0
    const videoItem = findItem(p2, "itm_test_video")!.item;
    expect(videoItem.audio!.volume).toBe(0);
    expect(videoItem.linkedGroupId).toBe("lnk_detach_test");

    // Audio item should exist on A1
    const audioItem = findItem(p2, "itm_detached_audio")!.item;
    expect(audioItem.trackId).toBe("trk_a1");
    expect(audioItem.assetId).toBe("ast_source_clip");
    expect(audioItem.audio!.volume).toBe(1);
    expect(audioItem.linkedGroupId).toBe("lnk_detach_test");
    expect(audioItem.timelineStart).toBe(20);
    expect(audioItem.sourceIn).toBe(0);
    expect(audioItem.sourceOut).toBe(10);
  });

  it("detached audio never causes duplicate embedded audio", () => {
    const p = createFixtureProject();
    // The fixture already has detached audio: V1 video is muted (vol=0)
    // and A1 has the detached audio (vol=1). Both share lnk_source_av.
    const v1Item = findItem(p, "itm_v1_main")!.item;
    const a1Item = findItem(p, "itm_a1_detached")!.item;

    // Video has volume 0 — won't produce embedded audio
    expect(v1Item.audio!.volume).toBe(0);
    // Audio item has volume 1 — the only audio source
    expect(a1Item.audio!.volume).toBe(1);

    // Both share same asset and linked group
    expect(v1Item.assetId).toBe(a1Item.assetId);
    expect(v1Item.linkedGroupId).toBe(a1Item.linkedGroupId);
  });
});

// ============================================================================
// Reducer: LINK / UNLINK
// ============================================================================

describe("Reducer: LINK / UNLINK", () => {
  it("LINK_ITEMS sets linkedGroupId on specified items", () => {
    const p = createFixtureProject();
    const { project } = reduce(p, {
      type: "LINK_ITEMS",
      itemIds: ["itm_a2_boom1", "itm_a2_boom2"],
      linkedGroupId: "lnk_booms",
    });
    const a2 = project.tracks.find((t) => t.id === "trk_a2")!;
    expect(a2.items[0].linkedGroupId).toBe("lnk_booms");
    expect(a2.items[1].linkedGroupId).toBe("lnk_booms");
  });

  it("UNLINK_ITEMS clears linkedGroupId", () => {
    const p = createFixtureProject();
    const { project } = reduce(p, {
      type: "UNLINK_ITEMS", itemIds: ["itm_v1_main", "itm_a1_detached"],
    });
    const v1Item = findItem(project, "itm_v1_main")!.item;
    const a1Item = findItem(project, "itm_a1_detached")!.item;
    expect(v1Item.linkedGroupId).toBeNull();
    expect(a1Item.linkedGroupId).toBeNull();
  });
});

// ============================================================================
// Reducer: RIPPLE_DELETE and INSERT_GAP
// ============================================================================

describe("Reducer: RIPPLE_DELETE", () => {
  it("deletes items and shifts downstream items left", () => {
    const p = createFixtureProject();
    // Put 3 items on A2: boom1 at 5, boom2 at 7, add a third at 15
    const { project: p1 } = reduce(p, {
      type: "ADD_ITEM",
      item: {
        id: "itm_boom3", assetId: "ast_boom", trackId: "trk_a2",
        timelineStart: 15, sourceIn: 0, sourceOut: 4.757, speed: 1,
        linkedGroupId: null, enabled: true,
        audio: { volume: 1, pan: 0, fadeIn: 0, fadeOut: 0, normalize: false },
      },
    });

    // Ripple-delete boom1 (5–9.757). Gap = 4.757.
    // boom2 at 7 is not >= 9.757 so it stays. boom3 at 15 >= 9.757 → shifts left.
    const { project: p2 } = reduce(p1, {
      type: "RIPPLE_DELETE",
      itemIds: ["itm_a2_boom1"],
      trackId: "trk_a2",
    });

    const a2 = p2.tracks.find((t) => t.id === "trk_a2")!;
    expect(a2.items.find((i) => i.id === "itm_a2_boom1")).toBeUndefined();
    const boom3 = a2.items.find((i) => i.id === "itm_boom3")!;
    expect(boom3.timelineStart).toBeCloseTo(15 - 4.757, 2);
  });
});

describe("Reducer: INSERT_GAP", () => {
  it("shifts items at or after the given time", () => {
    const p = createFixtureProject();
    // A2 has boom1 at 5 and boom2 at 7
    const { project } = reduce(p, {
      type: "INSERT_GAP", trackId: "trk_a2", time: 6, duration: 3,
    });
    const a2 = project.tracks.find((t) => t.id === "trk_a2")!;
    const boom1 = a2.items.find((i) => i.id === "itm_a2_boom1")!;
    const boom2 = a2.items.find((i) => i.id === "itm_a2_boom2")!;
    // boom1 at 5 < 6 → stays
    expect(boom1.timelineStart).toBe(5);
    // boom2 at 7 >= 6 → shifts to 10
    expect(boom2.timelineStart).toBe(10);
  });
});

// ============================================================================
// Reducer: SET_PLAYHEAD and SET_SELECTION
// ============================================================================

describe("Reducer: SET_PLAYHEAD", () => {
  it("sets playhead and clamps to 0", () => {
    const p = createFixtureProject();
    const { project: p1 } = reduce(p, { type: "SET_PLAYHEAD", time: 10 });
    expect(p1.playhead).toBe(10);

    const { project: p2 } = reduce(p, { type: "SET_PLAYHEAD", time: -5 });
    expect(p2.playhead).toBe(0);
  });
});

describe("Reducer: SET_SELECTION", () => {
  it("sets selection state", () => {
    const p = createFixtureProject();
    const { project } = reduce(p, {
      type: "SET_SELECTION",
      itemIds: ["itm_v1_main", "itm_a2_boom1"],
      focusedTrackId: "trk_v1",
    });
    expect(project.selection.itemIds).toEqual(["itm_v1_main", "itm_a2_boom1"]);
    expect(project.selection.focusedTrackId).toBe("trk_v1");
  });
});

// ============================================================================
// Reducer: SET_ITEM_TRANSFORM and SET_ITEM_AUDIO
// ============================================================================

describe("Reducer: SET_ITEM_TRANSFORM", () => {
  it("partially updates video transform", () => {
    const p = createFixtureProject();
    const { project } = reduce(p, {
      type: "SET_ITEM_TRANSFORM",
      itemId: "itm_v1_main",
      transform: { opacity: 0.5, rotation: 45 },
    });
    const item = findItem(project, "itm_v1_main")!.item;
    expect(item.video!.opacity).toBe(0.5);
    expect(item.video!.rotation).toBe(45);
    // Other properties unchanged
    expect(item.video!.x).toBe(0);
  });

  it("creates video transform if missing", () => {
    const p = createFixtureProject();
    // boom1 has no video transform
    const { project } = reduce(p, {
      type: "SET_ITEM_TRANSFORM",
      itemId: "itm_a2_boom1",
      transform: { opacity: 0.3 },
    });
    const item = findItem(project, "itm_a2_boom1")!.item;
    expect(item.video).toBeDefined();
    expect(item.video!.opacity).toBe(0.3);
  });
});

describe("Reducer: SET_ITEM_AUDIO", () => {
  it("partially updates audio settings", () => {
    const p = createFixtureProject();
    const { project } = reduce(p, {
      type: "SET_ITEM_AUDIO",
      itemId: "itm_a2_boom1",
      audio: { volume: 0.5, pan: 0.2 },
    });
    const item = findItem(project, "itm_a2_boom1")!.item;
    expect(item.audio!.volume).toBe(0.5);
    expect(item.audio!.pan).toBe(0.2);
    // Other properties unchanged
    expect(item.audio!.fadeOut).toBe(0.2);
  });
});

// ============================================================================
// Reducer: Revision bumping
// ============================================================================

describe("Reducer: revision and updatedAt", () => {
  it("bumps revision on every command", () => {
    const p = createFixtureProject();
    expect(p.revision).toBe(1);
    const { project: p1 } = reduce(p, { type: "SET_PLAYHEAD", time: 5 });
    expect(p1.revision).toBe(2);
    const { project: p2 } = reduce(p1, { type: "SET_PLAYHEAD", time: 10 });
    expect(p2.revision).toBe(3);
  });
});

// ============================================================================
// History: Undo / Redo
// ============================================================================

describe("Undo / Redo", () => {
  it("can undo a command", () => {
    const p = createFixtureProject();
    let h = createHistory(p);
    h = applyCommand(h, { type: "SET_PLAYHEAD", time: 10 });
    expect(h.current.playhead).toBe(10);

    h = undo(h);
    expect(h.current.playhead).toBe(0);
  });

  it("can redo an undone command", () => {
    const p = createFixtureProject();
    let h = createHistory(p);
    h = applyCommand(h, { type: "SET_PLAYHEAD", time: 10 });
    h = undo(h);
    expect(h.current.playhead).toBe(0);

    h = redo(h);
    expect(h.current.playhead).toBe(10);
  });

  it("new command clears redo stack", () => {
    const p = createFixtureProject();
    let h = createHistory(p);
    h = applyCommand(h, { type: "SET_PLAYHEAD", time: 10 });
    h = undo(h);
    expect(canRedo(h)).toBe(true);

    h = applyCommand(h, { type: "SET_PLAYHEAD", time: 5 });
    expect(canRedo(h)).toBe(false);
    expect(h.current.playhead).toBe(5);
  });

  it("undo with empty stack returns same state", () => {
    const p = createFixtureProject();
    const h = createHistory(p);
    expect(canUndo(h)).toBe(false);
    const h2 = undo(h);
    expect(h2).toBe(h);
  });

  it("supports multiple undo levels", () => {
    const p = createFixtureProject();
    let h = createHistory(p);
    h = applyCommand(h, { type: "SET_PLAYHEAD", time: 5 });
    h = applyCommand(h, { type: "SET_PLAYHEAD", time: 10 });
    h = applyCommand(h, { type: "SET_PLAYHEAD", time: 15 });
    expect(h.current.playhead).toBe(15);

    h = undo(h);
    expect(h.current.playhead).toBe(10);
    h = undo(h);
    expect(h.current.playhead).toBe(5);
    h = undo(h);
    expect(h.current.playhead).toBe(0);
  });

  it("respects max depth", () => {
    const p = createFixtureProject();
    let h = createHistory(p, 3); // max 3 undo entries
    for (let i = 1; i <= 10; i++) {
      h = applyCommand(h, { type: "SET_PLAYHEAD", time: i });
    }
    expect(h.undoStack.length).toBe(3);
    // Can undo 3 times
    h = undo(h); // back to 9
    h = undo(h); // back to 8
    h = undo(h); // back to 7
    expect(h.current.playhead).toBe(7);
    expect(canUndo(h)).toBe(false);
  });

  it("undo/redo complex operations (delete + paste)", () => {
    const p = createFixtureProject();
    let h = createHistory(p);

    // Delete boom1
    h = applyCommand(h, { type: "DELETE_ITEMS", itemIds: ["itm_a2_boom1"] });
    const a2After = h.current.tracks.find((t) => t.id === "trk_a2")!;
    expect(a2After.items).toHaveLength(1);

    // Undo delete
    h = undo(h);
    const a2Restored = h.current.tracks.find((t) => t.id === "trk_a2")!;
    expect(a2Restored.items).toHaveLength(2);
    expect(a2Restored.items.find((i) => i.id === "itm_a2_boom1")).toBeDefined();
  });
});

// ============================================================================
// Serialization: round-trip
// ============================================================================

describe("Serialization", () => {
  it("round-trips a project through JSON without loss", () => {
    const original = createFixtureProject();
    const json = serializeProject(original);
    const restored = deserializeProject(json);

    expect(restored.schemaVersion).toBe(original.schemaVersion);
    expect(restored.id).toBe(original.id);
    expect(restored.name).toBe(original.name);
    expect(restored.tracks).toHaveLength(original.tracks.length);

    // All items preserved
    const origItems = allItems(original);
    const restoredItems = allItems(restored);
    expect(restoredItems).toHaveLength(origItems.length);

    // All assets preserved
    expect(Object.keys(restored.assets)).toEqual(Object.keys(original.assets));
  });

  it("preserves the Clip Room candidate used for Discord delivery", () => {
    const original = createFixtureProject();
    original.sourceCandidateId = "cand_discord_thread_01";

    const restored = deserializeProject(serializeProject(original));

    expect(restored.sourceCandidateId).toBe("cand_discord_thread_01");
  });

  it("preserves item durations and timing after reload", () => {
    const original = createFixtureProject();
    const json = serializeProject(original);
    const restored = deserializeProject(json);

    const origDuration = projectDuration(original);
    const restoredDuration = projectDuration(restored);
    expect(restoredDuration).toBe(origDuration);
  });

  it("preserves linked groups after reload", () => {
    const original = createFixtureProject();
    const json = serializeProject(original);
    const restored = deserializeProject(json);

    const linked = linkedItems(restored, "lnk_source_av");
    expect(linked).toHaveLength(2);
  });

  it("preserves overlapping boom items after reload", () => {
    const original = createFixtureProject();
    const json = serializeProject(original);
    const restored = deserializeProject(json);

    const a2 = restored.tracks.find((t) => t.name === "A2")!;
    expect(a2.items).toHaveLength(2);
    expect(a2.items[0].assetId).toBe("ast_boom");
    expect(a2.items[1].assetId).toBe("ast_boom");
    expect(a2.items[0].id).not.toBe(a2.items[1].id);
  });

  it("preserves speed settings after reload", () => {
    const p = createFixtureProject();
    const { project } = reduce(p, {
      type: "SET_ITEM_SPEED", itemId: "itm_v1_main", speed: 2.5,
    });
    const json = serializeProject(project);
    const restored = deserializeProject(json);
    const item = findItem(restored, "itm_v1_main")!.item;
    expect(item.speed).toBe(2.5);
  });

  it("preserves long-form story plans after reload", () => {
    const original = createFixtureProject();
    original.contentMode = "long_form";
    original.longformPlan = {
      strategy: "rough_cut",
      brief: "challenge story",
      chapters: [{
        id: "chapter_01", title: "The setup", timelineStart: 0, timelineEnd: 30,
        sourceStart: 100, sourceEnd: 130, beatIds: ["beat_001"], role: "setup",
      }],
      captionsGenerated: 12,
    };
    const restored = deserializeProject(serializeProject(original));
    expect(restored.contentMode).toBe("long_form");
    expect(restored.longformPlan?.chapters?.[0].sourceStart).toBe(100);
    expect(restored.longformPlan?.captionsGenerated).toBe(12);
  });

  it("edits generated YouTube chapter titles without changing source ranges", () => {
    const original = createFixtureProject();
    original.contentMode = "long_form";
    original.longformPlan = {
      strategy: "rough_cut",
      chapters: [{
        id: "chapter_01", title: "Raw title", timelineStart: 0, timelineEnd: 30,
        sourceStart: 100, sourceEnd: 130, beatIds: ["beat_001"], role: "setup",
      }],
      youtubePackage: {
        title: "Challenge", description: "Description", tags: ["challenge"], chapterText: "0:00 Raw title",
        qualityReport: { grade: "ready", warnings: [], metrics: { selectedSeconds: 30, sourceCoverage: .1, targetSeconds: 30, roleCoverage: ["setup"] } },
      },
    };
    const result = reduce(original, { type: "SET_CHAPTER_TITLE", chapterId: "chapter_01", title: "The challenge begins" });
    expect(result.project.longformPlan?.chapters?.[0].title).toBe("The challenge begins");
    expect(result.project.longformPlan?.chapters?.[0].sourceStart).toBe(100);
    expect(result.project.longformPlan?.youtubePackage?.chapterText).toBe("0:00 The challenge begins");
  });
});

// ============================================================================
// Schema migration
// ============================================================================

describe("Schema migration", () => {
  it("migrates V1 schema to V2", () => {
    const v1Project = {
      schemaVersion: 1,
      id: "proj_v1_old",
      name: "Old Project",
      revision: 5,
      tracks: [
        {
          id: "trk_1", kind: "video", name: "V1", order: 0,
          muted: false, solo: false, locked: false, hidden: false,
          items: [
            {
              id: "itm_1", assetId: "a1", trackId: "trk_1",
              timelineStart: 0, sourceIn: 0, sourceOut: 10,
            },
          ],
        },
      ],
      assets: {},
    };
    const migrated = migrateProject(v1Project);
    expect(migrated.schemaVersion).toBe(2);
    expect(migrated.canvas).toBeDefined();
    expect(migrated.export).toBeDefined();
    expect(migrated.selection).toBeDefined();
    // Item defaults filled
    const item = migrated.tracks[0].items[0];
    expect(item.speed).toBe(1);
    expect(item.enabled).toBe(true);
    expect(item.linkedGroupId).toBeNull();
  });

  it("validates V2 schema and fills defaults", () => {
    const raw = {
      schemaVersion: 2,
      id: "proj_minimal",
      tracks: [
        {
          id: "t1", kind: "video", name: "V1", order: 0,
          muted: false, solo: false, locked: false, hidden: false,
          items: [{
            id: "i1", assetId: "a1", trackId: "t1",
            timelineStart: 0, sourceIn: 0, sourceOut: 5,
          }],
        },
      ],
    };
    const project = migrateProject(raw as Record<string, unknown>);
    expect(project.schemaVersion).toBe(2);
    expect(project.name).toBe("Untitled");
    expect(project.canvas.fps).toBe(30);
    const item = project.tracks[0].items[0];
    expect(item.speed).toBe(1);
    expect(item.enabled).toBe(true);
  });

  it("rejects unknown schema version", () => {
    expect(() => migrateProject({ schemaVersion: 99 })).toThrow("newer than supported");
  });

  it("rejects missing schema version", () => {
    expect(() => migrateProject({})).toThrow("Unknown or missing schemaVersion");
  });

  it("current schema version is 2", () => {
    expect(CURRENT_SCHEMA_VERSION).toBe(2);
  });
});

// ============================================================================
// Integration: full workflow
// ============================================================================

describe("Integration: full editing workflow", () => {
  it("add asset → add item → speed change → copy → paste → save → reload", () => {
    let p = createFixtureProject();
    let cb = null as import("..").ClipboardEntry | null;

    // Add new sound asset
    const yooohAsset = {
      id: "ast_yoooh", kind: "audio" as const, origin: "sound-bin" as const,
      name: "yoooh.mp4", stem: "yoooh", duration: 3.5, hasAudio: true,
      fingerprint: "sha256_yoooh", streamUrl: "/s",
    };
    ({ project: p } = reduce(p, { type: "ADD_ASSET", asset: yooohAsset }));

    // Add item on A2
    const yooohItem: TimelineItem = {
      id: "itm_yoooh1", assetId: "ast_yoooh", trackId: "trk_a2",
      timelineStart: 12, sourceIn: 0, sourceOut: 3.5, speed: 1,
      linkedGroupId: null, enabled: true,
      audio: { volume: 0.9, pan: 0, fadeIn: 0, fadeOut: 0, normalize: false },
    };
    ({ project: p } = reduce(p, { type: "ADD_ITEM", item: yooohItem }));
    expect(allItems(p).length).toBe(6);

    // Change speed to 2x
    ({ project: p } = reduce(p, {
      type: "SET_ITEM_SPEED", itemId: "itm_yoooh1", speed: 2,
    }));
    const yoooh = findItem(p, "itm_yoooh1")!.item;
    expect(itemDuration(yoooh)).toBe(1.75); // 3.5 / 2

    // Copy and paste
    ({ project: p, clipboard: cb } = reduce(p, {
      type: "COPY_ITEMS", itemIds: ["itm_yoooh1"],
    }));
    ({ project: p } = reduce(p, { type: "PASTE_ITEMS", time: 16 }, cb));
    expect(allItems(p).length).toBe(7);

    // Serialize and reload
    const json = serializeProject(p);
    const restored = deserializeProject(json);
    expect(allItems(restored).length).toBe(7);
    expect(projectDuration(restored)).toBe(projectDuration(p));
  });
});

describe("Editor V2 captions and transitions", () => {
  it("adds and edits a caption item on a caption track", () => {
    let p = createFixtureProject();
    ({ project: p } = reduce(p, {
      type: "ADD_ASSET",
      asset: {
        id: "ast_caption", kind: "caption", origin: "generated", name: "Caption",
        duration: 3, hasAudio: false, fingerprint: "caption", streamUrl: "",
      },
    }));
    ({ project: p } = reduce(p, {
      type: "ADD_TRACK",
      track: { id: "trk_c1", kind: "caption", name: "C1", order: 20, muted: false, solo: false, locked: false, hidden: false },
    }));
    ({ project: p } = reduce(p, {
      type: "ADD_ITEM",
      item: {
        id: "itm_caption", assetId: "ast_caption", trackId: "trk_c1",
        timelineStart: 2, sourceIn: 0, sourceOut: 3, speed: 1,
        linkedGroupId: null, enabled: true,
        caption: { text: "Original", fontSize: 64, color: "#ffffff", backgroundColor: "#000000", backgroundOpacity: 0.6, strokeColor: "#000000", strokeWidth: 3, position: "bottom", bold: true },
      },
    }));
    ({ project: p } = reduce(p, { type: "SET_ITEM_CAPTION", itemId: "itm_caption", caption: { text: "Rocomamas", fontSize: 999 } }));
    ({ project: p } = reduce(p, { type: "TRIM_ITEM", itemId: "itm_caption", edge: "end", delta: 7 }));
    const caption = findItem(p, "itm_caption")!.item.caption!;
    expect(caption.text).toBe("Rocomamas");
    expect(caption.fontSize).toBe(240);
    expect(findItem(p, "itm_caption")!.item.sourceOut).toBe(10);
  });

  it("creates a non-destructive opening flashback from the marked later range", () => {
    let p = createFixtureProject();
    const originalDuration = projectDuration(p);
    ({ project: p } = reduce(p, {
      type: "CREATE_FLASHBACK",
      itemId: "itm_v1_main",
      rangeStart: 10,
      rangeEnd: 12,
      insertAt: 0,
      separatorDuration: 0.2,
    }));

    const videoTrack = p.tracks.find((track) => track.id === "trk_v1")!;
    const teaser = videoTrack.items.find((item) => item.editorRole === "flashback")!;
    const original = videoTrack.items.find((item) => item.id === "itm_v1_main")!;
    expect(teaser).toMatchObject({ timelineStart: 0, sourceIn: 12, sourceOut: 14, editorRole: "flashback" });
    expect(original.timelineStart).toBeCloseTo(2.2);
    expect(projectDuration(p)).toBeCloseTo(originalDuration + 2.2);
    expect(activeVideoItemsAtTime(p, 2.1)).toHaveLength(0);
    expect(p.inPoint).toBeCloseTo(12.2);
    expect(p.outPoint).toBeCloseTo(14.2);
    const audioTeaser = p.tracks.flatMap((track) => track.items).find((item) => item.editorRole === "flashback" && item.audio && !item.video);
    expect(audioTeaser).toBeDefined();
    expect(audioTeaser!.sourceIn).toBe(12);
    expect(audioTeaser!.sourceOut).toBe(14);
    expect(p.selection.itemIds).toEqual([teaser.id, audioTeaser!.id]);
    expect(teaser.linkedGroupId).toBe(audioTeaser!.linkedGroupId);
  });

  it("appends another marked moment to an existing flashback teaser block", () => {
    let p = createFixtureProject();
    ({ project: p } = reduce(p, {
      type: "CREATE_FLASHBACK", itemId: "itm_v1_main",
      rangeStart: 10, rangeEnd: 12, insertAt: 0, separatorDuration: 0.2,
    }));
    ({ project: p } = reduce(p, {
      type: "CREATE_FLASHBACK", itemId: "itm_v1_main",
      rangeStart: 14.2, rangeEnd: 15.2, insertAt: 2.2, separatorDuration: 0.2,
    }));

    const teasers = p.tracks.find((track) => track.id === "trk_v1")!.items
      .filter((item) => item.editorRole === "flashback")
      .sort((left, right) => left.timelineStart - right.timelineStart);
    expect(teasers).toHaveLength(2);
    expect(teasers.map((item) => item.timelineStart)).toEqual([0, 2.2]);
    expect(teasers[1]).toMatchObject({ sourceIn: 14, sourceOut: 15 });
    expect(activeVideoItemsAtTime(p, 3.3)).toHaveLength(0);
  });

  it("adds a suggested source flashback even when that range is absent from the rough cut", () => {
    let p = createFixtureProject();
    p.contentMode = "long_form";
    p.assets.ast_source_clip.origin = "local-vod";
    p.assets.ast_source_clip.duration = 1200;
    p.longformPlan = {
      strategy: "rough_cut",
      appliedFlashbacks: [],
      chapters: [{
        id: "chapter_01", title: "The setup", timelineStart: 0, timelineEnd: 30,
        sourceStart: 100, sourceEnd: 130, beatIds: ["beat_setup"], role: "setup",
      }],
      youtubePackage: {
        title: "Challenge", description: "Description", tags: ["challenge"], chapterText: "0:00 The setup",
        qualityReport: { grade: "ready", warnings: [], metrics: { selectedSeconds: 30, sourceCoverage: .1, targetSeconds: 30, roleCoverage: ["setup"] } },
      },
      flashbackSuggestions: [{
        beatId: "beat_payoff", title: "Payoff", role: "payoff",
        sourceStart: 900, sourceEnd: 908, score: .9, why: "late payoff",
      }],
    };
    const before = projectDuration(p);
    ({ project: p } = reduce(p, {
      type: "CREATE_SOURCE_FLASHBACK",
      assetId: "ast_source_clip",
      trackId: "trk_v1",
      sourceIn: 900,
      sourceOut: 908,
      beatId: "beat_payoff",
      insertAt: 0,
      separatorDuration: .2,
    }));
    const teaser = findItem(p, p.selection.itemIds[0])!.item;
    expect(teaser).toMatchObject({ sourceIn: 900, sourceOut: 908, timelineStart: 0, editorRole: "flashback" });
    expect(p.longformPlan?.appliedFlashbacks).toEqual(["beat_payoff"]);
    expect(p.longformPlan?.chapters?.[0]).toMatchObject({ id: "chapter_cold_open", title: "Cold open", timelineStart: 0, timelineEnd: 8.2 });
    expect(p.longformPlan?.chapters?.[1].timelineStart).toBeCloseTo(8.2);
    expect(p.longformPlan?.youtubePackage?.chapterText).toBe("0:00 Cold open\n0:08 The setup");
    expect(projectDuration(p)).toBeCloseTo(before + 8.2);
    expect(p.tracks.flatMap((track) => track.items).filter((item) => item.id !== teaser.id).every((item) => item.timelineStart >= 8.2)).toBe(true);
  });

  it("edits YouTube delivery metadata with platform limits", () => {
    let p = createFixtureProject();
    p.contentMode = "long_form";
    p.longformPlan = {
      strategy: "rough_cut",
      youtubePackage: {
        title: "Old", description: "Old", tags: [], chapterText: "",
        qualityReport: { grade: "ready", warnings: [], metrics: { selectedSeconds: 0, sourceCoverage: 0, targetSeconds: 0, roleCoverage: [] } },
      },
    };
    ({ project: p } = reduce(p, { type: "SET_YOUTUBE_PACKAGE", changes: { title: "x".repeat(120), tags: [" one ", "", "two"] } }));
    expect(p.longformPlan?.youtubePackage?.title).toHaveLength(100);
    expect(p.longformPlan?.youtubePackage?.tags).toEqual(["one", "two"]);
  });

  it("moves B-roll onto the upper video track and mutes competing audio", () => {
    let p = createFixtureProject();
    ({ project: p } = reduce(p, {
      type: "APPLY_CREATIVE_TREATMENT",
      itemId: "itm_v1_main",
      treatment: "pip",
      targetTrackId: "trk_v2",
    }));
    const item = findItem(p, "itm_v1_main")!.item;
    expect(item.trackId).toBe("trk_v2");
    expect(item.editorRole).toBe("b_roll");
    expect(item.audio?.volume).toBe(0);
    expect(item.video).toMatchObject({ x: 1190, y: 43, width: 691, height: 389, fit: "contain" });
  });

  it("keeps meme audio available while applying a centered treatment", () => {
    const p = createFixtureProject();
    const originalVolume = findItem(p, "itm_v1_main")!.item.audio?.volume;
    const result = reduce(p, { type: "APPLY_CREATIVE_TREATMENT", itemId: "itm_v1_main", treatment: "meme" });
    const item = findItem(result.project, "itm_v1_main")!.item;
    expect(item.editorRole).toBe("meme_insert");
    expect(item.audio?.volume).toBe(originalVolume);
    expect(item.video?.fit).toBe("contain");
  });

  it("invalidates final playback approval after an editorial change", () => {
    let p = createFixtureProject();
    p.longformPlan = {
      strategy: "rough_cut",
      youtubePackage: {
        title: "Challenge", description: "A complete challenge description", tags: ["challenge"], chapterText: "",
        qualityReport: { grade: "ready", warnings: [], metrics: { selectedSeconds: 30, sourceCoverage: .1, targetSeconds: 30, roleCoverage: ["setup", "payoff"] } },
        review: { captionsReviewed: true, audioReviewed: true, rightsCleared: true, thumbnailReady: true, finalPlaybackReviewed: true, notes: "" },
      },
    };
    ({ project: p } = reduce(p, { type: "SET_ITEM_TRANSFORM", itemId: "itm_v1_main", transform: { opacity: .8 } }));
    expect(p.longformPlan?.youtubePackage?.review?.finalPlaybackReviewed).toBe(false);
  });

  it("persists mix and color-fade transitions while positioning the incoming clip", () => {
    let p = createFixtureProject();
    ({ project: p } = reduce(p, {
      type: "ADD_ITEM",
      item: {
        id: "itm_v1_second", assetId: "ast_source_clip", trackId: "trk_v1",
        timelineStart: 18, sourceIn: 20, sourceOut: 30, speed: 1,
        linkedGroupId: null, enabled: true,
        video: { x: 0, y: 0, width: 1920, height: 1080, rotation: 0, opacity: 1, crop: null, fit: "contain" },
      },
    }));
    ({ project: p } = reduce(p, { type: "SET_TRANSITION", fromItemId: "itm_v1_main", toItemId: "itm_v1_second", kind: "mix", duration: 1 }));
    expect(p.transitions).toEqual([expect.objectContaining({ kind: "mix", duration: 1 })]);
    expect(findItem(p, "itm_v1_second")!.item.timelineStart).toBe(17);

    ({ project: p } = reduce(p, { type: "SET_TRANSITION", fromItemId: "itm_v1_main", toItemId: "itm_v1_second", kind: "fade_white", duration: 0.6 }));
    expect(p.transitions).toEqual([expect.objectContaining({ kind: "fade_white", duration: 0.6 })]);
    expect(findItem(p, "itm_v1_second")!.item.timelineStart).toBe(18);
    expect(deserializeProject(serializeProject(p)).transitions).toEqual(p.transitions);
  });
});
