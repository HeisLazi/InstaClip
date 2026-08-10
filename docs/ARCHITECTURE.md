# InstaClip Architecture

## Backend entry

`backend/main.py` builds a FastAPI app and mounts the clipper router set at runtime:

1. `pipeline` — start and manage the durable VOD pipeline.
2. `clips` — list, move, and inspect raw cuts and edits.
3. `clip_room` — candidate review workflow.
4. `edit` — legacy editor operations.
5. `editor_v2` — multitrack editor project CRUD and render jobs.
6. `language` — language pack / slang / pronunciation.
7. `reviews` — submit keep/reject labels for learning.
8. `profile` — taste profile, memory, and profile tuner.
9. `settings` — read/update `config/settings.json`.
10. `status` — workspace counts, health, and current job status.
11. `stream` — WebSocket log/event stream.
12. `tester` — local preflight and optional cloud session bridge.

The `APP_EDITION` environment variable selects behavior. The public edition ships as `clipper`; `full` is accepted for compatibility but owner-only modules are not present.

## Modules map

| Module | Responsibility |
|---|---|
| `fetcher` | Resolve VODs from local disk or `yt-dlp` downloads. |
| `listener` | Extract audio, run `faster-whisper`, emit word-timestamp transcripts with checkpoints. |
| `clip_engine` | Rule-based highlight detection (audio spike, repetition, profile match, face reaction, keyword spike). |
| `clip_judge` | Optional LLM-based taste judge (Claude/Gemini) when API keys are configured. |
| `cutter` | `ffmpeg`-backed clip extraction with pre/post roll. |
| `candidate_budget` | Select which detected candidates are physically cut. |
| `editor` / `editor_v2` | Legacy and multitrack editing models, project serialization, transitions, captions. |
| `clip_room` | Review UI data model and candidate state coordination. |
| `pipeline_sync` | Promote pipeline detections into the relational Clip Room. |
| `render_worker` | Async render queue for edits and compilations. |
| `director` | Memory-grounded re-ranking of candidates via explainable rules. |
| `director_memory` | Stores creator memory/context used by the Director. |
| `review_trainer` | Feeds keep/reject reviews back into the taste profile. |
| `quality_classifier` | Embeddings + scikit-learn classifier for clip quality. |
| `profiler` | Builds the initial taste profile from example clips. |
| `profile_tuner` | Suggests profile edits by comparing good/bad clips or review notes. |
| `face_detector` | Face/signal detection (depends on `mediapipe`/`opencv-python`). |
| `face_locator` | Locate faces for framing/vertical cropping. |
| `speaker_id` | Speaker enrollment and diarization signals. |
| `language_pack` | Slang, names, pronunciation overrides. |
| `clip_extend` | Extend candidate boundaries to natural pauses. |
| `clip_hazards` | Detect hard-subtitles, loading screens, etc. |
| `clip_preview` | Lightweight candidate previews. |
| `clip_reviews` / `clip_memory` | Review and memory bookkeeping. |
| `clip_context` / `media_story` / `story_engine` / `stream_context` | Narrative and context analysis. |
| `transcript_ops` | Transcript slicing, search, and normalization. |
| `vod_resolver` | VOD path/name normalization. |
| `streamer_lexicon` | Streamer-specific vocabulary. |
| `compilation` | Stitch multiple clips into compilations. |
| `vision_describer` | Optional local-vision descriptions. |
| `clip_delivery` | Discord delivery stubs (public edition keeps the module for tests but no live bot; tunnel fallback removed). |
| `tester_gateway` / `tester_profile` | Optional cloud judge bridge and local tester profile. |
| `scene_layout` | Scene composition helpers. |
| `utils` | Audio, file, path, text, thumbnail, progress, whisper-bundle helpers. |

## Database layer

- `db/base.py` — SQLAlchemy `Base`, tenant/creator default, session factory.
- `db/models.py` — `Creator`, `Vod`, `ClipCandidate`, `ClipVersion`, `WorkflowEvent`, plus memory/stream/analytics tables.
- `db/state_machine.py` — candidate state transitions (`DETECTED`, `REVIEWED`, `APPROVED`, `REJECTED`, etc.).
- `db/repository.py` / `db/job_store.py` — data access and durable job persistence.
- `db/migrations/` — Alembic migration scripts; `db/migrate_json.py` migrates legacy JSON state.

The default DB is `sqlite:///./data/instaclip.db`. It is created automatically on first backend start.

## Frontend structure

- `src/main.tsx` — React entry + React Query provider.
- `src/App.tsx` — shell layout, sidebar, command bar, log drawer, page routing.
- `src/nav.ts` — `PageKey` enum and `CLIPPER_NAV` sidebar taxonomy.
- `src/api/client.ts` — typed REST + WebSocket client.
- `src/pages/` — top-level pages: Dashboard, Gallery, ClipRoom, Editor, Profile, Language, Preferences, Account, Onboarding, Tutorial.
- `src/components/` — shared components (Sidebar, StatusBar, LogDrawer, BatchPanel, JobsPanel, etc.).
- `src/editor-v2/` — multitrack editor: model, reducer, history, preflight, DnD, timeline, waveform, preview, inspector, story panel.
- `src/lib/tauri.ts` — Tauri API guards so the app still runs in a browser during dev.
- `src/styles/globals.css` — dark zinc-based theme.

## Tauri shell

- `src-tauri/src/lib.rs` — spawns the Python backend on port 8765, kills it on exit.
- `src-tauri/src/main.rs` — desktop window entrypoint.
- `tauri.conf.json` — dev config (`com.instaclip.app`).
- `tauri.clipper.conf.json` — clipper beta config with external binary placeholders.

Icons are not committed; regenerate with `frontend/generate_icons.py` before `tauri build`.

## Config and paths

- `config/settings.json` — runtime tuning (whisper model, thresholds, engine selection, etc.).
- `config/paths.py` — workspace layout under `data/` and `output/`.
- `.env.example` — environment variable template.
- `INSTACLIP_EDITION` selects runtime mode; `VITE_APP_EDITION` mirrors it for the frontend build.

## Data flow

```
[ VOD source ]
     |
     v
[ fetcher ]  ----->  [ listener / whisper ]  ----->  [ transcript JSON ]
     |                                               |
     v                                               v
[ clip_engine / director / quality_classifier ]  [ clip_room DB ]
     |                                               |
     v                                               v
[ cutter / ffmpeg ]  ----->  [ output/clips ]  <---- [ review labels ]
     |                                               |
     v                                               v
[ editor_v2 ]  ----->  [ render_worker ]  ----->  [ taste profile update ]
```

The core loop is intentionally file-based so it works without the database; the DB adds durable jobs, candidate review state, and the learning loop.
