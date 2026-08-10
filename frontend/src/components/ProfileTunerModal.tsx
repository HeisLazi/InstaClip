/**
 * Side-by-side LLM-suggested patch viewer + applier.
 * Matches the redesign doc's "diff view" requirement (Section 9).
 *
 * Workflow:
 *   1. User clicks "Suggest changes" on the Profile page
 *   2. Backend kicks off a job that calls the LLM tuner
 *   3. This modal opens, subscribes to the job, shows live status
 *   4. When the job finishes with a patch payload, the diff renders
 *   5. User ticks the changes they like and clicks "Apply selected"
 */

import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { BookText, Brain, Check, X, Plus, Minus, Loader2, NotebookPen, ShieldAlert } from "lucide-react";

import { api, subscribeJob, type JobInfo } from "@/api/client";
import { cn } from "@/lib/utils";

interface ProfileTunerModalProps {
  jobId: string;
  /**
   * Which tuner produced this job:
   *   "compare" — good-vs-bad clip comparison (legacy)
   *   "reviews" — review-driven (emits context_rules, slang_glossary, avoid_patterns)
   */
  source?: "compare" | "reviews";
  onClose: () => void;
}

interface PatchPayload {
  add:    Record<string, string[]>;
  remove: Record<string, string[]>;
  rationale: string;
  model: string;
  // compare-mode fields:
  n_good?: number;
  n_bad?:  number;
  // review-mode fields:
  n_reviews?:      number;
  context_rules?:  string[];
  slang_glossary?: Record<string, string>;
  avoid_patterns?: string[];
}

