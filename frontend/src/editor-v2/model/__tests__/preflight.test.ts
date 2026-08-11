import { describe, expect, it } from "vitest";

import { buildYouTubePreflight, createFixtureProject } from "..";

function readyProject() {
  const project = createFixtureProject();
  project.contentMode = "long_form";
  project.export = { ...project.export, width: 1920, height: 1080, range: "full", quality: "high" };
  const main = project.tracks.flatMap((track) => track.items).find((item) => item.id === "itm_v1_main")!;
  main.sourceOut = main.sourceIn + 60;
  project.longformPlan = {
    strategy: "rough_cut",
    chapters: [
      { id: "c1", title: "Cold open", timelineStart: 0, timelineEnd: 15, sourceStart: 50, sourceEnd: 65, beatIds: [], role: "payoff" },
      { id: "c2", title: "Setup", timelineStart: 15, timelineEnd: 35, sourceStart: 100, sourceEnd: 120, beatIds: [], role: "setup" },
      { id: "c3", title: "Payoff", timelineStart: 35, timelineEnd: 60, sourceStart: 500, sourceEnd: 525, beatIds: [], role: "payoff" },
    ],
    qualityReport: { grade: "ready", warnings: [], metrics: { selectedSeconds: 60, sourceCoverage: .1, targetSeconds: 60, roleCoverage: ["setup", "payoff"] } },
    youtubePackage: {
      title: "Rocomamas Challenge", description: "The complete challenge from setup through the final payoff.", tags: ["rocomamas", "challenge"], chapterText: "0:00 Cold open\n0:15 Setup\n0:35 Payoff",
      qualityReport: { grade: "ready", warnings: [], metrics: { selectedSeconds: 60, sourceCoverage: .1, targetSeconds: 60, roleCoverage: ["setup", "payoff"] } },
      review: { captionsReviewed: true, audioReviewed: true, rightsCleared: true, thumbnailReady: true, finalPlaybackReviewed: true, notes: "" },
    },
  };
  return project;
}

describe("YouTube export preflight", () => {
  it("passes a complete creator-reviewed landscape project", () => {
    const result = buildYouTubePreflight(readyProject());
    expect(result.ready).toBe(true);
    expect(result.checks.every((check) => check.status === "pass")).toBe(true);
  });

  it("fails chapters that do not begin at zero", () => {
    const project = readyProject();
    project.longformPlan!.chapters![0].timelineStart = 8;
    const result = buildYouTubePreflight(project);
    expect(result.ready).toBe(false);
    expect(result.checks.find((check) => check.id === "chapters")?.status).toBe("fail");
  });
});
