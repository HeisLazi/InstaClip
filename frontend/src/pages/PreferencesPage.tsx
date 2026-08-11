/**
 * Preferences — common knobs as a form, plus a raw JSON editor for everything
 * else. Live-edits patch settings.json + mirror into the running cfg namespace.
 */

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  FileJson,
  FolderOpen,
  Loader2,
  RotateCcw,
  Save,
} from "lucide-react";

import { api } from "@/api/client";
import { cn } from "@/lib/utils";
import { PageHeader, PageBody } from "./_shared";

export function PreferencesPage() {
  return (
    <>
      <PageHeader
        title="Preferences"
        subtitle="Tune Whisper, scoring weights, and paths. The common stuff is a form; everything else is the raw JSON below."
      />
      <PageBody>
        <CommonCard />
        <RawJsonCard />
      </PageBody>
    </>
  );
}

// ---------------------------------------------------------------------------

function CommonCard() {
  const qc = useQueryClient();
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings.get });

  const patch = useMutation({
    mutationFn: (body: Record<string, any>) => api.settings.patch(body),
    onSuccess:  () => qc.invalidateQueries({ queryKey: ["settings", "status"] }),
  });

  const s = settings.data;
  if (!s) {
    return (
      <div className="premium-card rounded-xl surface-1 border border-border/50 p-5 text-sm text-muted-foreground">
        Loading settings…
      </div>
    );
  }

  const ce = s.clip_engine ?? {};
  const wh = s.whisper ?? {};
  const ft = s.fetcher ?? {};

  const weight = (k: string, fallback = 0) =>
    typeof ce.score_weights?.[k] === "number" ? ce.score_weights[k] : fallback;

  function patchWeight(k: string, v: number) {
    patch.mutate({ clip_engine: { score_weights: { ...ce.score_weights, [k]: v } } });
  }

  return (
    <div className="premium-card rounded-xl surface-1 border border-border/50 p-5 space-y-5">
      <div className="flex items-center justify-between">
        <div className="text-sm font-semibold">Common settings</div>
        <div className="text-[11px] text-muted-foreground">
          Edits save instantly to <code>config/settings.json</code>.
        </div>
      </div>

      {/* Whisper */}
      <Section title="Whisper (transcription)">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <SelectField
            label="Device"
            value={wh.device ?? "cpu"}
            options={["cpu", "cuda"]}
            onChange={(v) => patch.mutate({ whisper: { device: v } })}
            hint="cuda needs NVIDIA + cuBLAS DLLs"
          />
          <SelectField
            label="Model size"
            value={wh.model_size ?? "small"}
            options={["tiny", "base", "small", "medium", "large-v3"]}
            onChange={(v) => patch.mutate({ whisper: { model_size: v } })}
            hint="Bigger = slower + more accurate"
          />
          <SelectField
            label="Compute type"
            value={wh.compute_type ?? "int8"}
            options={["int8", "int8_float16", "float16", "float32"]}
            onChange={(v) => patch.mutate({ whisper: { compute_type: v } })}
            hint="int8 = fastest CPU, float16 = GPU"
          />
          <NumField
            label="Beam size"
            value={wh.beam_size ?? 5}
            min={1} max={10} step={1}
            onChange={(v) => patch.mutate({ whisper: { beam_size: v } })}
            hint="Higher = better quality, slower"
          />
        </div>
      </Section>

      {/* Clip engine: thresholds */}
      <Section title="Clip engine — thresholds + windows">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <NumField
            label="Highlight threshold"
            value={ce.highlight_threshold ?? 0.55}
            min={0} max={1} step={0.01}
            onChange={(v) => patch.mutate({ clip_engine: { highlight_threshold: v } })}
            hint="Min combined score to keep a clip"
          />
          <NumField
            label="Pre-roll (sec)"
            value={ce.pre_roll_seconds ?? 10}
            min={0} max={60} step={1}
            onChange={(v) => patch.mutate({ clip_engine: { pre_roll_seconds: v } })}
            hint="Seconds before the peak"
          />
          <NumField
            label="Post-roll (sec)"
            value={ce.post_roll_seconds ?? 40}
            min={0} max={120} step={1}
            onChange={(v) => patch.mutate({ clip_engine: { post_roll_seconds: v } })}
            hint="Seconds after the peak"
          />
          <NumField
            label="Quality min-keep"
            value={ce.quality_min_keep ?? 0.35}
            min={0} max={1} step={0.01}
            onChange={(v) => patch.mutate({ clip_engine: { quality_min_keep: v } })}
            hint="LLM classifier drops clips below this"
          />
        </div>
      </Section>

      {/* Clip engine: weights */}
      <Section title="Clip engine — score weights">
        <p className="text-[11px] text-muted-foreground mb-2">
          Relative pull of each scoring signal. Don't need to sum to 1.
        </p>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          {[
            ["audio_spike",   "Audio spike"],
            ["explosion",     "Explosion (silence → spike)"],
            ["repetition",    "Repetition"],
            ["profile_match", "Profile word match"],
            ["face_reaction", "Face reaction"],
            ["keyword_spike", "Keyword + spike"],
          ].map(([k, label]) => (
            <NumField
              key={k}
              label={label}
              value={weight(k)}
              min={0} max={1} step={0.01}
              onChange={(v) => patchWeight(k, v)}
            />
          ))}
        </div>
      </Section>

      {/* Paths */}
      <Section title="Paths">
        <div className="space-y-2">
          <TextField
            label="Local VOD folder"
            value={ft.local_vod_dir ?? ""}
            onSave={(v) => patch.mutate({ fetcher: { local_vod_dir: v } })}
            icon={FolderOpen}
            placeholder="e.g. C:\\Streams\\VODs"
          />
        </div>
      </Section>
    </div>
  );
}