export function ProfileTunerModal({ jobId, source = "compare", onClose }: ProfileTunerModalProps) {
  const qc = useQueryClient();
  const [job, setJob] = useState<JobInfo | null>(null);
  const [selectedAdd, setSelectedAdd] = useState<Record<string, Set<string>>>({});
  const [selectedRemove, setSelectedRemove] = useState<Record<string, Set<string>>>({});
  const [selectedRules, setSelectedRules] = useState<Set<string>>(new Set());
  const [selectedSlang, setSelectedSlang] = useState<Set<string>>(new Set());
  const [selectedAvoid, setSelectedAvoid] = useState<Set<string>>(new Set());
  const [applying, setApplying] = useState(false);

  useEffect(() => {
    const unsub = subscribeJob(jobId, (info) => setJob(info));
    return unsub;
  }, [jobId]);

  // When the job finishes, pre-select every suggestion.
  const patch: PatchPayload | null = useMemo(() => {
    if (!job || job.status !== "done" || !job.result) return null;
    return job.result as unknown as PatchPayload;
  }, [job]);

  useEffect(() => {
    if (!patch) return;
    const initAdd: Record<string, Set<string>> = {};
    const initRem: Record<string, Set<string>> = {};
    for (const [k, vs] of Object.entries(patch.add ?? {})) initAdd[k] = new Set(vs);
    for (const [k, vs] of Object.entries(patch.remove ?? {})) initRem[k] = new Set(vs);
    setSelectedAdd(initAdd);
    setSelectedRemove(initRem);
    setSelectedRules(new Set(patch.context_rules ?? []));
    setSelectedSlang(new Set(Object.keys(patch.slang_glossary ?? {})));
    setSelectedAvoid(new Set(patch.avoid_patterns ?? []));
  }, [patch]);

  const isLoading = job?.status === "running" || job?.status === "queued";
  const failed    = job?.status === "failed";

  function toggleAdd(key: string, value: string) {
    setSelectedAdd((prev) => {
      const next = { ...prev };
      const set = new Set(next[key] ?? []);
      set.has(value) ? set.delete(value) : set.add(value);
      next[key] = set;
      return next;
    });
  }

  function toggleRemove(key: string, value: string) {
    setSelectedRemove((prev) => {
      const next = { ...prev };
      const set = new Set(next[key] ?? []);
      set.has(value) ? set.delete(value) : set.add(value);
      next[key] = set;
      return next;
    });
  }

  function toggleSimple(set: Set<string>, value: string, update: (s: Set<string>) => void) {
    const next = new Set(set);
    next.has(value) ? next.delete(value) : next.add(value);
    update(next);
  }

  async function applySelected() {
    if (!patch) return;
    const addObj: Record<string, string[]> = {};
    const remObj: Record<string, string[]> = {};
    for (const [k, set] of Object.entries(selectedAdd)) {
      if (set.size > 0) addObj[k] = Array.from(set);
    }
    for (const [k, set] of Object.entries(selectedRemove)) {
      if (set.size > 0) remObj[k] = Array.from(set);
    }
    const slangObj: Record<string, string> = {};
    if (patch.slang_glossary) {
      for (const word of selectedSlang) {
        const meaning = patch.slang_glossary[word];
        if (meaning) slangObj[word] = meaning;
      }
    }
    setApplying(true);
    try {
      await api.profile.apply({
        add: addObj,
        remove: remObj,
        context_rules: Array.from(selectedRules),
        slang_glossary: slangObj,
        avoid_patterns: Array.from(selectedAvoid),
        save: true,
      });
      qc.invalidateQueries({ queryKey: ["profile"] });
      qc.invalidateQueries({ queryKey: ["profile-memory"] });
      onClose();
    } finally {
      setApplying(false);
    }
  }

  const totalAdd = Object.values(selectedAdd).reduce((n, s) => n + s.size, 0);
  const totalRem = Object.values(selectedRemove).reduce((n, s) => n + s.size, 0);
  const totalMemory = selectedRules.size + selectedSlang.size + selectedAvoid.size;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/72 backdrop-blur-md"
      onClick={onClose}
    >
      <div
        className="glass-strong modal-shell w-[min(960px,92vw)] max-h-[88vh] rounded-xl flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between px-5 py-3 border-b border-border/40">
          <div className="flex items-center gap-2">
            {source === "reviews" ? (
              <NotebookPen className="h-4 w-4 text-primary" />
            ) : (
              <Brain className="h-4 w-4 text-primary" />
            )}
            <div className="text-base font-semibold">
              {source === "reviews"
                ? "Tuner — reading your review notes"
                : "LLM-suggested profile changes"}
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
            title="Close (Esc)"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {isLoading && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground py-12 justify-center">
              <Loader2 className="h-4 w-4 animate-spin text-primary" />
              {source === "reviews"
                ? (job?.progress?.stage === "reading_reviews" ? "LLM is reading your review notes…" : "Starting…")
                : (job?.progress?.stage === "thinking" ? "LLM is comparing your clips…" : "Starting…")}
            </div>
          )}

          {failed && (
            <div className="text-sm text-destructive py-8">
              Tuner failed: {job?.error ?? "unknown"}
            </div>
          )}

          {patch && (
            <>
              <div className="mb-4 rounded-md bg-secondary/40 px-3 py-2.5 text-xs text-foreground/80">
                {source === "reviews"
                  ? <>Read <span className="font-medium">{patch.n_reviews ?? 0}</span> reviews with usable feedback using <code className="font-mono">{patch.model}</code>.</>
                  : <>Compared <span className="font-medium">{patch.n_good ?? 0}</span> good clips vs <span className="font-medium">{patch.n_bad ?? 0}</span> bad clips using <code className="font-mono">{patch.model}</code>.</>}
                {patch.rationale && (
                  <div className="mt-1 italic text-muted-foreground">"{patch.rationale}"</div>
                )}
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <PatchColumn
                  tone="add"
                  icon={Plus}
                  title="Add to profile"
                  bucket={patch.add}
                  selected={selectedAdd}
                  onToggle={toggleAdd}
                />
                <PatchColumn
                  tone="remove"
                  icon={Minus}
                  title="Remove from profile"
                  bucket={patch.remove}
                  selected={selectedRemove}
                  onToggle={toggleRemove}
                />
              </div>

              {source === "reviews" && (
                <div className="mt-5 space-y-3">
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
                    Persistent profile notes — these are saved to <code className="font-mono">data/clip_memory.md</code> so the next tuner can reuse them
                  </div>

                  {(patch.context_rules?.length ?? 0) > 0 && (
                    <SimpleSection
                      icon={BookText}
                      title="Context rules"
                      tone="primary"
                      values={patch.context_rules ?? []}
                      selected={selectedRules}
                      onToggle={(v) => toggleSimple(selectedRules, v, setSelectedRules)}
                    />
                  )}

                  {patch.slang_glossary && Object.keys(patch.slang_glossary).length > 0 && (
                    <SimpleSection
                      icon={BookText}
                      title="Slang glossary (word → meaning)"
                      tone="primary"
                      values={Object.keys(patch.slang_glossary)}
                      formatLabel={(word) => `${word} — ${patch.slang_glossary?.[word] ?? ""}`}
                      selected={selectedSlang}
                      onToggle={(v) => toggleSimple(selectedSlang, v, setSelectedSlang)}
                    />
                  )}

                  {(patch.avoid_patterns?.length ?? 0) > 0 && (
                    <SimpleSection
                      icon={ShieldAlert}
                      title="Patterns to avoid"
                      tone="destructive"
                      values={patch.avoid_patterns ?? []}
                      selected={selectedAvoid}
                      onToggle={(v) => toggleSimple(selectedAvoid, v, setSelectedAvoid)}
                    />
                  )}
                </div>
              )}

              {totalAdd + totalRem + totalMemory === 0 && (
                <div className="mt-4 text-sm italic text-muted-foreground text-center">
                  Nothing selected. Tick at least one suggestion to enable Apply.
                </div>
              )}
            </>
          )}
        </div>

        <footer className="flex items-center justify-between gap-3 border-t border-border/40 px-5 py-3 bg-background/45">
          <div className="text-xs text-muted-foreground">
            {patch
              ? `${totalAdd} adds · ${totalRem} removes${source === "reviews" ? ` · ${totalMemory} memory` : ""} selected`
              : ""}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="px-3 py-1.5 rounded-md text-sm border border-border/60 text-muted-foreground hover:text-foreground hover:bg-accent"
            >
              Discard
            </button>
            <button
              disabled={!patch || applying || (totalAdd + totalRem + totalMemory) === 0}
              onClick={applySelected}
              className={cn(
                "px-3 py-1.5 rounded-md text-sm font-medium flex items-center gap-1.5",
                "bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50",
              )}
            >
              {applying
                ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                : <Check className="h-3.5 w-3.5" />}
              Apply selected
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}

