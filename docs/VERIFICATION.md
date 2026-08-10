# Verification

All commands below were run in the public workspace on branch `portfolio/initial-public-edition`. Outputs are recorded exactly as produced.

## Backend tests

Command:

```bash
.venv-public/bin/python -m pytest tests/ -q
```

Output:

```
........................................................................ [ 27%]
........................................................................ [ 55%]
........................................................................ [ 82%]
...............................................                          [100%]
=============================== warnings summary ===============================
.venv-public/lib/python3.14/site-packages/fastapi/testclient.py:1
  .venv-public/lib/python3.14/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as starlette_TestClient  # noqa

-- Docs: https://docs.pytest.org/stable/warnings.html
261 passed, 1 warning in 5.77s
```

## Frontend tests

Command:

```bash
cd frontend
npm test -- --run
```

Output:

```
npm notice run instaclip-frontend@0.1.0 test
npm notice run vitest run --run

  RUN  v4.1.9 frontend

 Test Files  7 passed (7)
      Tests  127 passed (127)
   Start at  00:07:47
   Duration  1.48s (transform 1.20s, setup 0ms, import 2.21s, tests 157ms, environment 2ms)
```

## Type check

Command:

```bash
cd frontend
npx tsc --noEmit
```

Result: no output, no errors.

## Clipper build

Command:

```bash
cd frontend
npm run build:clipper
```

Output:

```
npm notice run instaclip-frontend@0.1.0 build:clipper
npm notice run 'vite build --mode clipper && node scripts/check-clipper-bundle.mjs'
vite v6.4.2 building for clipper...
transforming...
✓ 1759 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                    0.83 kB │ gzip:   0.45 kB
dist/assets/index-CGXFdpPC.css    83.17 kB │ gzip:  15.37 kB
dist/assets/index-BkW3q3LQ.js      0.13 kB │ gzip:   0.14 kB
dist/assets/index-BJgKrDjI.js      0.17 kB │ gzip:   0.17 kB
dist/assets/core-mPlcS5K-.js       0.83 kB │ gzip:   0.45 kB
dist/assets/webview-D1qcvjE1.js   17.43 kB │ gzip:   3.94 kB
dist/assets/index-6HgJdyMT.js    718.03 kB │ gzip: 202.14 kB
✓ built in 4.37s

(!) Some chunks are larger than 500 kB after minification. Consider:
- Using dynamic import() to code-split the application
- Using build.rollupOptions.output.manualChunks to improve chunking: https://rollupjs.org/configuration-options/#output-manualchunks
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
Clipper bundle check passed.
```

## Environment facts

- Python version used: **3.14.6** (`.venv-public/bin/python --version`).
- Heavy dependencies listed in `requirements.txt` but **not installed** in this environment:
  - `torch`
  - `mediapipe`
  - `resemblyzer`
  - `sounddevice`
  - `opencv-python`
- `mediapipe` specifically requires **Python 3.12** and has no published wheels for Python 3.13/3.14 at the time of writing.
- The suite still passes because modules degrade gracefully (try/except fallbacks) and tests mock the heavy-ML paths.
- Installed packages present include: `faster-whisper`, `librosa`, `numpy`, `ffmpeg-python`, `yt-dlp`, `fastapi`, `uvicorn`, `soundfile`, `scikit-learn`, `SQLAlchemy`, `alembic`, `requests`, `Pillow`, `joblib`.

## npm audit

Command:

```bash
cd frontend
npm audit --audit-level=none
```

Output:

```
# npm audit report

@babel/core  <=7.29.0
@babel/core: Arbitrary File Read via sourceMappingURL Comment - https://github.com/advisories/GHSA-4x5r-pxfx-6jf8
fix available via `npm audit fix`

nanoid  <=3.3.16
Severity: high
nanoid: non-secure generators can loop indefinitely with negative size - https://github.com/advisories/GHSA-28wg-ghj8-5hjv
nanoid: custom generators can loop indefinitely when size is zero - https://github.com/advisories/GHSA-2v37-7h3g-55p8
fix available via `npm audit fix`

postcss  <=8.5.22
Severity: high
PostCSS: Path Traversal in Previous Source Map Auto-Loading (sourceMappingURL) leads to Arbitrary .map File Disclosure - https://github.com/advisories/GHSA-r28c-9q8g-f849
PostCSS: incomplete fix of GHSA-6g55-p6wh-862q — attacker-controlled sourceMappingURL reads arbitrary .map files when `from` is unset - https://github.com/advisories/GHSA-fxqj-rqcc-2cmp
fix available via `npm audit fix`

vite  <=6.4.2
Severity: high
launch-editor: NTLMv2 hash disclosure via UNC path handling on Windows - https://github.com/advisories/GHSA-v6wh-96g9-6wx3
vite: `server.fs.deny` bypass on Windows alternate paths - https://github.com/advisories/GHSA-fx2h-pf6j-xcff
fix available via `npm audit fix`

4 vulnerabilities (1 low, 3 high)
```

These findings are in upstream dependencies and were not introduced by this edition's code.

## What was NOT run

- `tauri build` / Windows installer creation.
- Clean-machine acceptance testing on a fresh OS install.
- Live cloud gateway tests (no `CLIPPER_GATEWAY_URL` was configured).
- End-to-end ingest of a real multi-hour VOD in this verification pass (the test suite exercises synthetic media and mocked paths).
