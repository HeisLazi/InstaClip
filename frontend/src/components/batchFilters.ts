export type BatchVod = {
  name: string;
  path: string;
  size_mb: number;
  mtime: number;
  transcribed: boolean;
};

export type BatchStatusFilter = "all" | "unprocessed" | "transcribed";
export type BatchSizeFilter = "all" | "small" | "medium" | "large";
export type BatchSort = "newest" | "oldest" | "name" | "largest" | "smallest";

export function filterBatchVods(
  vods: BatchVod[],
  options: { query: string; status: BatchStatusFilter; size: BatchSizeFilter; sort: BatchSort },
) {
  const query = options.query.trim().toLowerCase();
  const matches = vods.filter((vod) => {
    if (query && !vod.name.toLowerCase().includes(query)) return false;
    if (options.status === "unprocessed" && vod.transcribed) return false;
    if (options.status === "transcribed" && !vod.transcribed) return false;
    if (options.size === "small" && vod.size_mb >= 1000) return false;
    if (options.size === "medium" && (vod.size_mb < 1000 || vod.size_mb >= 5000)) return false;
    if (options.size === "large" && vod.size_mb < 5000) return false;
    return true;
  });

  return matches.sort((left, right) => {
    if (options.sort === "oldest") return left.mtime - right.mtime;
    if (options.sort === "name") return left.name.localeCompare(right.name, undefined, { numeric: true });
    if (options.sort === "largest") return right.size_mb - left.size_mb;
    if (options.sort === "smallest") return left.size_mb - right.size_mb;
    return right.mtime - left.mtime;
  });
}
