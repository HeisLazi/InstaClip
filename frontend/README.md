# InstaClip frontend (Tauri + React)

React + Vite frontend for the local-first InstaClip desktop app.

## Architecture

```
[ Tauri shell (Rust) ]
        |
        +-- spawns: python -m backend.main   (FastAPI on 127.0.0.1:8765)
        |
        +-- hosts WebView2 → React frontend (Vite dev / dist build)
```

In dev mode the backend and frontend run as two parallel processes.

## Dev

```bash
# terminal 1 — backend
python -m backend.main

# terminal 2 — frontend (browser preview)
cd frontend
npm run dev          # http://localhost:5173

# OR full Tauri shell with webview
cd frontend
npm run tauri dev    # native window, spawns the backend itself
```

## Files

```
src/
  main.tsx              entry, React Query provider
  App.tsx               window layout, sidebar + status bar + drawer
  nav.ts                clipper nav taxonomy
  api/client.ts         typed REST + WS client
  styles/globals.css    shadcn dark palette (zinc)
  components/           shared UI pieces
  pages/                top-level views
  editor-v2/            multitrack editor model + UI

src-tauri/
  src/lib.rs            spawns the Python backend, kills it on exit
  src/main.rs           windowed entrypoint
  tauri.conf.json
  tauri.clipper.conf.json
  Cargo.toml
  capabilities/default.json
```

## Tests

```bash
npm test -- --run
npx tsc --noEmit
npm run build:clipper
```
