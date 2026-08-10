import type { Bucket } from "@/api/client";
import type { EditorAsset } from "@/editor-v2/model";
import type { AssetSource } from "@/editor-v2/useEditorProject";

export const EDITOR_ASSET_MIME = "application/x-instaclip-editor-asset";
const TEXT_PREFIX = "instaclip-editor-asset:";

export type DragAsset =
  | { type: "asset"; asset: EditorAsset }
  | { type: "clip"; bucket: Bucket; stem: string }
  | { type: "media"; mediaId: string }
  | { type: "sound"; soundName: string };

export function setAssetDrag(event: React.DragEvent, source: DragAsset): void {
  event.dataTransfer.effectAllowed = "copy";
  const serialized = JSON.stringify(source);
  event.dataTransfer.setData(EDITOR_ASSET_MIME, serialized);
  // WebView2 can omit custom MIME data on drop, so retain a namespaced fallback.
  event.dataTransfer.setData("text/plain", `${TEXT_PREFIX}${serialized}`);
}

export function readAssetDrag(event: React.DragEvent): AssetSource | null {
  const custom = event.dataTransfer.getData(EDITOR_ASSET_MIME);
  const plain = event.dataTransfer.getData("text/plain");
  const raw = custom || (plain.startsWith(TEXT_PREFIX) ? plain.slice(TEXT_PREFIX.length) : "");
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AssetSource;
  } catch {
    return null;
  }
}