// ---------------------------------------------------------------------------

function RawJsonCard() {
  const qc = useQueryClient();
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings.get });

  const initialText = useMemo(
    () => (settings.data ? JSON.stringify(settings.data, null, 2) : ""),
    [settings.data],
  );

  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<number | null>(null);

  // Reset draft when the remote settings change AND the user hasn't edited.
  useEffect(() => {
    if (!text || text === "") setText(initialText);
  }, [initialText, text]);

  function reset() {
    setText(initialText);
    setError(null);
    setSaved(null);
  }

  const dirty = text !== initialText;

  const save = useMutation({
    mutationFn: async () => {
      let parsed: any;
      try {
        parsed = JSON.parse(text);
      } catch (e: any) {
        throw new Error(`Invalid JSON: ${e.message}`);
      }
      // Patch the whole document at once.
      return api.settings.patch(parsed);
    },
    onMutate:   () => { setError(null); },
    onSuccess:  () => { setSaved(Date.now()); qc.invalidateQueries({ queryKey: ["settings", "status"] }); },
    onError:    (e: any) => setError(e.message ?? "Save failed"),
  });

  return (
    <div className="premium-card rounded-xl surface-1 border border-border/50 p-5 space-y-4">
      <header className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <FileJson className="h-4 w-4 text-muted-foreground" />
          <div>
            <div className="text-sm font-semibold">Raw settings.json</div>
            <div className="text-xs text-muted-foreground">
              Edit anything not exposed in the form above. Validated on Save.
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            disabled={!dirty || save.isPending}
            onClick={reset}
            className="text-xs px-3 py-1.5 rounded border border-border/60 text-muted-foreground hover:text-foreground hover:bg-accent disabled:opacity-50 flex items-center gap-1.5"
          >
            <RotateCcw className="h-3 w-3" /> Reset
          </button>
          <button
            disabled={!dirty || save.isPending}
            onClick={() => save.mutate()}
            className={cn(
              "text-xs px-3 py-1.5 rounded font-medium flex items-center gap-1.5",
              dirty
                ? "bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                : "bg-secondary text-muted-foreground cursor-not-allowed",
            )}
          >
            {save.isPending
              ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
              : <Save className="h-3.5 w-3.5" />}
            Save
          </button>
        </div>
      </header>

      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        spellCheck={false}
        className="w-full h-[420px] bg-secondary/40 rounded-md border border-border/60 px-3 py-2 text-[12px] font-mono leading-relaxed outline-none focus:ring-1 focus:ring-primary"
      />

      <div className="flex items-center gap-3 text-xs">
        {dirty && !error && (
          <span className="flex items-center gap-1.5 text-warning">
            <AlertTriangle className="h-3 w-3" /> Unsaved changes
          </span>
        )}
        {error && (
          <span className="text-destructive">{error}</span>
        )}
        {saved && !dirty && (
          <span className="flex items-center gap-1.5 text-success">
            <CheckCircle2 className="h-3 w-3" /> Saved.
          </span>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// shared field primitives
// ---------------------------------------------------------------------------

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground mb-2">
        {title}
      </div>
      {children}
    </section>
  );
}

interface SelectFieldProps {
  label: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
  hint?: string;
}

function SelectField({ label, value, options, onChange, hint }: SelectFieldProps) {
  return (
    <FieldBox label={label} hint={hint}>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-secondary/60 px-2 py-1.5 rounded text-xs outline-none focus:ring-1 focus:ring-primary"
      >
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </FieldBox>
  );
}

interface NumFieldProps {
  label: string;
  value: number;
  min?: number; max?: number; step?: number;
  onChange: (v: number) => void;
  hint?: string;
}

function NumField({ label, value, min, max, step, onChange, hint }: NumFieldProps) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  return (
    <FieldBox label={label} hint={hint}>
      <input
        type="number"
        value={draft}
        min={min} max={max} step={step}
        onChange={(e) => setDraft(Number(e.target.value))}
        onBlur={() => { if (draft !== value) onChange(draft); }}
        onKeyDown={(e) => {
          if (e.key === "Enter") (e.target as HTMLInputElement).blur();
        }}
        className="w-full bg-secondary/60 px-2 py-1.5 rounded text-xs outline-none focus:ring-1 focus:ring-primary tabular-nums"
      />
    </FieldBox>
  );
}

interface TextFieldProps {
  label: string;
  value: string;
  placeholder?: string;
  hint?: string;
  icon?: React.ComponentType<{ className?: string }>;
  onSave: (v: string) => void;
}

function TextField({ label, value, placeholder, hint, icon: Icon, onSave }: TextFieldProps) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const dirty = draft !== value;
  return (
    <FieldBox label={label} hint={hint}>
      <div className="flex items-center gap-2">
        {Icon && <Icon className="h-3.5 w-3.5 text-muted-foreground shrink-0" />}
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={placeholder}
          className="flex-1 bg-secondary/60 px-2 py-1.5 rounded text-xs outline-none focus:ring-1 focus:ring-primary placeholder:text-muted-foreground"
        />
        {dirty && (
          <button
            onClick={() => onSave(draft)}
            className="text-[11px] px-2 py-1 rounded bg-primary text-primary-foreground hover:bg-primary/90"
          >
            Save
          </button>
        )}
      </div>
    </FieldBox>
  );
}

function FieldBox({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[11px] text-muted-foreground mb-1">{label}</div>
      {children}
      {hint && <div className="text-[10px] text-muted-foreground/80 mt-1">{hint}</div>}
    </div>
  );
}
