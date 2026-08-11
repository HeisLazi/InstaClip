import { useEffect, useState } from "react";

import { api } from "@/api/client";

const cache = new Map<string, number[]>();

export function Waveform({ projectId, assetId }: { projectId: string; assetId: string }) {
  const key = `${projectId}/${assetId}`;
  const [peaks, setPeaks] = useState<number[]>(cache.get(key) ?? []);

  useEffect(() => {
    if (cache.has(key)) return;
    let cancelled = false;
    api.edit.v2.waveform(projectId, assetId, 360)
      .then((result) => {
        cache.set(key, result.peaks);
        if (!cancelled) setPeaks(result.peaks);
      })
      .catch(() => {
        if (!cancelled) setPeaks([]);
      });
    return () => { cancelled = true; };
  }, [assetId, key, projectId]);

  if (peaks.length === 0) {
    return <div className="absolute inset-x-2 top-1/2 h-px bg-current opacity-25" />;
  }
  const step = Math.max(1, Math.ceil(peaks.length / 120));
  const shown = peaks.filter((_, index) => index % step === 0);
  return (
    <svg className="absolute inset-0 h-full w-full opacity-65" preserveAspectRatio="none" viewBox={`0 0 ${shown.length} 2`} aria-hidden="true">
      <path
        d={shown.map((peak, index) => `${index === 0 ? "M" : "L"}${index},${1 - peak * 0.9}`).join(" ") + shown.slice().reverse().map((peak, reverseIndex) => ` L${shown.length - 1 - reverseIndex},${1 + peak * 0.9}`).join("") + " Z"}
        fill="currentColor"
      />
    </svg>
  );
}
