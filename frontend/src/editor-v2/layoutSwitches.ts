import type { LayoutScanResult } from "@/api/client";
import type { EditorProjectV2 } from "@/editor-v2/model";

export type TimelineLayoutSwitch = {
  itemId: string;
  time: number;
  sourceTime: number;
  label: string;
};

export function mapLayoutSwitches(project: EditorProjectV2, scan: LayoutScanResult | null): TimelineLayoutSwitch[] {
  if (!scan) return [];
  const primaryAssetId = Object.keys(project.assets)[0];
  if (!primaryAssetId) return [];

  return scan.switches.flatMap((sourceTime, index) => {
    for (const track of project.tracks) {
      if (track.kind !== "video") continue;
      const item = track.items.find((candidate) =>
        candidate.assetId === primaryAssetId
        && sourceTime > candidate.sourceIn
        && sourceTime < candidate.sourceOut,
      );
      if (!item) continue;
      const segment = scan.segments.find((candidate) => candidate.start >= sourceTime - 0.05) ?? scan.segments[index + 1];
      return [{
        itemId: item.id,
        time: item.timelineStart + (sourceTime - item.sourceIn) / item.speed,
        sourceTime,
        label: segment?.layout ?? "switch",
      }];
    }
    return [];
  });
}
