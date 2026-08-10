# Known Limitations

## Missing owner-only surfaces

The public edition does **not** include the commercial product's owner-only features:

- Discord Clip Room bot and delivery (the Discord status UI, "Send to Discord" action, `/discord/*` API client surface, and `api.clipRoom.deliver` method are not present in this edition). The public Clip Room also omits the backend `POST /clip-room/candidates/{id}/send` route and the corresponding `send` action in the frontend `api.clipRoom.action` surface; the underlying `send_to_discord` state-machine transition remains as a local no-op through `NullDiscordGateway` for source parity.
- Twitch sync and credentials (the `/twitch/*` API client surface, including status, credentials, and sync methods, is not present in this edition).
- Publishing to Instagram, TikTok, or YouTube (the publishing UI, account management, queue, and `/publish/*` API client surface are not present in this edition).
- Cloud tester gateway (the LLM judge is opt-in via `CLIPPER_GATEWAY_URL` only).
- Creator OS surfaces: Director chat, Memory UI, Stream Studio, Research Desk, Idea Bank.
- Release packaging, code signing, and installer machinery.

## Verification gaps

The following were not run during preparation of this public edition:

- `tauri build` (Rust desktop bundle).
- Windows installer / NSIS / MSI creation.
- Clean-machine acceptance testing on a fresh OS install.
- Live cloud gateway tests (no `CLIPPER_GATEWAY_URL` was configured).
- End-to-end processing of a real multi-hour VOD in this verification pass.

## Dependency constraints

- `mediapipe` requires **Python 3.12** at the time of writing and has no published wheels for Python 3.13/3.14.
- The verification environment used Python **3.14.6**.
- The following heavy ML/audio packages were **not installed** there: `torch`, `mediapipe`, `resemblyzer`, `sounddevice`, `opencv-python`.
- The test suite passes without them because modules degrade gracefully and tests mock the heavy paths.
- For full runtime features (face detection, speaker ID, quality classifier training) install Python 3.12 and the packages listed in `requirements.txt`.

## Runtime behavior

- The faster-whisper model downloads from HuggingFace on first use.
- Face/scene models auto-download from public sources when their dependencies are installed.
- The sound FX library is empty in this edition; no redistributable audio assets are included.
- Tauri icons are not committed. Run `frontend/generate_icons.py` from a source icon before `tauri build`.

## Security / dependency audit

- `npm audit` reports **4 vulnerabilities** in upstream dependencies (1 low, 3 high) as of the verification run. These were not introduced by this edition's code.
- See `docs/PRIVACY_AND_SECURITY.md` for the local-API guard details.

## Edition-specific exclusions

- Cloudflare quick-tunnel file sharing (`modules/tunnel_publish.py`) is not included in this edition; when a rendered clip exceeds the attachment limit, delivery logs a local notice instead of exposing a public URL.

## License

No license has been chosen yet; all rights reserved pending an owner decision. Do not use, distribute, or create derivative works without explicit permission from the owner.
