import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BookOpenText,
  Download,
  FileUp,
  Languages,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";

import { api, type LanguagePack, type LanguageTerm } from "@/api/client";
import { cn } from "@/lib/utils";
import { PageBody, PageHeader } from "./_shared";

type ImportMode = "merge" | "replace";

const sourceLabel: Record<string, string> = {
  manual: "You added",
  derived_reviews: "From reviews",
  imported: "Imported",
};

function downloadJson(name: string, payload: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  URL.revokeObjectURL(url);
}

function parsePack(value: unknown): LanguagePack {
  if (!value || typeof value !== "object") throw new Error("This file is not a language pack.");
  const pack = value as Partial<LanguagePack>;
  if (pack.kind !== "lek_language_pack" || !Array.isArray(pack.terms)) {
    throw new Error("Expected a language pack with a terms list.");
  }
  return pack as LanguagePack;
}

export function LanguageStudioPage() {
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [search, setSearch] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [importMode, setImportMode] = useState<ImportMode>("merge");
  const [replaceConfirmed, setReplaceConfirmed] = useState(false);
  const [draft, setDraft] = useState({ term: "", meaning: "", lang: "", aliases: "" });

  const termsQuery = useQuery({ queryKey: ["language-terms"], queryFn: api.language.terms });
  const hotwordsQuery = useQuery({ queryKey: ["language-hotwords"], queryFn: api.language.hotwords });
  const terms = termsQuery.data?.terms ?? [];
  const hotwords = hotwordsQuery.data?.hotwords ?? [];

  const refresh = async () => {
    setNotice(null);
    await Promise.all([termsQuery.refetch(), hotwordsQuery.refetch()]);
  };

  const refreshLanguage = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["language-terms"] }),
      queryClient.invalidateQueries({ queryKey: ["language-hotwords"] }),
    ]);
  };

  const addTerm = useMutation({
    mutationFn: api.language.add,
    onSuccess: async () => {
      await refreshLanguage();
      setDraft({ term: "", meaning: "", lang: "", aliases: "" });
      setNotice("Language term saved. New transcriptions and AI judgements can use it.");
    },
    onError: (error: Error) => setNotice(`Could not save the term: ${error.message}`),
  });

  const removeTerm = useMutation({
    mutationFn: api.language.remove,
    onSuccess: async () => {
      await refreshLanguage();
      setNotice("Term removed from your language pack.");
    },
    onError: (error: Error) => setNotice(`Could not remove the term: ${error.message}`),
  });

  const seedTerms = useMutation({
    mutationFn: api.language.seedFromReviews,
    onSuccess: async (result) => {
      await refreshLanguage();
      setNotice(`Reviewed your notes: ${result.added} terms found, ${result.total} total. Check derived terms before keeping them.`);
    },
    onError: (error: Error) => setNotice(`Could not learn from reviews: ${error.message}`),
  });

  const exportPack = async () => {
    try {
      const pack = await api.language.exportPack();
      downloadJson(`instaclip-language-${new Date().toISOString().slice(0, 10)}.json`, pack);
      setNotice("Language pack exported without clips, credentials, or private memory.");
    } catch (error) {
      setNotice(`Could not export the pack: ${error instanceof Error ? error.message : String(error)}`);
    }
  };

  const importFile = async (file: File) => {
    try {
      const pack = parsePack(JSON.parse(await file.text()));
      const result = await api.language.importPack(pack, importMode);
      await refreshLanguage();
      setNotice(`Imported ${result.imported} terms (${result.total} total) using ${result.mode} mode.`);
    } catch (error) {
      setNotice(`Could not import the pack: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const normalizedSearch = search.trim().toLowerCase();
  const filtered = normalizedSearch
    ? terms.filter((item) => [item.term, item.meaning, item.lang, ...(item.aliases ?? [])]
      .some((value) => value.toLowerCase().includes(normalizedSearch)))
    : terms;
  const languages = new Set(terms.map((item) => item.lang.trim()).filter(Boolean)).size;

  const submitTerm = () => {
    const term = draft.term.trim();
    const meaning = draft.meaning.trim();
    if (!term || !meaning) return;
    addTerm.mutate({
      term,
      meaning,
      lang: draft.lang.trim(),
      aliases: draft.aliases.split(",").map((item) => item.trim()).filter(Boolean),
    });
  };

  return (
    <>
      <PageHeader
        title="Language & Learning Studio"
        subtitle="Teach InstaClip your slang, names, languages, and pronunciation so transcripts and clip judgements understand your community."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" onClick={() => void refresh()} disabled={termsQuery.isFetching} className="language-action">
              <RefreshCw className={cn("h-3.5 w-3.5", termsQuery.isFetching && "animate-spin")} /> Refresh
            </button>
            <button type="button" onClick={() => void exportPack()} disabled={!terms.length} className="language-action">
              <Download className="h-3.5 w-3.5" /> Export
            </button>
            <button type="button" onClick={() => fileInput.current?.click()} disabled={importMode === "replace" && !replaceConfirmed} className="language-action" title={importMode === "replace" && !replaceConfirmed ? "Confirm replace mode below first" : undefined}>
              <FileUp className="h-3.5 w-3.5" /> Import
            </button>
            <input ref={fileInput} type="file" accept="application/json,.json,.lekprofile" className="hidden" onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void importFile(file);
            }} />
          </div>
        }
      />

      <PageBody>
        <section className="premium-card relative overflow-hidden rounded-2xl border border-cyan-300/20 surface-1 p-5">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_8%_0%,rgba(34,211,238,.15),transparent_38%),radial-gradient(circle_at_92%_100%,rgba(249,115,22,.1),transparent_35%)]" />
          <div className="relative grid gap-5 lg:grid-cols-[1fr_auto] lg:items-center">
            <div>
              <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.18em] text-cyan-200/80">
                <Languages className="h-4 w-4" /> Your words, your meaning
              </div>
              <h2 className="mt-2 text-xl font-semibold tracking-tight">Stop generic AI from guessing what you meant.</h2>
              <p className="mt-2 max-w-2xl text-xs leading-5 text-muted-foreground">
                This pack stays local. Terms bias transcription and give the Director the correct meaning when it judges a clip. Derived review terms stay visible so you can remove noisy guesses.
              </p>
            </div>
            <div className="grid grid-cols-3 gap-2 text-center">
              <Metric label="Terms" value={String(terms.length)} />
              <Metric label="Languages" value={String(languages)} />
              <Metric label="Hotwords" value={String(hotwords.length)} />
            </div>
          </div>
        </section>

        {notice && (
          <div className="flex items-center justify-between gap-3 rounded-lg border border-primary/25 bg-primary/[0.07] px-4 py-3 text-xs text-primary">
            <span>{notice}</span>
            <button type="button" onClick={() => setNotice(null)} aria-label="Dismiss"><X className="h-3.5 w-3.5" /></button>
          </div>
        )}

        <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
          <div className="space-y-3">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold">Language pack</h3>
                <p className="mt-1 text-xs text-muted-foreground">Search meanings and aliases, then remove anything the review learner misunderstood.</p>
              </div>
              <label className="relative block min-w-56">
                <Search className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
                <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search terms or meanings" className="premium-control w-full rounded-md border border-border/55 py-2 pl-8 pr-3 text-xs" />
              </label>
            </div>

            {termsQuery.isLoading && <div className="grid h-32 place-items-center"><Loader2 className="h-5 w-5 animate-spin text-primary" /></div>}
            {termsQuery.isError && <div className="rounded-xl border border-destructive/35 bg-destructive/[0.08] p-4 text-xs text-destructive">Could not load the language pack: {termsQuery.error.message}</div>}
            {!termsQuery.isLoading && !filtered.length && (
              <div className="rounded-xl border border-dashed border-border/60 p-8 text-center text-xs text-muted-foreground">
                {terms.length ? "No terms match this search." : "No terms yet. Add one or learn definitions from your clip reviews."}
              </div>
            )}
            <div className="space-y-2">
              {filtered.map((item) => <TermCard key={item.term} item={item} removing={removeTerm.isPending} onRemove={() => removeTerm.mutate(item.term)} />)}
            </div>
          </div>

          <aside className="space-y-4">
            <section className="premium-card rounded-xl border border-border/50 surface-1 p-4">
              <div className="flex items-center gap-2"><Plus className="h-4 w-4 text-primary" /><h3 className="text-sm font-semibold">Teach a term</h3></div>
              <div className="mt-4 space-y-2">
                <input value={draft.term} onChange={(event) => setDraft((value) => ({ ...value, term: event.target.value }))} placeholder="Term or name" className="language-input" />
                <textarea value={draft.meaning} onChange={(event) => setDraft((value) => ({ ...value, meaning: event.target.value }))} placeholder="What it means in your community" className="language-input min-h-24 resize-y" />
                <div className="grid grid-cols-2 gap-2">
                  <input value={draft.lang} onChange={(event) => setDraft((value) => ({ ...value, lang: event.target.value }))} placeholder="Language" className="language-input" />
                  <input value={draft.aliases} onChange={(event) => setDraft((value) => ({ ...value, aliases: event.target.value }))} placeholder="Aliases, comma separated" className="language-input" />
                </div>
                <button type="button" onClick={submitTerm} disabled={!draft.term.trim() || !draft.meaning.trim() || addTerm.isPending} className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground disabled:opacity-45">
                  {addTerm.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />} Save term
                </button>
              </div>
            </section>

            <section className="premium-card rounded-xl border border-amber-300/20 bg-amber-300/[0.04] p-4">
              <div className="flex items-center gap-2 text-amber-100"><Sparkles className="h-4 w-4" /><h3 className="text-sm font-semibold">Learn from reviews</h3></div>
              <p className="mt-2 text-xs leading-5 text-muted-foreground">Looks for definitions you already wrote, such as “tsek means go away.” It does not upload clips.</p>
              <button type="button" onClick={() => seedTerms.mutate()} disabled={seedTerms.isPending} className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-md border border-amber-300/30 px-3 py-2 text-xs font-semibold text-amber-100 hover:bg-amber-300/[0.08] disabled:opacity-45">
                {seedTerms.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <BookOpenText className="h-3.5 w-3.5" />} Scan my review notes
              </button>
            </section>

            <section className="premium-card rounded-xl border border-border/50 surface-1 p-4">
              <h3 className="text-sm font-semibold">Import behavior</h3>
              <p className="mt-1 text-[11px] leading-4 text-muted-foreground">Merge preserves your terms. Replace clears this language pack before importing.</p>
              <div className="mt-3 grid grid-cols-2 gap-2">
                {(["merge", "replace"] as ImportMode[]).map((mode) => (
                  <button key={mode} type="button" onClick={() => { setImportMode(mode); setReplaceConfirmed(false); }} className={cn("rounded-md border px-3 py-2 text-xs capitalize", importMode === mode ? "border-primary/50 bg-primary/[0.09] text-primary" : "border-border/50 text-muted-foreground")}>{mode}</button>
                ))}
              </div>
              {importMode === "replace" && (
                <label className="mt-3 flex cursor-pointer items-start gap-2 rounded-md border border-destructive/25 bg-destructive/[0.05] p-2.5 text-[10px] leading-4 text-muted-foreground">
                  <input type="checkbox" checked={replaceConfirmed} onChange={(event) => setReplaceConfirmed(event.target.checked)} className="mt-0.5 h-3.5 w-3.5 accent-destructive" />
                  <span>I understand that importing will remove every term currently in this language pack.</span>
                </label>
              )}
            </section>

            <section className="premium-card rounded-xl border border-border/50 surface-1 p-4">
              <h3 className="text-sm font-semibold">Active hotwords</h3>
              <p className="mt-1 text-[11px] leading-4 text-muted-foreground">Terms and aliases sent to the transcription bias.</p>
              <div className="mt-3 flex max-h-32 flex-wrap gap-1.5 overflow-y-auto">
                {hotwords.slice(0, 80).map((word) => <span key={word} className="rounded-full border border-cyan-300/20 bg-cyan-300/[0.06] px-2 py-1 text-[9px] text-cyan-100">{word}</span>)}
                {!hotwords.length && <span className="text-[10px] italic text-muted-foreground">No hotwords yet.</span>}
              </div>
            </section>
          </aside>
        </section>
      </PageBody>
    </>
  );
}

function TermCard({ item, removing, onRemove }: { item: LanguageTerm; removing: boolean; onRemove: () => void }) {
  const confidence = Math.round(Math.max(0, Math.min(1, item.confidence)) * 100);
  return (
    <article className="premium-card rounded-xl border border-border/45 surface-1 p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-sm font-semibold">{item.term}</h4>
            {item.lang && <span className="rounded-full border border-sky-300/20 bg-sky-300/[0.06] px-2 py-0.5 text-[9px] uppercase tracking-wide text-sky-200">{item.lang}</span>}
            <span className={cn("rounded-full border px-2 py-0.5 text-[9px]", item.source === "manual" ? "border-emerald-300/25 bg-emerald-300/[0.07] text-emerald-200" : "border-amber-300/25 bg-amber-300/[0.07] text-amber-200")}>{sourceLabel[item.source] ?? item.source}</span>
          </div>
          <p className="mt-2 text-xs leading-5 text-muted-foreground">{item.meaning}</p>
          {!!item.aliases?.length && <div className="mt-2 text-[10px] text-muted-foreground">Also heard as: <span className="text-foreground">{item.aliases.join(", ")}</span></div>}
        </div>
        <button type="button" onClick={onRemove} disabled={removing} className="rounded-md border border-destructive/25 p-2 text-destructive/75 hover:bg-destructive/[0.08] hover:text-destructive disabled:opacity-40" aria-label={`Remove ${item.term}`}><Trash2 className="h-3.5 w-3.5" /></button>
      </div>
      <div className="mt-3 flex items-center gap-2">
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-secondary"><div className="h-full rounded-full bg-gradient-to-r from-cyan-400 to-emerald-300" style={{ width: `${confidence}%` }} /></div>
        <span className="text-[9px] tabular-nums text-muted-foreground">{confidence}% confidence</span>
      </div>
    </article>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="min-w-20 rounded-xl border border-white/10 bg-black/20 px-3 py-3"><div className="text-lg font-semibold tabular-nums">{value}</div><div className="mt-1 text-[9px] uppercase tracking-wide text-muted-foreground">{label}</div></div>;
}