interface PatchColumnProps {
  tone: "add" | "remove";
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  bucket: Record<string, string[]>;
  selected: Record<string, Set<string>>;
  onToggle: (key: string, value: string) => void;
}

function PatchColumn({ tone, icon: Icon, title, bucket, selected, onToggle }: PatchColumnProps) {
  const keys = Object.keys(bucket).filter((k) => (bucket[k] ?? []).length > 0);

  return (
    <div className={cn(
      "rounded-lg border p-3",
      tone === "add" ? "border-success/30 bg-success/5" : "border-destructive/30 bg-destructive/5",
    )}>
      <div className={cn(
        "flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.1em] mb-3",
        tone === "add" ? "text-success" : "text-destructive",
      )}>
        <Icon className="h-3 w-3" />
        {title}
      </div>

      {keys.length === 0 && (
        <div className="text-xs italic text-muted-foreground">
          (No suggestions in this direction.)
        </div>
      )}

      <div className="space-y-3">
        {keys.map((k) => (
          <div key={k}>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
              {k}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {bucket[k].map((v) => {
                const checked = selected[k]?.has(v) ?? false;
                return (
                  <label
                    key={v}
                    className={cn(
                      "inline-flex items-center gap-1.5 px-2 py-1 rounded border cursor-pointer text-[11px]",
                      checked
                        ? tone === "add"
                          ? "border-success/60 bg-success/15 text-success"
                          : "border-destructive/60 bg-destructive/15 text-destructive"
                        : "border-border/60 bg-background/40 text-foreground/70 hover:bg-accent",
                    )}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => onToggle(k, v)}
                      className="h-3 w-3 accent-primary"
                    />
                    {tone === "add" ? "+" : "−"} {v}
                  </label>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

interface SimpleSectionProps {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  tone: "primary" | "destructive";
  values: string[];
  selected: Set<string>;
  formatLabel?: (value: string) => string;
  onToggle: (value: string) => void;
}

function SimpleSection({ icon: Icon, title, tone, values, selected, formatLabel, onToggle }: SimpleSectionProps) {
  if (values.length === 0) return null;
  const borderCls = tone === "destructive" ? "border-destructive/30 bg-destructive/5" : "border-primary/30 bg-primary/5";
  const titleCls  = tone === "destructive" ? "text-destructive" : "text-primary";
  const onCls     = tone === "destructive"
    ? "border-destructive/60 bg-destructive/15 text-destructive"
    : "border-primary/60 bg-primary/15 text-primary";
  return (
    <div className={cn("rounded-lg border p-3", borderCls)}>
      <div className={cn(
        "flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.1em] mb-2",
        titleCls,
      )}>
        <Icon className="h-3 w-3" />
        {title}
      </div>
      <div className="flex flex-col gap-1.5">
        {values.map((v) => {
          const checked = selected.has(v);
          const label = formatLabel ? formatLabel(v) : v;
          return (
            <label
              key={v}
              className={cn(
                "inline-flex items-start gap-2 px-2 py-1.5 rounded border cursor-pointer text-[11px]",
                checked ? onCls : "border-border/60 bg-background/40 text-foreground/80 hover:bg-accent",
              )}
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={() => onToggle(v)}
                className="h-3 w-3 mt-0.5 accent-primary shrink-0"
              />
              <span className="leading-snug">{label}</span>
            </label>
          );
        })}
      </div>
    </div>
  );
}
