import { describe, expect, it } from "vitest";

import { mapLayoutSwitches } from "@/editor-v2/layoutSwitches";
import { createFixtureProject } from "@/editor-v2/model";

describe("mapLayoutSwitches", () => {
  it("maps source layout changes onto a trimmed timeline item", () => {
    const project = createFixtureProject();
    const video = project.tracks.find((track) => track.kind === "video")!;
    const item = video.items[0];
    item.sourceIn = 10;
    item.sourceOut = 30;
    item.timelineStart = 4;
    item.speed = 2;

    const points = mapLayoutSwitches(project, {
      switches: [14, 24],
      has_layout_switch: true,
      segments: [
        { start: 0, end: 14, layout: "fullcam" },
        { start: 14, end: 24, layout: "smallcam" },
        { start: 24, end: 30, layout: "noface" },
      ],
    });

    expect(points.map((point) => point.time)).toEqual([6, 11]);
    expect(points.map((point) => point.label)).toEqual(["smallcam", "noface"]);
    expect(points.every((point) => point.itemId === item.id)).toBe(true);
  });

  it("omits source switches removed from the current timeline", () => {
    const project = createFixtureProject();
    const video = project.tracks.find((track) => track.kind === "video")!;
    const item = video.items[0];
    item.sourceIn = 20;
    item.sourceOut = 40;

    const points = mapLayoutSwitches(project, {
      switches: [10, 30],
      has_layout_switch: true,
      segments: [
        { start: 0, end: 10, layout: "fullcam" },
        { start: 10, end: 30, layout: "smallcam" },
        { start: 30, end: 40, layout: "fullcam" },
      ],
    });

    expect(points).toHaveLength(1);
    expect(points[0].sourceTime).toBe(30);
  });
});
