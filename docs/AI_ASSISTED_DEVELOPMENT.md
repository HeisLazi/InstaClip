# AI-Assisted Development

## How this codebase was built

InstaClip was developed with heavy AI assistance. The private commercial codebase uses a documented multi-agent operating contract (`AGENTS.md`) that assigns roles across several AI agents:

- **Claude** — architecture, product decisions, and long-form design.
- **Codex** — implementation passes and test scaffolding.
- **Ollama** — local model inference and lightweight validation.
- **Antigravity** — code review, lint/security, and integration checks.

This division of labor was managed by the human product owner (Lazarus / HeisLazi) through structured prompts, task queues, and review gates in the private repository.

## How this public edition was prepared

This public portfolio edition was prepared by an opencode engineering manager delegating to subagents. The work was done in the destination repo only; the private repo was not modified. Subagents performed:

- **Exploration** — listing the public edition tree and identifying modules, routers, frontend pages, and tests.
- **Extraction** — confirming the clipper router set and edition gating were already in place in the public branch.
- **Testing** — running backend `pytest`, frontend `vitest`, TypeScript checks, and the clipper Vite build.
- **Review** — cross-checking documentation claims against the actual code and verification outputs.

## Verification honesty

Every verification number cited in this repository was produced by actually running the command. In particular:

- `261 passed, 1 warning in 5.77s` — produced by `.venv-public/bin/python -m pytest tests/ -q`.
- `7 passed test files, 127 passed tests` — produced by `npm test -- --run` in `frontend/`.
- `npx tsc --noEmit` — produced zero errors.
- `npm run build:clipper` — produced a successful Vite build with the clipper bundle check passing.
- `npm audit` — produced the 4-vulnerability report recorded in `docs/VERIFICATION.md`.

No screenshots, numbers, or feature claims were fabricated. Claims about modules that were not exercised (e.g., live `tauri build`, live cloud gateway, real multi-hour VOD ingest) are explicitly listed as not run in `docs/VERIFICATION.md` and `docs/KNOWN_LIMITATIONS.md`.
