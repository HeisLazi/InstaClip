import { describe, expect, it } from "vitest";

import { filterBatchVods, type BatchVod } from "@/components/batchFilters";

const vods: BatchVod[] = [
  { name: "Stream 10.mp4", path: "ten", size_mb: 900, mtime: 10, transcribed: false },
  { name: "Stream 2.mp4", path: "two", size_mb: 1200, mtime: 20, transcribed: true },
  { name: "Challenge.mp4", path: "challenge", size_mb: 6000, mtime: 30, transcribed: false },
];

describe("filterBatchVods", () => {
  it("combines name, transcript-state, and file-size filters", () => {
    expect(filterBatchVods(vods, {
      query: "stream",
      status: "unprocessed",
      size: "small",
      sort: "newest",
    }).map((vod) => vod.path)).toEqual(["ten"]);
  });

  it("keeps size bands non-overlapping at their boundaries", () => {
    expect(filterBatchVods(vods, { query: "", status: "all", size: "small", sort: "newest" }).map((vod) => vod.path)).toEqual(["ten"]);
    expect(filterBatchVods(vods, { query: "", status: "all", size: "medium", sort: "newest" }).map((vod) => vod.path)).toEqual(["two"]);
    expect(filterBatchVods(vods, { query: "", status: "all", size: "large", sort: "newest" }).map((vod) => vod.path)).toEqual(["challenge"]);
  });

  it("supports natural name order and numeric/date/size ordering", () => {
    expect(filterBatchVods(vods, { query: "", status: "all", size: "all", sort: "name" }).map((vod) => vod.path)).toEqual(["challenge", "two", "ten"]);
    expect(filterBatchVods(vods, { query: "", status: "all", size: "all", sort: "oldest" }).map((vod) => vod.path)).toEqual(["ten", "two", "challenge"]);
    expect(filterBatchVods(vods, { query: "", status: "all", size: "all", sort: "largest" }).map((vod) => vod.path)).toEqual(["challenge", "two", "ten"]);
  });
});
