import { describe, expect, it } from "vitest";

import { createFixtureProject, findItem, reduce, type Command } from "..";

describe("Editor V2 model invariants", () => {
  it("is deterministic for commands that generate IDs", () => {
    const project = createFixtureProject();
    const command: Command = { type: "SPLIT_ITEMS", itemIds: ["itm_v1_main"], time: 5 };
    expect(reduce(project, command).project).toEqual(reduce(project, command).project);
  });

  it("moves linked video and detached audio together", () => {
    const project = reduce(createFixtureProject(), {
      type: "MOVE_ITEMS",
      itemIds: ["itm_v1_main"],
      deltaTime: 2,
    }).project;
    expect(findItem(project, "itm_v1_main")?.item.timelineStart).toBe(2);
    expect(findItem(project, "itm_a1_detached")?.item.timelineStart).toBe(2);
  });

  it("trims and changes speed across a linked group", () => {
    let project = reduce(createFixtureProject(), {
      type: "TRIM_ITEM",
      itemId: "itm_v1_main",
      edge: "end",
      delta: -2,
    }).project;
    project = reduce(project, {
      type: "SET_ITEM_SPEED",
      itemId: "itm_v1_main",
      speed: 1.5,
    }).project;
    expect(findItem(project, "itm_v1_main")?.item.sourceOut).toBe(18);
    expect(findItem(project, "itm_a1_detached")?.item.sourceOut).toBe(18);
    expect(findItem(project, "itm_a1_detached")?.item.speed).toBe(1.5);
  });

  it("rejects moving audio-only items onto video tracks", () => {
    expect(() => reduce(createFixtureProject(), {
      type: "MOVE_ITEMS",
      itemIds: ["itm_a2_boom1"],
      deltaTime: 0,
      targetTrackId: "trk_v1",
    })).toThrow(/incompatible/);
  });

  it("rejects edits on locked tracks", () => {
    let project = reduce(createFixtureProject(), {
      type: "SET_TRACK_LOCK",
      trackId: "trk_a2",
      locked: true,
    }).project;
    expect(() => reduce(project, {
      type: "MOVE_ITEMS",
      itemIds: ["itm_a2_boom1"],
      deltaTime: 1,
    })).toThrow(/locked/);
  });
});
