import logging
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

from config import cfg, paths
from utils.file_utils import load_json, save_json
from utils.progress_events import emit as emit_progress

log = logging.getLogger("main")


def _load_batch_progress():
    progress = load_json(paths.METADATA_DIR / "batch_progress.json")
    return progress if progress else {"vods": {}}


def _save_batch_progress(progress):
    save_json(progress, paths.METADATA_DIR / "batch_progress.json")


def _results_exist(vod_name):
    return (paths.METADATA_DIR / f"{Path(vod_name).stem}_results.json").exists()


def _mark_batch_result(progress, vod_name, result):
    progress.setdefault("vods", {})
    progress["vods"][vod_name] = {
        "success": bool(result.get("success")),
        "clips_found": result.get("clips_found", 0),
        "clips_cut": result.get("clips_cut", 0),
        "error": result.get("error"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    _save_batch_progress(progress)


def run_profiler_only():
    from modules.profiler.profiler import build_profile
    log.info("Running Module 0: Profiler only...")
    profile = build_profile()
    if not profile:
        log.error("Profiler failed.")
        sys.exit(1)
    log.info("Profiler complete. Run main.py again to process a VOD.")


def run_pipeline(source=None, profile=None, model=None, interactive=None):
    log.info("=" * 60)
    log.info("PROJECT LEK — PIPELINE START")
    log.info("=" * 60)

    if not profile and os.environ.get("INSTACLIP_EDITION", "full").lower() == "clipper":
        profile = {"clips_analyzed": 0, "source": "tester_taste_profile"}
        log.info("Clipper edition uses the signed-in tester taste profile.")
    if not profile:
        profile = load_json(paths.PROFILE_PATH)
        if not profile:
            log.warning("No profile found. Running profiler first...")
            from modules.profiler.profiler import build_profile
            profile = build_profile()
            if not profile:
                log.error("Profiler failed. Add clips to data/old_clips/ and retry.")
                return {"success": False}
        else:
            log.info(f"Profile loaded — {profile.get('clips_analyzed', 0)} clips analyzed.")

    # Module 1: Fetcher
    try:
        emit_progress(stage="fetching", message="Fetching VOD…")
        from modules.fetcher.fetcher import fetch_vod
        vod_path = fetch_vod(source)
        if not vod_path:
            log.error("No VOD selected.")
            return {"success": False}
    except Exception as e:
        log.error(f"Fetcher crashed: {e}")
        log.error(traceback.format_exc())
        return {"success": False, "error": str(e)}

    emit_progress(stage="listener_starting", vod=vod_path.name,
                  message=f"Transcribing {vod_path.name}")

    # Module 2: Listener
    try:
        from modules.listener.listener import transcribe_vod
        listener_interactive = (source is None) if interactive is None else interactive
        transcript = transcribe_vod(vod_path, model=model, interactive=listener_interactive)
        if not transcript:
            log.error("Transcription failed.")
            return {"success": False, "vod": vod_path.name, "error": "transcription_failed"}
    except Exception as e:
        log.error(f"Listener crashed on {vod_path.name}: {e}")
        log.error(traceback.format_exc())
        return {"success": False, "vod": vod_path.name, "error": str(e)}

    emit_progress(stage="clip_engine_starting", vod=vod_path.name,
                  message="Scoring segments and merging highlights")

    # Module 3: Clip Engine — taste-judge (Gemini, scores against data/clip_taste.md)
    # or the legacy audio-spike rule engine, chosen by settings.clip_engine.selection_engine.
    engine = getattr(cfg.clip_engine, "selection_engine", "rules")
    try:
        if engine == "judge":
            from modules.clip_judge import select_highlights
            highlights = select_highlights(transcript, vod_path)
        else:
            from modules.clip_engine.clip_engine import find_highlights
            highlights = find_highlights(transcript, profile, vod_path)
        if not highlights:
            log.warning(
                f"No highlights found for {vod_path.name}. "
                f"Try lowering highlight_threshold in settings.json "
                f"(currently {cfg.clip_engine.highlight_threshold})"
            )
            return {"success": True, "vod": vod_path.name, "clips_found": 0, "clips_cut": 0}
    except Exception as e:
        log.error(f"Clip Engine crashed on {vod_path.name}: {e}")
        log.error(traceback.format_exc())
        return {"success": False, "vod": vod_path.name, "error": str(e)}

    # Module 4: Cutter
    try:
        from modules.cutter.cutter import cut_clips
        from modules.candidate_budget import select_auto_cut_candidates

        cutter_interactive = (source is None) if interactive is None else interactive
        cut_candidates = (
            highlights
            if cutter_interactive
            else select_auto_cut_candidates(highlights)
        )
        if len(cut_candidates) < len(highlights):
            log.info(
                "Stage 2 auto-cut budget: materializing top %d of %d detections; "
                "all detections remain in metadata/Clip Room.",
                len(cut_candidates),
                len(highlights),
            )
        emit_progress(
            stage="cutter_starting",
            vod=vod_path.name,
            message=(
                f"Cutting {len(cut_candidates)} ranked clips "
                f"from {len(highlights)} detections"
            ),
        )
        cut_paths = cut_clips(vod_path, cut_candidates, interactive=cutter_interactive)
    except Exception as e:
        log.error(f"Cutter crashed on {vod_path.name}: {e}")
        log.error(traceback.format_exc())
        return {"success": False, "vod": vod_path.name, "error": str(e)}

    # Module 5: sync this VOD's detections into the relational Clip Room (Phase 2).
    # Non-fatal — the file-based pipeline must keep working even if the DB hiccups.
    promoted = 0
    try:
        from modules.pipeline_sync import sync_vod
        # judge_top=10: the LLM taste judge rates the promoted top-10 (the clips that
        # reach Discord) against the creator's memory, recording a verdict on each.
        sync = sync_vod(vod_path.name, vod_path=str(vod_path), judge_top=10)
        promoted = sync["promoted"]
    except Exception as e:  # noqa: BLE001
        log.warning(f"Clip Room DB sync skipped for {vod_path.name}: {e}")

    emit_progress(stage="done", percent=100.0, vod=vod_path.name,
                  message=f"Done — cut {len(cut_paths)} clips from {vod_path.name}")

    result = {
        "success": True,
        "vod": vod_path.name,
        "clips_found": len(highlights),
        "clips_selected_for_cut": len(cut_candidates),
        "clips_cut": len(cut_paths),
        "promoted_to_clip_room": promoted,
    }

    log.info("=" * 60)
    log.info("PIPELINE COMPLETE")
    log.info(f"  VOD:        {vod_path.name}")
    log.info(f"  Highlights: {len(highlights)} found")
    log.info(f"  Selected:   {len(cut_candidates)} for physical cuts")
    log.info(f"  Clips cut:  {len(cut_paths)}")
    log.info(f"  Location:   {paths.CLIPS_DIR}")
    log.info("=" * 60)

    return result


def run_batch(batch_size=10, burst_limit=None):
    from modules.fetcher.fetcher import list_local_vods

    progress = _load_batch_progress()

    profile = load_json(paths.PROFILE_PATH)
    if not profile:
        log.warning("No profile found. Running profiler first...")
        from modules.profiler.profiler import build_profile
        profile = build_profile()
        if not profile:
            log.error("Profiler failed. Cannot run batch.")
            sys.exit(1)

    log.info(f"Profile loaded — {profile.get('clips_analyzed', 0)} clips analyzed.")

    from modules.listener.listener import load_whisper_model
    try:
        model = load_whisper_model()
    except Exception as e:
        log.error(f"Failed to load Whisper for batch: {e}")
        sys.exit(1)

    vods = list_local_vods()
    if not vods:
        log.error("No VODs found.")
        sys.exit(1)

    print("\n" + "=" * 60)
    print(f"BATCH MODE — Pick up to {batch_size} VODs")
    print("=" * 60)
    for i, vod in enumerate(vods, start=1):
        size_mb = round(vod.stat().st_size / (1024 * 1024), 1)
        print(f"  [{i:>3}] {vod.name}  ({size_mb} MB)")
    print("=" * 60)
    print(f"Enter up to {batch_size} numbers separated by commas (e.g. 1,5,12,23)")
    print("Or press Enter to auto-pick first unprocessed VODs")

    choice = input("Your selection: ").strip()
    selected_vods = []

    if choice == "":
        for vod in vods:
            transcript_cache = paths.TRANSCRIPTS_DIR / (vod.stem + ".json")
            if not transcript_cache.exists():
                selected_vods.append(vod)
            if len(selected_vods) >= batch_size:
                break
        if not selected_vods:
            selected_vods = vods[:batch_size]
            print(f"All VODs transcribed. Processing first {batch_size}.")
        else:
            print(f"Auto-selected {len(selected_vods)} unprocessed VODs.")
    else:
        try:
            indices = [int(x.strip()) - 1 for x in choice.split(",")]
            selected_vods = [vods[i] for i in indices if 0 <= i < len(vods)]
            if len(selected_vods) > batch_size:
                selected_vods = selected_vods[:batch_size]
                print(f"Capped at {batch_size} VODs.")
        except (ValueError, IndexError):
            log.error("Invalid selection.")
            sys.exit(1)

    if not selected_vods:
        log.error("No VODs selected.")
        sys.exit(1)

    already_done = []
    pending_vods = []
    for vod in selected_vods:
        progress_entry = progress.get("vods", {}).get(vod.name, {})
        if progress_entry.get("success") or _results_exist(vod.name):
            already_done.append(vod)
        else:
            pending_vods.append(vod)

    if already_done:
        print("\nSkipping already completed VODs:")
        for vod in already_done:
            print(f"  - {vod.name}")

    if burst_limit is not None and burst_limit > 0:
        pending_vods = pending_vods[:burst_limit]
    active_burst_limit = burst_limit
    burst_limit = None

    if not pending_vods:
        print("\nNothing left to process in this selection.")
        print(f"Progress file: {paths.METADATA_DIR / 'batch_progress.json'}")
        sys.exit(0)

    print("\n" + "=" * 60)
    print(f"BATCH CONFIRMED — {len(selected_vods)} VODs queued")
    print("=" * 60)
    print(f"Processing this run: {len(pending_vods)} pending VOD(s)")
    for i, vod in enumerate(pending_vods, start=1):
        print(f"  {i}. {vod.name}")
    if active_burst_limit is not None and active_burst_limit > 0:
        print("=" * 60)
        print(f"Burst limit active - processing at most {active_burst_limit} VOD(s) this run.")
    print("=" * 60)
    print("Clips will be cut automatically — no prompts during batch.")
    confirm = input("Start batch? [y/n]: ").strip().lower()
    if confirm != "y":
        print("Cancelled.")
        sys.exit(0)

    batch_results = []
    total_clips = 0

    for i, vod in enumerate(pending_vods, start=1):
        print(f"\n{'='*60}")
        print(f"BATCH [{i}/{len(pending_vods)}]: {vod.name}")
        print(f"{'='*60}")

        result = run_pipeline(
            source=str(vod),
            profile=profile,
            model=model,
            interactive=False,
        )
        batch_results.append(result)
        total_clips += result.get("clips_cut", 0)
        _mark_batch_result(progress, vod.name, result)

        if not result.get("success"):
            log.error(f"VOD failed: {result.get('error', 'unknown_error')}")
            log.info("Continuing to next VOD...")

    successful = [r for r in batch_results if r.get("success")]
    failed = [r for r in batch_results if not r.get("success")]

    print("\n" + "=" * 60)
    print("BATCH COMPLETE")
    print("=" * 60)
    print(f"  VODs processed:  {len(successful)}/{len(pending_vods)}")
    print(f"  Total clips cut: {total_clips}")
    print(f"  Clips location:  {paths.CLIPS_DIR}")
    print(f"  Progress file:   {paths.METADATA_DIR / 'batch_progress.json'}")
    print("=" * 60)

    if failed:
        print("Failed VODs:")
        for r in failed:
            print(f"  x {r.get('vod', 'unknown')} — {r.get('error', 'unknown error')}")

    print("\nNext steps:")
    print("  1. Review clips in output/clips/")
    print("  2. Move good clips -> data/old_clips/")
    print("  3. Move bad clips  -> output/notclips/")
    print("  4. Run: python main.py --profile-only")
    print("  5. Run another batch: python main.py --batch")
    print("=" * 60)


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--profile-only" in args:
        run_profiler_only()

    elif "--batch" in args:
        idx = args.index("--batch")
        size = 10
        burst_limit = None
        if idx + 1 < len(args):
            try:
                size = int(args[idx + 1])
            except ValueError:
                pass
        if "--burst" in args:
            burst_idx = args.index("--burst")
            if burst_idx + 1 < len(args):
                try:
                    burst_limit = int(args[burst_idx + 1])
                except ValueError:
                    pass
        run_batch(batch_size=size, burst_limit=burst_limit)

    else:
        source = args[0] if args else None
        run_pipeline(source)
