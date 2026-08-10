import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Brain, NotebookPen, Plus, RefreshCw, Sparkles, Wand2 } from "lucide-react";

import { api } from "@/api/client";
import { Chip } from "@/components/Chip";
import { ProfileTunerModal } from "@/components/ProfileTunerModal";
import { cn } from "@/lib/utils";
import { PageHeader, PageBody } from "./_shared";

interface CategoryMeta { label: string; desc: string; key_field?: string }

type TunerSource = "compare" | "reviews";

export function ProfilePage() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["profile"],
    queryFn:  api.profile.get,
  });

  const addMutation = useMutation({
    mutationFn: ({ key, value }: { key: string; value: any }) => api.profile.add(key, value),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["profile"] }),
  });
  const removeMutation = useMutation({
    mutationFn: ({ key, value }: { key: string; value: any }) => api.profile.remove(key, value),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["profile"] }),
  });

  const [tunerJobId, setTunerJobId] = useState<string | null>(null);
  const [tunerSource, setTunerSource] = useState<TunerSource>("compare");
  const [tuning, setTuning] = useState<TunerSource | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function startTuner(source: TunerSource) {
    setError(null);
    setTuning(source);
    setTunerSource(source);
    try {
      const { job_id } = source === "reviews"
        ? await api.profile.suggestFromReviews()
        : await api.profile.suggest();
      setTunerJobId(job_id);
    } catch (e: any) {
      setError(e.message ?? "Tuner failed to start");
    } finally {
      setTuning(null);
    }
  }

  const profile = data?.profile ?? {};
  const schema = data?.schema as {
    lists:      Record<string, CategoryMeta>;
    dict_lists: Record<string, CategoryMeta>;
  } | undefined;

  return (
    <>
      <PageHeader
        title="Profile Tuner"
        subtitle="Edit the rule-based profile by hand, or let the local LLM suggest changes — either by comparing your good vs bad clips, or by reading what you wrote in your review notes."
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={() => {
              qc.invalidateQueries({ queryKey: ["profile"] });
            }}
              className="text-xs px-3 py-1.5 rounded border border-border/60 text-muted-foreground hover:text-foreground hover:bg-accent flex items-center gap-1"
            >
              <RefreshCw className="h-3 w-3" /> Reload
            </button>
            <button
              onClick={() => startTuner("compare")}
              disabled={tuning !== null}
              className="text-xs px-3 py-1.5 rounded border border-border/60 text-foreground hover:bg-accent disabled:opacity-50 flex items-center gap-1"
              title="Compare good vs bad clip transcripts and suggest profile edits"
            >
              <Sparkles className="h-3 w-3" />
              {tuning === "compare" ? "Asking LLM…" : "Compare good vs bad"}
            </button>
            <button
              onClick={() => startTuner("reviews")}
              disabled={tuning !== null}
              className="text-xs px-3 py-1.5 rounded bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 flex items-center gap-1"
              title="Read your review notes and extract slang, rules, and patterns to fix"
            >
              <NotebookPen className="h-3 w-3" />
              {tuning === "reviews" ? "Reading reviews…" : "Tune from review notes"}
            </button>
          </div>
        }
      />
      <PageBody>
        {isLoading && <div className="text-sm text-muted-foreground">Loading profile…</div>}
        {error && <div className="text-sm text-destructive">{error}</div>}

        {!isLoading && Object.keys(profile).length === 0 && (
          <div className="premium-card rounded-lg border border-border/50 p-6 text-sm text-muted-foreground italic surface-1">
            No profile yet. Run profile-rebuild from the Classifier page.
          </div>
        )}

        {!isLoading && schema && (
          <>
            <ProfileStats profile={profile} />

            {Object.entries(schema.lists).map(([k, meta]) => (
              <CategorySection
                key={k}
                category={k}
                meta={meta}
                values={(profile[k] ?? []) as string[]}
                isDictList={false}
                onAdd={(value) => addMutation.mutate({ key: k, value })}
                onRemove={(value) => removeMutation.mutate({ key: k, value })}
              />
            ))}

            {Object.entries(schema.dict_lists).map(([k, meta]) => (
              <CategorySection
                key={k}
                category={k}
                meta={meta}
                values={(profile[k] ?? []) as Array<string | { phrase?: string; pattern?: string; score?: number }>}
                isDictList={true}
                onAdd={(value) => addMutation.mutate({ key: k, value })}
                onRemove={(value) => removeMutation.mutate({ key: k, value })}
              />
            ))}
          </>
        )}
      </PageBody>

      {tunerJobId && (
        <ProfileTunerModal
          jobId={tunerJobId}
          source={tunerSource}
          onClose={() => {
            setTunerJobId(null);
          }}
        />
      )}
    </>
  );
}

function ProfileStats({ profile }: { profile: any }) {
  return (
    <div className="premium-card rounded-lg border border-border/50 surface-1 px-4 py-3 text-xs text-muted-foreground">
      Built from <span className="text-foreground font-medium">{profile.clips_analyzed ?? "?"}</span> good clips
      &nbsp;and <span className="text-foreground font-medium">{profile.bad_clips_used ?? "?"}</span> bad clips
      &nbsp;· avg clip duration <span className="text-foreground font-medium">{Math.round(profile.avg_clip_duration ?? 0)}s</span>
    </div>
  );
}

interface CategorySectionProps {
  category: string;
  meta:     CategoryMeta;
  values:   any[];
  isDictList: boolean;
  onAdd:    (value: any) => void;
  onRemove: (value: any) => void;
}

function CategorySection({ category, meta, values, isDictList, onAdd, onRemove }: CategorySectionProps) {
  const [draft, setDraft] = useState("");
  const kf = meta.key_field ?? "phrase";

  function commit() {
    const v = draft.trim().toLowerCase();
    if (!v) return;
    onAdd(isDictList ? { [kf]: v, score: 0.5 } : v);
    setDraft("");
  }

  return (
    <section className="premium-card rounded-lg border border-border/50 surface-1 p-4">
      <div className="flex items-end justify-between gap-3 mb-1">
        <h3 className="text-sm font-semibold">{meta.label}</h3>
        <span className="text-[11px] text-muted-foreground">
          {values.length} entries
        </span>
      </div>
      <p className="text-xs text-muted-foreground mb-3">{meta.desc}</p>

      <div className="flex flex-wrap gap-1.5 mb-3 max-h-44 overflow-y-auto pr-1">
        {values.length === 0 && (
          <span className="text-xs italic text-muted-foreground">(empty)</span>
        )}
        {values.map((v: any, i: number) => {
          const label = isDictList ? (v?.[kf] ?? String(v)) : String(v);
          return (
            <Chip
              key={`${label}-${i}`}
              label={label}
              onRemove={() => onRemove(isDictList ? v : label)}
              title={isDictList && typeof v === "object" && v?.score != null
                       ? `${label} (score ${v.score})`
                       : label}
            />
          );
        })}
      </div>

      <div className="flex items-center gap-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") commit(); }}
          placeholder={isDictList ? "Add phrase…" : "Add word…"}
          className={cn(
            "flex-1 bg-secondary/60 px-2 py-1.5 rounded text-xs",
            "outline-none focus:ring-1 focus:ring-primary placeholder:text-muted-foreground",
          )}
        />
        <button
          onClick={commit}
          disabled={!draft.trim()}
          className="text-xs px-3 py-1.5 rounded bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-40 flex items-center gap-1"
        >
          <Plus className="h-3 w-3" /> Add
        </button>
      </div>
    </section>
  );
}
