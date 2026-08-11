/**
 * Thin typed HTTP/WS client over the FastAPI backend.
 *
 * Dev (browser):  /api proxied by Vite to http://127.0.0.1:8765
 * Dev (Tauri):    absolute http://127.0.0.1:8765 (no Vite proxy in the Tauri webview)
 * Prod (exe):     absolute http://127.0.0.1:8765 — Tauri spawns the sidecar there
 *
 * Override with VITE_BACKEND_URL when running against a remote backend.
 */

import type { EditorAsset, EditorProjectV2, YouTubeBrandKit } from "@/editor-v2/model";

function resolveBackendBase(): string {
  const override = (import.meta.env.VITE_BACKEND_URL as string | undefined)?.replace(/\/$/, "");
  if (override) return override;
  if (typeof window !== "undefined" && "__TAURI_INTERNALS__" in window) {
    return "http://127.0.0.1:8765";
  }
  return "/api";
}

const HTTP_BASE = resolveBackendBase();

// For WebSockets we always need an absolute URL.
const wsBase = () => {
  if (HTTP_BASE.startsWith("http")) {
    return HTTP_BASE.replace(/^http/, "ws");
  }
  // /api proxy → derive from current location.
  const loc = window.location;
  const proto = loc.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${loc.host}/api`;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(HTTP_BASE + path, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    let body: any = undefined;
    try { body = await res.json(); } catch {}
    throw new ApiError(res.status, body?.detail, body);
  }
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get("content-type") ?? "";
  return (ct.includes("application/json") ? res.json() : (res.blob() as any));
}

/**
 * Turn a FastAPI error detail (which can be a string OR a structured dict)
 * into a human-readable one-liner. The full structured body is still on
 * .detail for callers who want to render it richly.
 */
function summariseDetail(detail: unknown, status: number): string {
  if (!detail) return `Request failed (${status})`;
  if (typeof detail === "string") return detail;
  if (typeof detail === "object") {
    const d = detail as Record<string, any>;
    // The "file_not_found" shape we explicitly return from /pipeline/run:
    if (d.error === "file_not_found") {
      const tried = d.tried_path ?? d.received_raw ?? "<unknown>";
      const parent = d.parent_exists
        ? "parent dir exists"
        : "parent dir does NOT exist";
      return `File not found: ${tried}  (${parent})`;
    }
    // Pydantic validation errors come as arrays.
    if (Array.isArray(d)) {
      return d.map((e: any) => e?.msg ?? JSON.stringify(e)).join("; ");
    }
    if (typeof d.message === "string") return d.message;
    if (typeof d.error === "string") return d.error;
    return JSON.stringify(d);
  }
  return String(detail);
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  body: unknown;
  constructor(status: number, detail: unknown, body: unknown) {
    super(summariseDetail(detail, status));
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.body = body;
  }
}

async function uploadRequest<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(HTTP_BASE + path, { method: "POST", body: form });
  if (!res.ok) {
    let body: any = undefined;
    try { body = await res.json(); } catch {}
    throw new ApiError(res.status, body?.detail, body);
  }
  return res.json() as Promise<T>;
}

// ---- Types matching backend/schemas.py + route responses --------------------

export type Bucket = "output" | "positives" | "negatives" | "edited";

export interface EditorMediaAsset {
  id: string;
  name: string;
  kind: "image" | "video";
  duration: number;
  width: number;
  height: number;
  has_audio: boolean;
  size_mb: number;
}

export interface CompilationItem {
  source_type: "clip" | "media";
  bucket?: Bucket;
  stem?: string;
  media_id?: string;
  spec: unknown;
  automatic?: boolean;
  still_duration?: number;
}

export interface EditorPreset {
  id: string;
  label: string;
  layout: "reaction" | "crop" | "fullcam" | "passthrough";
  cam_box?: [number, number, number, number];
  content_box?: [number, number, number, number];
  crop_box?: [number, number, number, number];
  audio_normalize: boolean;
  audio_boost_db: number;
}

export interface TrimSuggestion {
  stem: string;
  start: number;
  end: number;
  reason: string;
  confidence: number;
  method: "gemini_video" | "full_clip";
}

export interface EditorV2ProjectSummary {
  id: string;
  name: string;
  revision: number;
  updatedAt: number;
  duration: number;
  contentMode: "short_form" | "long_form";
  strategy?: "full_vod" | "rough_cut";
  chapterCount?: number;
  storyBeatCount?: number;
  captionCount?: number;
}

export interface EditorV2RenderResult {
  ok: boolean;
  stem: string;
  bucket: "edited";
  path: string;
  duration: number;
  renderedAt: number;
}

export interface LanguageTerm {
  term: string;
  meaning: string;
  lang: string;
  aliases: string[];
  source: "manual" | "derived_reviews" | "imported" | string;
  confidence: number;
}

export interface LanguagePack {
  kind: "lek_language_pack";
  version: number;
  terms: LanguageTerm[];
}

export interface ClipInfo {
  stem: string;
  name: string;
  bucket: Bucket;
  size_mb: number;
  duration_seconds?: number | null;
  mtime: number;
  score?: number | null;
  quality_score?: number | null;
  speaker?: string | null;
  has_thumbnail: boolean;
  group: string;
  source_vod?: string | null;
  triggers: string[];
  hazard_flags: string[];
  tags: string[];
}

export interface ClipGroup {
  id: string;
  label: string;
  count: number;
  micro_count: number;
  reviewed_count: number;
  total_size_mb: number;
  avg_duration: number | null;
  best_score: number | null;
  newest: number;
}

export interface ClipListOptions {
  limit?: number;
  group?: string;
  search?: string;
  minDuration?: number;
  maxDuration?: number;
  minScore?: number;
  tag?: string;
  sortBy?: "newest" | "oldest" | "duration" | "score" | "size" | "name";
  order?: "asc" | "desc";
}

export interface ClipReview {
  stem: string;
  bucket: Bucket;
  rating: number | null;
  verdict: "keeper" | "maybe" | "miss" | "undecided";
  reasons: string[];
  tags: string[];
  notes: string;
  caption_notes: string;
  created_at: number;
  updated_at: number;
}

export interface ClipDetails {
  stem: string;
  bucket: Bucket;
  transcript: string | null;
  visual_caption: string | null;
  size_mb: number;
  score: number | null;
  quality_prediction: number | null;
  signals: null | {
    audio_spike?:    number;
    explosion?:      number;
    repetition?:     number;
    profile_match?:  number;
    face_reaction?:  number;
    keyword_spike?:  number;
    state_change?:   number;
    aftermath?:      number;
    semantic_boost?: number;
    audio_energy?:   number;
    score?:          number;
    quality_score?:  number | null;
    final_score?:    number;
    clip_type?:      string;
  };
  triggers:  string[];
  peak_text: string | null;
  hazard_flags: string[];
  review: ClipReview | null;
}

export type TranscriptEditOperation =
  | { type: "cut_ranges"; ranges: Array<{ start: number; end: number }> }
  | { type: "remove_silences"; min_gap?: number; pad?: number; noise_db?: number }
  | { type: "remove_fillers"; words?: string[]; pad?: number };

export type TranscriptEditReport = {
  ops: Array<Record<string, unknown>>;
  removed_seconds: number;
  items_split: number;
  skipped_items: string[];
  cut_ranges_applied: Array<[number, number]>;
};

export type EditorSourceTranscript = {
  stem: string;
  version: number | string;
  has_words: boolean;
  segments: Array<{
    text: string;
    start: number;
    end: number;
    words: Array<{ text: string; start: number; end: number }>;
  }>;
};

export type YouTubeEpisodeProposal = {
  index: number;
  part_group: string | number | null;
  part: number;
  parts_total: number;
  title_hint: string;
  start: number;
  end: number;
  duration: number;
  blocks: Array<Record<string, unknown>>;
  standalone: boolean;
  top_moments: Array<{
    stem: string;
    score: number;
    reason: string;
    start: number;
    end: number;
    state: string;
  }>;
};

export type YouTubeEpisodePlan = {
  vod: string;
  contract: Record<string, unknown>;
  episode_count: number;
  moment_candidates_total: number;
  episodes: YouTubeEpisodeProposal[];
};

export type LayoutScanResult = {
  segments: Array<{ start: number; end: number; layout: "fullcam" | "smallcam" | "noface" | "unknown" }>;
  switches: number[];
  has_layout_switch: boolean;
};

export interface JobInfo {
  id: string;
  kind: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  progress: Record<string, any>;
  result: Record<string, any> | null;
  error: string | null;
  started_at: number;
  finished_at: number;
  cancel_requested?: boolean;
}

export type ClipRoomState =
  | "DETECTED"
  | "CANDIDATE"
  | "SENT_TO_DISCORD"
  | "CLAIMED"
  | "RAW_REQUESTED"
  | "EDIT_REQUESTED"
  | "RENDERING"
  | "READY_FOR_REVIEW"
  | "REVISION_REQUESTED"
  | "APPROVED"
  | "SCHEDULED"
  | "PUBLISHED"
  | "MEASURED"
  | "LEARNING_COMPLETE"
  | "REJECTED";

export interface ClipRoomCandidate {
  id: string;
  stem: string;
  state: ClipRoomState;
  score: number | null;
  start: number | null;
  end: number | null;
  reason: string | null;
  hazards: string[] | null;
  claimed_by: string | null;
  // These fields are kept for data-model compatibility with existing Clip Room
  // workflow records. They are not read or written by this public edition UI.
  discord_message_id: string | null;
  discord_thread_id: string | null;
  vod_id: string | null;
  vod_stem: string | null;
  vod_path: string | null;
  created_at: number;
  updated_at: number;
  has_render: boolean;
  tags: string[];
}

export type ClipRoomSort = "score_desc" | "newest" | "oldest" | "duration_asc" | "duration_desc" | "stream_position" | "updated";

export interface ClipRoomCandidateQuery {
  states?: ClipRoomState[];
  q?: string;
  vod_id?: string;
  min_score?: number;
  max_score?: number;
  min_duration?: number;
  max_duration?: number;
  claimed_by?: string;
  hazard?: boolean;
  render_status?: "any" | "rendered" | "unrendered";
  tag?: string;
  sort?: ClipRoomSort;
  cursor?: string;
  limit?: number;
}

export interface ClipRoomCandidatePage {
  candidates: ClipRoomCandidate[];
  total: number;
  next_cursor: string | null;
  facets: {
    states: Record<string, number>;
    vods: Array<{ id: string; stem: string }>;
    assignees: string[];
    tags: string[];
  };
}

export interface ClipRoomCard {
  candidate_id: string;
  title: string;
  stem: string;
  score: number;
  duration: number;
  start: number;
  end: number;
  hazards: string[];
  state: ClipRoomState;
}

export interface ClipRoomAuditEvent {
  actor: string;
  from: ClipRoomState;
  to: ClipRoomState;
  reason: string;
  payload: Record<string, unknown> | null;
  ts: number;
}

export interface ClipRoomStateGraph {
  transitions: Record<ClipRoomState, ClipRoomState[]>;
  terminal: ClipRoomState[];
}

export interface DirectorJudgement {
  base_score: number;
  adjustment: number;
  adjusted_score: number;
  null_like: boolean;
  notes: string[];
}

export interface DirectorTasteVerdict {
  fit: number;
  verdict: "keep" | "maybe" | "skip";
  why: string;
}

export interface TesterTasteProfile {
  version: number;
  user_id: string;
  preset: string;
  traits: string[];
  preferred_duration: number[];
  notes: string;
  examples: Array<{ path: string; label: string; reason: string }>;
  calibration_feedback: Array<Record<string, unknown>>;
  onboarding_complete: boolean;
}

export interface SystemStatus {
  vod_folder: { path: string; exists: boolean };
  ffmpeg: { on_path: boolean };
  profile: { trained: boolean };
  quality_classifier: { trained: boolean };
  ollama: { alive: boolean };
  vision: { model: string; ok: boolean; msg: string; enabled: boolean };
  face_detector: { available: boolean };
  speaker_id: {
    resemblyzer: boolean;
    speakers: string[];
    enabled: boolean;
    target: string;
  };
  twitch: { configured: boolean };
  note?: string;
  whisper: { device: string; model_size: string };
  paths: Record<string, string>;
}

export interface ClipCounts {
  positives: number;
  negatives: number;
  newly_cut: number;
}

export interface LogLine {
  ts: number;
  level: string;
  logger: string;
  message: string;
  keepalive?: boolean;
}

// ---- Endpoints --------------------------------------------------------------

export const api = {
  root: () => request<{ name: string; version: string; status: string }>("/"),

  status: {
    full:   () => request<SystemStatus>("/status"),
    counts: () => request<ClipCounts>("/status/counts"),
  },

  pipeline: {
    run:       (source: string) => request<{ job_id: string; source: string }>("/pipeline/run",   { method: "POST", body: JSON.stringify({ source }) }),
    batch:     (body: { size?: number; paths?: string[] }) =>
                                   request<{ job_id: string; queued: number }>("/pipeline/batch", { method: "POST", body: JSON.stringify(body) }),
    cancel:    (id: string)     => request<{ ok: boolean }>(`/pipeline/jobs/${id}/cancel`, { method: "POST", body: "{}" }),
    job:       (id: string)     => request<JobInfo>(`/pipeline/jobs/${id}`),
    jobs:      ()               => request<JobInfo[]>("/pipeline/jobs"),
    localVods: ()               => request<{
                                     folder: string;
                                     count:  number;
                                     vods:   Array<{ name: string; path: string; size_mb: number; mtime: number; transcribed: boolean }>;
                                   }>("/pipeline/local-vods"),
  },

  clips: {
    list:   (bucket: Bucket, options: ClipListOptions = {}) => {
      const params = new URLSearchParams({
        bucket,
        limit: String(options.limit ?? 500),
        sort_by: options.sortBy ?? "newest",
        order: options.order ?? "desc",
      });
      if (options.group && options.group !== "all") params.set("group", options.group);
      if (options.search) params.set("search", options.search);
      if (options.minDuration !== undefined) params.set("min_duration", String(options.minDuration));
      if (options.maxDuration !== undefined) params.set("max_duration", String(options.maxDuration));
      if (options.minScore !== undefined) params.set("min_score", String(options.minScore));
      if (options.tag && options.tag !== "all") params.set("tag", options.tag);
      return request<ClipInfo[]>(`/clips?${params.toString()}`);
    },
    groups: (bucket: Bucket) =>
      request<{ bucket: Bucket; total: number; micro_total: number; groups: ClipGroup[] }>(`/clips/groups?bucket=${bucket}`),
    move:   (stem: string, from: Bucket, to: Bucket) =>
      request<{ ok: boolean; new_stem: string; keeper_path: string | null }>("/clips/move", {
        method: "POST",
        body: JSON.stringify({ stem, from_bucket: from, to_bucket: to }),
      }),
    tagTaxonomy: () =>
      request<{ taxonomy: { good: string[]; bad: string[] } }>("/clips/tags/taxonomy"),
    setTags: (bucket: Bucket, stem: string, tags: string[]) =>
      request<{ stem: string; bucket: Bucket; tags: string[] }>(
        `/clips/${bucket}/${encodeURIComponent(stem)}/tags`,
        { method: "PUT", body: JSON.stringify({ tags }) },
      ),
    importClip: (file: File, bucket: Bucket, group: string, tags: string[]) => {
      const form = new FormData();
      form.append("file", file);
      form.append("bucket", bucket);
      form.append("group", group);
      form.append("tags", tags.join(","));
      return uploadRequest<{ stem: string; name: string; bucket: Bucket; group: string; tags: string[] }>("/clips/import", form);
    },
    details: (bucket: Bucket, stem: string) =>
      request<ClipDetails>(`/clips/${bucket}/${stem}/details`),
    thumbUrl: (bucket: Bucket, stem: string) =>
      `${HTTP_BASE}/clips/${bucket}/${encodeURIComponent(stem)}/thumbnail`,
    // Hit the backend DIRECTLY for video, bypassing the Vite dev proxy.
    videoUrl: (bucket: Bucket, stem: string) =>
      `http://127.0.0.1:8765/clips/${bucket}/${encodeURIComponent(stem)}/video.mp4`,

    // ----- Keepers (per-VOD "good clips" folder) -----------------------
    keeperGroups:   () => request<{
                      folder: string;
                      groups: Array<{
                        vod_stem: string;
                        count:    number;
                        folder:   string;
                        clips: Array<{ stem: string; name: string; size_mb: number; mtime: number; score: number | null }>;
                      }>;
                    }>("/clips/keepers/groups"),
    keeperBackfill: () => request<{ linked: number; skipped: number; unmatched: number }>(
                      "/clips/keepers/backfill", { method: "POST", body: "{}" }),
    keeperThumbUrl: (vodStem: string, stem: string) =>
      `${HTTP_BASE}/clips/keepers/${encodeURIComponent(vodStem)}/${encodeURIComponent(stem)}/thumbnail`,
    keeperVideoUrl: (vodStem: string, stem: string) =>
      `http://127.0.0.1:8765/clips/keepers/${encodeURIComponent(vodStem)}/${encodeURIComponent(stem)}/video.mp4`,
  },

  clipRoom: {
    states: () => request<ClipRoomStateGraph>("/clip-room/states"),
    candidates: (state: ClipRoomState, limit = 500) =>
      request<{ candidates: ClipRoomCandidate[] }>(
        `/clip-room/candidates?state=${encodeURIComponent(state)}&limit=${limit}`,
      ),
    queryCandidates: (query: ClipRoomCandidateQuery) => {
      const params = new URLSearchParams();
      if (query.states?.length) params.set("states", query.states.join(","));
      if (query.q) params.set("q", query.q);
      if (query.vod_id) params.set("vod_id", query.vod_id);
      if (query.min_score != null) params.set("min_score", String(query.min_score));
      if (query.max_score != null) params.set("max_score", String(query.max_score));
      if (query.min_duration != null) params.set("min_duration", String(query.min_duration));
      if (query.max_duration != null) params.set("max_duration", String(query.max_duration));
      if (query.claimed_by) params.set("claimed_by", query.claimed_by);
      if (query.hazard != null) params.set("hazard", String(query.hazard));
      if (query.render_status) params.set("render_status", query.render_status);
      if (query.tag) params.set("tag", query.tag);
      if (query.sort) params.set("sort", query.sort);
      if (query.cursor) params.set("cursor", query.cursor);
      params.set("limit", String(query.limit ?? 100));
      return request<ClipRoomCandidatePage>(`/clip-room/candidates?${params.toString()}`);
    },
    card: (candidateId: string) =>
      request<{ card: ClipRoomCard }>(`/clip-room/candidates/${encodeURIComponent(candidateId)}/card`),
    audit: (candidateId: string) =>
      request<{ audit: ClipRoomAuditEvent[] }>(`/clip-room/candidates/${encodeURIComponent(candidateId)}/audit`),
    judgement: (candidateId: string) =>
      request<{ judgement: DirectorJudgement }>(`/clip-room/candidates/${encodeURIComponent(candidateId)}/judgement`),
    verdict: (candidateId: string) =>
      request<{ verdict: DirectorTasteVerdict | null }>(`/clip-room/candidates/${encodeURIComponent(candidateId)}/verdict`),
    previewUrl: (candidateId: string) =>
      `${HTTP_BASE}/clip-room/candidates/${encodeURIComponent(candidateId)}/preview`,
    action: (
      candidateId: string,
      action: "promote" | "claim" | "request-raw" | "request-edit" | "extend-before" | "extend-after" | "different-crop" | "render" | "approve" | "request-revision" | "reject",
      body: Record<string, unknown> = { actor: "lazi" },
    ) => request<{ candidate?: ClipRoomCandidate; job_id?: string; status?: string }>(
      `/clip-room/candidates/${encodeURIComponent(candidateId)}/${action}`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  },

  tester: {
    presets: () => request<{ presets: Array<{ id: string; label: string; description: string; traits: string[]; preferred_duration: number[] }> }>("/tester/profile/presets"),
    profile: (userId: string) => request<{ profile: TesterTasteProfile }>("/tester/profile", { headers: { "X-Tester-Id": userId } }),
    save: (userId: string, body: Partial<TesterTasteProfile>) => request<{ profile: TesterTasteProfile }>("/tester/profile", { method: "PUT", headers: { "X-Tester-Id": userId }, body: JSON.stringify(body) }),
    reset: (userId: string, preset: string) => request<{ profile: TesterTasteProfile }>("/tester/profile/reset", { method: "POST", headers: { "X-Tester-Id": userId }, body: JSON.stringify({ preset }) }),
    feedback: (userId: string, body: Record<string, unknown>) => request<{ profile: TesterTasteProfile }>("/tester/profile/feedback", { method: "POST", headers: { "X-Tester-Id": userId }, body: JSON.stringify(body) }),
    preflight: () => request<{ workspace: string; workspace_writable: boolean; free_disk_gb: number; ffmpeg: string; ffprobe: string; ready: boolean; models?: { face_landmarker_present: boolean; whisper_model: string; note: string } }>("/tester/preflight"),
    supportBundleUrl: () => `${HTTP_BASE}/tester/support-bundle`,
    attachCloudSession: (body: { gateway_url: string; access_token: string; refresh_token: string; user_id: string }) => request<{ attached: boolean; user_id: string }>("/tester/cloud-session", { method: "POST", body: JSON.stringify(body) }),
    clearCloudSession: () => request<{ ok: boolean }>("/tester/cloud-session", { method: "DELETE" }),
  },

  language: {
    terms: () => request<{ terms: LanguageTerm[] }>("/language/terms"),
    add: (body: { term: string; meaning: string; lang?: string; aliases?: string[] }) =>
      request<{ term: LanguageTerm } | LanguageTerm>("/language/terms", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    remove: (term: string) => request<{ deleted: boolean }>(
      `/language/terms/${encodeURIComponent(term)}`,
      { method: "DELETE" },
    ),
    seedFromReviews: () => request<{ added: number; total: number }>(
      "/language/seed-from-reviews",
      { method: "POST", body: "{}" },
    ),
    hotwords: () => request<{ hotwords: string[] }>("/language/hotwords"),
    exportPack: () => request<LanguagePack>("/language/export"),
    importPack: (pack: LanguagePack, mode: "merge" | "replace") =>
      request<{ imported: number; total: number; mode: string }>("/language/import", {
        method: "POST",
        body: JSON.stringify({ terms: pack.terms, mode }),
      }),
  },

  edit: {
    sounds: () => request<{ sounds_dir: string; sounds: Array<{ name: string; file: string; duration: number }> }>("/edit/sounds"),
    soundUrl: (name: string) => `${HTTP_BASE}/edit/sounds/${encodeURIComponent(name)}/stream`,
    importSound: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return uploadRequest<{ ok: boolean; sound: { name: string; file: string; duration: number } }>("/edit/sounds/import", form);
    },
    media: () => request<{ media_dir: string; assets: EditorMediaAsset[] }>("/edit/media"),
    importMedia: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return uploadRequest<{ ok: boolean; asset: EditorMediaAsset }>("/edit/media/import", form);
    },
    mediaUrl: (assetId: string) => `${HTTP_BASE}/edit/media/${encodeURIComponent(assetId)}/stream`,
    mediaThumbnailUrl: (assetId: string) => `${HTTP_BASE}/edit/media/${encodeURIComponent(assetId)}/thumbnail`,
    probe:  (bucket: string, stem: string) =>
      request<{ duration: number; width: number; height: number; fps: number }>(`/edit/${bucket}/${encodeURIComponent(stem)}/probe`),
    templates: (bucket: string, stem: string) =>
      request<{ templates: Record<string, any> }>(`/edit/${bucket}/${encodeURIComponent(stem)}/templates`),
    presets: (bucket: string, stem: string) =>
      request<{ presets: EditorPreset[] }>(`/edit/${bucket}/${encodeURIComponent(stem)}/presets`),
    savePreset: (bucket: string, stem: string, name: string, spec: unknown) =>
      request<{ preset: EditorPreset }>(`/edit/${bucket}/${encodeURIComponent(stem)}/presets`, {
        method: "POST",
        body: JSON.stringify({ name, spec }),
      }),
    deletePreset: (presetId: string) =>
      request<{ ok: boolean }>(`/edit/presets/${encodeURIComponent(presetId)}`, { method: "DELETE" }),
    suggestTrim: (bucket: Bucket, stem: string) =>
      request<TrimSuggestion>("/edit/suggest-trim", {
        method: "POST",
        body: JSON.stringify({ bucket, stem }),
      }),
    renderSegments: (bucket: string, stem: string, segments: any[], output_stem?: string) =>
      request<{ ok: boolean; stem: string; bucket: string; path: string; duration: number }>(
        "/edit/render-segments", { method: "POST", body: JSON.stringify({ bucket, stem, segments, output_stem }) }),
    compile: (items: CompilationItem[], output_stem?: string, transition_sound?: string, transition_duration = 0, transition_type?: string) =>
      request<{ ok: boolean; stem: string; bucket: string; path: string; duration: number }>(
        "/edit/compile", {
          method: "POST",
          body: JSON.stringify({ items, output_stem, transition_sound, transition_duration, transition_type }),
        },
      ),
    // POST /edit/preview returns a JPEG blob — caller wraps in an object URL.
    previewBlob: (bucket: string, stem: string, spec: any, at: number) =>
      request<Blob>("/edit/preview", { method: "POST", body: JSON.stringify({ bucket, stem, spec, at }) }),
    render: (bucket: string, stem: string, spec: any) =>
      request<{ ok: boolean; stem: string; bucket: string; path: string; duration: number }>(
        "/edit/render", { method: "POST", body: JSON.stringify({ bucket, stem, spec }) }),
    auto: (bucket: string, stem: string, spec: any = {}) =>
      request<{ ok: boolean; stem: string; bucket: string; path: string }>(
        "/edit/auto", { method: "POST", body: JSON.stringify({ bucket, stem, spec }) }),
    videoUrl: (stem: string) =>
      `http://127.0.0.1:8765/clips/edited/${encodeURIComponent(stem)}/video.mp4`,
    v2: {
      brandKit: () => request<{ brand_kit: YouTubeBrandKit }>("/edit/v2/youtube-brand-kit"),
      saveBrandKit: (brandKit: YouTubeBrandKit) =>
        request<{ brand_kit: YouTubeBrandKit }>("/edit/v2/youtube-brand-kit", {
          method: "PUT",
          body: JSON.stringify(brandKit),
        }),
      projects: () => request<{ projects: EditorV2ProjectSummary[] }>("/edit/v2/projects"),
      fromClip: (bucket: Bucket, stem: string, name?: string) =>
        request<{ project: EditorProjectV2 }>("/edit/v2/projects/from-clip", {
          method: "POST",
          body: JSON.stringify({ bucket, stem, name }),
        }),
      fromLocal: (path: string, name?: string) =>
        request<{ project: EditorProjectV2 }>("/edit/v2/projects/from-local", {
          method: "POST",
          body: JSON.stringify({ path, name }),
        }),
      get: (projectId: string) =>
        request<{ project: EditorProjectV2 }>(`/edit/v2/projects/${encodeURIComponent(projectId)}`),
      transcriptOps: (projectId: string, ops: TranscriptEditOperation[], expectedRevision?: number) =>
        request<{ project: EditorProjectV2; report: TranscriptEditReport }>(
          `/edit/v2/projects/${encodeURIComponent(projectId)}/transcript-ops`,
          {
            method: "POST",
            body: JSON.stringify({ ops, expected_revision: expectedRevision }),
          },
        ),
      transcript: (projectId: string) =>
        request<EditorSourceTranscript>(`/edit/v2/projects/${encodeURIComponent(projectId)}/transcript`),
      proposeEpisodes: (body: {
        vod_stem: string;
        min_minutes?: number;
        target_minutes?: number;
        max_minutes?: number;
        gap_seconds?: number;
        layout_switches?: number[];
      }) => request<YouTubeEpisodePlan>("/edit/v2/episodes/propose", {
        method: "POST",
        body: JSON.stringify(body),
      }),
      layoutScan: (projectId: string, body: { start?: number; end?: number; threshold?: number } = {}) =>
        request<LayoutScanResult>(`/edit/v2/projects/${encodeURIComponent(projectId)}/layout-scan`, {
          method: "POST",
          body: JSON.stringify(body),
        }),
      detectCam: (projectId: string, body: { source_time?: number; aspect?: number } = {}) =>
        request<{
          found: boolean;
          detail?: string;
          identity?: string | null;
          identity_score?: number | null;
          face?: { x: number; y: number; w: number; h: number; area_ratio: number };
          cam_box?: [number, number, number, number];
          crop_box?: [number, number, number, number];
          source_size?: [number, number];
        }>(`/edit/v2/projects/${encodeURIComponent(projectId)}/detect-cam`, {
          method: "POST",
          body: JSON.stringify(body),
        }),
      extend: (projectId: string, body: { before?: number; after?: number; expected_revision?: number }) =>
        request<{ project: EditorProjectV2; report: { mode: string; granted: { before: number; after: number } } }>(
          `/edit/v2/projects/${encodeURIComponent(projectId)}/extend`,
          { method: "POST", body: JSON.stringify(body) },
        ),
      storyCut: (projectId: string, body: {
        brief: string;
        target_minutes?: number;
        max_sections?: number;
        title?: string;
        generate_captions?: boolean;
        stream_type?: string;
        goal?: string;
        required_events?: string[];
        excluded_topics?: string[];
      }) => request<{ project: EditorProjectV2; plan: NonNullable<EditorProjectV2["longformPlan"]>; source_project_id: string }>(
        `/edit/v2/projects/${encodeURIComponent(projectId)}/story-cut`,
        { method: "POST", body: JSON.stringify(body) },
      ),
      save: (project: EditorProjectV2) =>
        request<{ project: EditorProjectV2 }>(`/edit/v2/projects/${encodeURIComponent(project.id)}`, {
          method: "PUT",
          body: JSON.stringify(project),
        }),
      addClip: (projectId: string, bucket: Bucket, stem: string) =>
        request<{ asset: EditorAsset; project: EditorProjectV2 }>(
          `/edit/v2/projects/${encodeURIComponent(projectId)}/assets/clip`,
          { method: "POST", body: JSON.stringify({ bucket, stem }) },
        ),
      addMedia: (projectId: string, mediaId: string) =>
        request<{ asset: EditorAsset; project: EditorProjectV2 }>(
          `/edit/v2/projects/${encodeURIComponent(projectId)}/assets/media/${encodeURIComponent(mediaId)}`,
          { method: "POST", body: "{}" },
        ),
      addSound: (projectId: string, soundName: string) =>
        request<{ asset: EditorAsset; project: EditorProjectV2 }>(
          `/edit/v2/projects/${encodeURIComponent(projectId)}/assets/sound/${encodeURIComponent(soundName)}`,
          { method: "POST", body: "{}" },
        ),
      waveform: (projectId: string, assetId: string, points = 600) =>
        request<{ duration: number; points: number; peaks: number[] }>(
          `/edit/v2/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}/waveform?points=${points}`,
        ),
      render: (projectId: string) =>
        request<EditorV2RenderResult>(`/edit/v2/projects/${encodeURIComponent(projectId)}/render`, {
          method: "POST",
          body: "{}",
        }),
      streamUrl: (projectId: string, assetId: string) =>
        `${HTTP_BASE}/edit/v2/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}/stream`,
      thumbnailUrl: (projectId: string, assetId: string) =>
        `${HTTP_BASE}/edit/v2/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}/thumbnail`,
      frameThumbnailUrl: (projectId: string, assetId: string, at: number, width = 180) =>
        `${HTTP_BASE}/edit/v2/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}/thumbnail?at=${Math.max(0, at).toFixed(2)}&width=${width}`,
      audioProxyUrl: (projectId: string, assetId: string) =>
        `${HTTP_BASE}/edit/v2/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}/audio-proxy`,
      videoProxyUrl: (projectId: string, assetId: string) =>
        `${HTTP_BASE}/edit/v2/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}/video-proxy`,
    },
  },

  reviews: {
    options: () => request<{ verdicts: string[]; reasons: string[] }>("/reviews/options"),
    list:    (limit = 500) => request<{ reviews: ClipReview[] }>(`/reviews?limit=${limit}`),
    save:    (stem: string, bucket: Bucket, review: {
      rating: number | null;
      verdict: ClipReview["verdict"];
      reasons: string[];
      tags: string[];
      notes: string;
      caption_notes: string;
    }) => request<{ review: ClipReview }>(`/reviews/${encodeURIComponent(stem)}?bucket=${bucket}`, {
      method: "PUT",
      body: JSON.stringify(review),
    }),
  },

  profile: {
    get:     ()                  => request<{ profile: any; schema: any }>("/profile"),
    save:    (profile: any)      => request<{ ok: boolean }>("/profile", { method: "PUT", body: JSON.stringify(profile) }),
    add:     (key: string, value: any) =>
      request<{ added: boolean; profile: any }>("/profile/add",    { method: "POST", body: JSON.stringify({ key, value }) }),
    remove:  (key: string, value: any) =>
      request<{ removed: boolean; profile: any }>("/profile/remove", { method: "POST", body: JSON.stringify({ key, value }) }),
    suggest: ()                  => request<{ job_id: string }>("/profile/suggest", { method: "POST", body: "{}" }),
    suggestFromReviews: ()       => request<{ job_id: string }>("/profile/suggest-from-reviews", { method: "POST", body: "{}" }),
    apply:   (patch: {
                add: Record<string, any[]>;
                remove: Record<string, any[]>;
                context_rules?: string[];
                slang_glossary?: Record<string, string>;
                avoid_patterns?: string[];
                save?: boolean;
              }) =>
      request<{ stats: any; profile: any }>("/profile/apply", { method: "POST", body: JSON.stringify(patch) }),
  },

  settings: {
    get:   ()                          => request<any>("/settings"),
    patch: (updates: Record<string, any>) =>
      request<any>("/settings", { method: "PATCH", body: JSON.stringify(updates) }),
  },
};

// ---- WebSocket helpers ------------------------------------------------------

export function subscribeLogs(onMessage: (line: LogLine) => void): () => void {
  const ws = new WebSocket(`${wsBase()}/stream/logs`);
  ws.onmessage = (ev) => {
    try {
      const data: LogLine = JSON.parse(ev.data);
      if (data.keepalive) return;
      onMessage(data);
    } catch {}
  };
  return () => ws.close();
}

export function subscribeJob(
  jobId: string,
  onMessage: (info: JobInfo) => void,
  onDone?: () => void,
): () => void {
  const ws = new WebSocket(`${wsBase()}/stream/job/${jobId}`);
  ws.onmessage = (ev) => {
    try {
      const data = JSON.parse(ev.data);
      if (data.keepalive) return;
      onMessage(data as JobInfo);
      const terminal = ["done", "failed", "cancelled"].includes(data.status);
      if (terminal) onDone?.();
    } catch {}
  };
  ws.onclose = () => onDone?.();
  return () => ws.close();
}
