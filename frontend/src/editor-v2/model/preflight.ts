import { allItems, projectDuration } from "./selectors";
import { itemEnd, type EditorProjectV2 } from "./types";

export type PreflightCheck = {
  id: string;
  label: string;
  detail: string;
  status: "pass" | "fail" | "pending";
  kind: "automatic" | "manual";
  reviewKey?: "captionsReviewed" | "audioReviewed" | "rightsCleared" | "thumbnailReady" | "finalPlaybackReviewed";
};
type ReviewKey = NonNullable<PreflightCheck["reviewKey"]>;

export function buildYouTubePreflight(project: EditorProjectV2): { ready: boolean; checks: PreflightCheck[] } {
  const youtube = project.longformPlan?.youtubePackage;
  const chapters = [...(project.longformPlan?.chapters ?? [])].sort((left, right) => left.timelineStart - right.timelineStart);
  const duration = projectDuration(project);
  const title = youtube?.title.trim() ?? "";
  const description = youtube?.description.trim() ?? "";
  const chapterStartsAtZero = chapters.length > 0 && Math.abs(chapters[0].timelineStart) < 0.5;
  const ascending = chapters.every((chapter, index) => index === 0 || chapter.timelineStart > chapters[index - 1].timelineStart);
  const minimumChapterLength = chapters.every((chapter, index) => {
    const nextStart = chapters[index + 1]?.timelineStart ?? duration;
    return nextStart - chapter.timelineStart >= 10;
  });
  const aspect = project.export.width / Math.max(1, project.export.height);
  const hasVisibleVideo = allItems(project).some((item) => item.enabled && item.video && itemEnd(item) > 0);
  const qcBlocked = project.longformPlan?.qualityReport?.grade === "blocked";
  const automatic: PreflightCheck[] = [
    { id: "title", label: "YouTube title", detail: "Required and limited to 100 characters.", status: title.length >= 5 && title.length <= 100 ? "pass" : "fail", kind: "automatic" },
    { id: "description", label: "Description", detail: "Add a useful description before delivery.", status: description.length >= 20 ? "pass" : "fail", kind: "automatic" },
    { id: "chapters", label: "Valid manual chapters", detail: "Starts at 0:00, at least 3 timestamps, ascending, each at least 10 seconds.", status: chapterStartsAtZero && chapters.length >= 3 && ascending && minimumChapterLength ? "pass" : "fail", kind: "automatic" },
    { id: "canvas", label: "Landscape YouTube frame", detail: `${project.export.width}x${project.export.height} output.`, status: aspect >= 1.7 && aspect <= 1.8 ? "pass" : "fail", kind: "automatic" },
    { id: "range", label: "Full timeline export", detail: "Final delivery should render the full edit, not a marked review range.", status: project.export.range === "full" ? "pass" : "fail", kind: "automatic" },
    { id: "video", label: "Visible video", detail: "At least one enabled video layer is required.", status: hasVisibleVideo ? "pass" : "fail", kind: "automatic" },
    { id: "qc", label: "Editorial QC", detail: qcBlocked ? "Resolve blocking story warnings." : "No blocking story warnings.", status: qcBlocked ? "fail" : "pass", kind: "automatic" },
  ];
  const review = youtube?.review;
  const manualDefinitions: Array<[ReviewKey, string, string]> = [
    ["captionsReviewed", "Captions reviewed", "Check wording, timing, spelling, and safe placement."],
    ["audioReviewed", "Audio reviewed", "Listen for dialogue clarity, clipping, and layered SFX balance."],
    ["rightsCleared", "Media rights cleared", "Confirm every meme, image, music, and B-roll asset is safe to publish."],
    ["thumbnailReady", "Thumbnail ready", "Confirm the final thumbnail and title work together."],
    ["finalPlaybackReviewed", "Final playback reviewed", "Watch the exported file from beginning to end."],
  ];
  const manual = manualDefinitions.map(([reviewKey, label, detail]): PreflightCheck => ({
    id: reviewKey, label, detail, reviewKey, kind: "manual",
    status: review?.[reviewKey] ? "pass" : "pending",
  }));
  const checks = [...automatic, ...manual];
  return { ready: checks.every((check) => check.status === "pass"), checks };
}
