# InstaClip — Clips That Learn Your Taste

**InstaClip** is a local-first desktop application that turns streamer VODs into short vertical clips. It ingests video from disk or URL, transcribes speech with `faster-whisper`, detects highlight moments, cuts them with `ffmpeg`, and learns the creator's taste from ongoing reviews. The result is an iterative pipeline that gets sharper as the creator rejects bad clips and keeps good ones.

## What this repository is

This is the **public portfolio edition** of a commercial product. It contains a coherent, runnable slice of the InstaClip core:

- the ingest → transcribe → detect → cut pipeline,
- the candidate review workflow (Clip Room),
- the multitrack editor (Editor V2),
- the review/learning loop that updates a taste profile.

**Owner-only surfaces are intentionally NOT included:** the Discord Clip Room bot, publishing (Instagram/TikTok/YouTube), Director chat / Creator OS, the cloud tester gateway, and release packaging are all part of the commercial edition and were removed for this publication.

## MVP status vs production gaps

| Public edition (this repo) | Commercial edition (private) |
|---|---|
| Local pipeline, editor, Clip Room review, profile learning | Signed installer + update machinery |
| Faster-whisper transcription on CPU | Optional cloud LLM judge gateway for remote QA |
| Quality classifier + face/speaker signals (degrades if heavy ML deps missing) | Discord Clip Room bot + delivery |
| SQLite job store with durable pipeline | Publishing to IG/TikTok/YouTube |
| Frontend `npm test` + backend `pytest` suites | Five-tester acceptance gates on clean machines |
| Vite build + Tauri shell scaffolding | Creator OS surfaces: Director chat, Memory UI, Stream Studio, Research Desk, Idea Bank |

The commercial edition remains private. No claim is made that this repo is a finished consumer product.

## Screenshots

No screenshots are included in this edition. The UI can be run locally with the commands below.

## Workflow & feature summary

1. **Fetch** — load a local VOD or download via `yt-dlp`.
2. **Transcribe** — `faster-whisper` with word-level timestamps.
3. **Detect** — rule-based clip engine scores audio spikes, repetition, profile match, face reactions, and keyword spikes; optional quality classifier re-ranks candidates.
4. **Cut** — `ffmpeg` extracts each candidate with configurable pre/post roll.
5. **Review** — Clip Room lets the user keep, reject, or annotate clips.
6. **Edit** — Editor V2 supports multitrack arrangement, captions, transitions, and sound FX placeholders.
7. **Learn** — review labels feed back into the taste profile and quality classifier so the next run is better aligned with the creator's taste.

Additional modules:

- **Language pack** — teach slang, names, and pronunciation so transcripts and captions match the streamer's vocabulary.
- **Taste profile** — rule-based profile the user can tune by hand or have the local LLM suggest updates from kept/rejected clips.
- **Quality classifier** — learnable scoring model trained on kept vs rejected clips.

## Architecture overview

- **Backend** — FastAPI on `127.0.0.1:8765` (loopback-only, no authentication by design).
- **Frontend** — React + Vite; dev proxy maps `/api` to port `8765`.
- **Desktop shell** — Tauri (Rust) spawns the Python backend as a sidecar.
- **Database** — SQLite via SQLAlchemy + Alembic migrations.
- **Media** — `ffmpeg`/`ffprobe` on PATH; proxies/thumbnails/waveforms are cached under `data/`.
- **Speech** — `faster-whisper`; model downloaded on first use from HuggingFace.
- **Edition gating** — `INSTACLIP_EDITION` / `VITE_APP_EDITION` select the clipper runtime.

For details see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Setup & verification

### Backend

```bash
python3.12 -m venv .venv-public      # mediapipe requires Python 3.12 at the time of writing
source .venv-public/bin/activate
pip install -r requirements.txt
# ensure ffmpeg and ffprobe are on PATH
python -m backend.main               # 127.0.0.1:8765
```

> The verification environment used Python **3.14.6**; `mediapipe`, `torch`, `resemblyzer`, `sounddevice`, and `opencv-python` were **not installed** there. The test suite still passes because modules degrade gracefully and heavy-ML paths are mocked.

### Frontend

```bash
cd frontend
npm install
npm run dev          # Vite dev server on http://localhost:5173
```

### Tests

```bash
python -m pytest tests/ -q          # 261 passed, 1 warning (snapshot from verification)
cd frontend && npm test -- --run  # 7 files, 127 passed
npx tsc --noEmit                    # no errors
npm run build:clipper              # Vite build + clipper bundle check passes
```

- Whisper model downloads on first use from HuggingFace.
- Face/scene models auto-download from public sources when their dependencies are installed.

## Privacy model

- **Local-first** — media and transcripts stay on the machine.
- **Loopback binding** — the API only listens on `127.0.0.1`.
- **No telemetry** — nothing is sent anywhere by default.
- **Origin + Host guards** — CORS allowlist plus Host-header allowlist block DNS-rebinding and cross-site POST side effects.
- **Optional cloud judge** — a cloud LLM judge is only used if `CLIPPER_GATEWAY_URL` is configured; it is empty by default.
- **Credential handling** — no credentials live in this repo. `.env.example` contains only placeholder keys, and `.gitignore` excludes `.env`, credential files, and model weights.

See [`docs/PRIVACY_AND_SECURITY.md`](docs/PRIVACY_AND_SECURITY.md).

## Lazarus's responsibilities

Lazarus (also `HeisLazi`) is the product owner of the commercial InstaClip project. This public edition is his portfolio artifact. He owns the private repository, licensing, and all commercial decisions about the product. The public edition was prepared by an opencode engineering manager delegating to subagents.

## AI-assistance disclosure

This codebase was developed with heavy AI assistance. The private commercial repo uses a documented multi-agent workflow (Claude, Codex, Ollama, Antigravity roles per that repo's `AGENTS.md` operating contract). This public edition was prepared by an opencode engineering manager with subagents (exploration, extraction, testing, review). Every verification number in this repo was produced by actually running the commands; no results were fabricated.

See [`docs/AI_ASSISTED_DEVELOPMENT.md`](docs/AI_ASSISTED_DEVELOPMENT.md).

## Known limitations

- No Discord integration or delivery.
- No publishing to social platforms.
- No cloud tester gateway by default (the LLM judge is opt-in via `CLIPPER_GATEWAY_URL`).
- No Creator OS surfaces (Director chat, Memory UI, Stream Studio, Research Desk, Idea Bank).
- No release packaging, code signing, or installer.
- No clean-machine acceptance testing was run.
- `mediapipe` requires Python 3.12; the verification environment only had Python 3.14.6.
- Whisper model downloads on first use.
- The sound FX library is empty (no redistributable audio assets).
- Tauri icons must be regenerated via `frontend/generate_icons.py` before a Tauri build.
- `tauri build` was not run.
- `npm audit` reports 4 vulnerabilities in upstream dependencies (1 low, 3 high) not introduced by this edition.

See [`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md).

## License

No license has been chosen yet; all rights reserved pending an owner decision.
