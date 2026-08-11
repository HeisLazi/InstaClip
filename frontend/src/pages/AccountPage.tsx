import { useEffect, useState } from "react";
import { ExternalLink, ShieldCheck } from "lucide-react";

import { api } from "@/api/client";
import { openExternalUrl } from "@/lib/tauri";
import { PageHeader } from "./_shared";

const PRIVACY_URL = "https://example.com/privacy";
const TERMS_URL = "https://example.com/terms";

function LegalLinks() {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-muted-foreground">
      <span>Local edition: no cloud account is required. All processing happens on this device.</span>
      <button type="button" onClick={() => void openExternalUrl(PRIVACY_URL)} className="inline-flex items-center gap-1 text-cyan-200/80 hover:text-cyan-100">Privacy <ExternalLink className="h-2.5 w-2.5" /></button>
      <button type="button" onClick={() => void openExternalUrl(TERMS_URL)} className="inline-flex items-center gap-1 text-cyan-200/80 hover:text-cyan-100">Terms <ExternalLink className="h-2.5 w-2.5" /></button>
    </div>
  );
}

export function AccountPage() {
  const [preflight, setPreflight] = useState<{ ready: boolean; free_disk_gb: number; ffmpeg: string; workspace: string; models?: { face_landmarker_present: boolean; whisper_model: string; note: string } } | null>(null);

  useEffect(() => {
    api.tester.preflight().then(setPreflight).catch(() => undefined);
  }, []);

  return (
    <div>
      <PageHeader title="Local edition" subtitle="Status, support bundle, and legal links." />
      <div className="mx-auto max-w-2xl space-y-4 px-5 py-6">
        <div className="surface-1 rounded-2xl border border-border/50 p-5">
          <div className="flex items-center justify-between gap-4">
            <div>
              <div className="text-lg font-semibold">Local edition</div>
              <div className="mt-1 text-xs uppercase tracking-wider text-emerald-300">No cloud account required</div>
            </div>
            <ShieldCheck className="h-8 w-8 text-emerald-300" />
          </div>
          {preflight && (
            <div className={`mt-4 rounded-lg border p-3 text-xs ${preflight.ready ? "border-emerald-400/25 bg-emerald-400/[0.06]" : "border-amber-400/25 bg-amber-400/[0.06]"}`}>
              <div className="font-medium">Local processing {preflight.ready ? "ready" : "needs attention"}</div>
              <div className="mt-1 text-[10px] text-muted-foreground">{preflight.free_disk_gb} GB free · FFmpeg {preflight.ffmpeg ? "found" : "missing"} · {preflight.workspace}</div>
              {preflight.models && (
                <div className="mt-2 rounded-md border border-white/5 bg-black/15 px-2.5 py-2 text-[10px] leading-4 text-muted-foreground">
                  <span className="font-medium text-foreground">Speech model: {preflight.models.whisper_model}</span>
                  <span className="block">{preflight.models.note}</span>
                </div>
              )}
            </div>
          )}
          <div className="mt-5 flex flex-wrap gap-2">
            <a href={api.tester.supportBundleUrl()} className="inline-flex items-center rounded-md border border-border/60 px-3 py-2 text-xs text-muted-foreground hover:text-foreground">Export redacted support bundle</a>
          </div>
          <div className="mt-4 border-t border-border/40 pt-4"><LegalLinks /></div>
        </div>
      </div>
    </div>
  );
}
