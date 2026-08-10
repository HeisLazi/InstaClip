# =============================================================================
# modules/cutter/cutter.py — Module 4: The Cutter
# Project LeK — Auto Clipper V1
# =============================================================================
# PURPOSE:
#   Take highlight timestamps from Module 3 and cut them from the VOD.
#   Outputs vertical (9:16) clips ready for TikTok/YouTube Shorts/Instagram.
#
# OUTPUT:
#   output/clips/{clip_id}.mp4        ← final clips
#   output/metadata/{vod}_results.json ← what was cut and why
#
# DATA CONTRACT:
#   Input:  vod_path Path
#           highlights list (from Module 3)
#   Output: list of successfully cut clip paths
# =============================================================================

import json
import logging
import subprocess
from pathlib import Path

from config import cfg, paths
from utils.clip_files import safe_folder_name
from utils.file_utils import save_json
from utils.progress_events import emit as emit_progress

log = logging.getLogger("cutter")


# =============================================================================
# FFMPEG CUT + FORMAT
# =============================================================================

def cut_clip(
        vod_path: Path,
        start: float,
        end: float,
        output_path: Path,
) -> bool:
    """
    Cut a clip from the VOD using ffmpeg.
    Output: vertical 9:16 format, H264, optimized for social media.

    Uses stream copy where possible for speed, re-encodes for vertical crop.

    Returns True on success.
    """
    duration = end - start

    # Horizontal format — preserve original aspect ratio
    # scale filter ensures dimensions divisible by 2 (H264 requirement)
    vf_filter = "scale=trunc(iw/2)*2:trunc(ih/2)*2"

    command = [
        "ffmpeg",
        "-y",
        "-ss",       str(round(start, 3)),   # Seek to start (fast)
        "-i",        str(vod_path),
        "-t",        str(round(duration, 3)),  # Duration
        "-vf",       vf_filter,
        "-c:v",      "libx264",
        "-preset",   "fast",                  # Balance speed/quality
        "-crf",      "23",                    # Quality (18=best, 28=worst)
        "-c:a",      "aac",
        "-b:a",      "192k",
        "-movflags", "+faststart",            # Web-optimized
        "-avoid_negative_ts", "make_zero",
        str(output_path),
    ]

    try:
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=True,
            timeout=300,
        )
        log.debug(f"Cut: {output_path.name}")
        return True

    except subprocess.CalledProcessError as e:
        log.error(f"ffmpeg failed on {output_path.name}: {e.stderr.decode()[-500:]}")
        return False
    except subprocess.TimeoutExpired:
        log.error(f"ffmpeg timed out on {output_path.name}")
        return False
    except FileNotFoundError:
        log.critical("ffmpeg not found — is it installed and in PATH?")
        return False


# =============================================================================
# REVIEW PROMPT
# Asks user to approve/reject before cutting (optional — can disable)
# =============================================================================

def show_highlight_preview(highlights: list[dict], vod_name: str) -> list[dict]:
    """
    Show all found highlights and let user choose which to cut.
    Returns the approved subset.
    """
    print("\n" + "=" * 60)
    print(f"HIGHLIGHTS FOUND — {vod_name}")
    print("=" * 60)
    print(f"{'#':<4} {'Score':<7} {'Q':<6} {'Start':<10} {'Dur':<8} {'Triggers':<25} Preview")
    print("-" * 90)

    for i, h in enumerate(highlights, start=1):
        start_ts = _seconds_to_timestamp(h["start"])
        dur      = f"{h['duration']:.0f}s"
        triggers = ", ".join(h.get("triggers", []))[:24]
        preview  = h.get("peak_text", "")[:35]
        q_val    = h.get("quality_score")
        q_str    = f"{q_val:.2f}" if isinstance(q_val, (int, float)) else "  —"
        score    = h.get("final_score", h.get("peak_score", 0.0))
        print(f"[{i:<2}]  {score:<7.3f} {q_str:<6} {start_ts:<10} {dur:<8} {triggers:<25} {preview}")

    print("=" * 60)
    print("Options: 'a' = cut all | numbers = cut specific (e.g. '1,3,5') | 'q' = quit")

    while True:
        choice = input("Your choice: ").strip().lower()

        if choice == "q":
            return []
        elif choice == "a":
            return highlights
        else:
            try:
                indices = [int(x.strip()) - 1 for x in choice.split(",")]
                selected = [highlights[i] for i in indices if 0 <= i < len(highlights)]
                if selected:
                    return selected
                print(f"  Enter numbers between 1 and {len(highlights)}")
            except (ValueError, IndexError):
                print("  Invalid input. Try 'a', 'q', or numbers like '1,3,5'")


# =============================================================================
# PUBLIC INTERFACE
# =============================================================================


def generate_clip_name(highlight: dict, index: int) -> str:
    """
    Generate a human-readable clip filename from the peak moment text + score.

    Format: GEN_{score}_{key_phrase}.mp4
    The GEN_ prefix lets the profiler distinguish system clips from creator clips.
    """
    import re
    text = highlight.get("peak_text", "")
    score = highlight.get("peak_score", 0)

    # Clean and shorten text to key phrase (max 6 words)
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]", "", text)
    words = [w for w in text.split() if len(w) > 1][:6]
    phrase = "_".join(words) if words else f"clip_{index:03d}"

    # Format: GEN_0.46_nah_we_dont_got_this
    name = f"GEN_{score:.2f}_{phrase}"

    # Truncate if too long for filesystem
    if len(name) > 80:
        name = name[:80]

    return name

def cut_clips(
        vod_path: Path,
        highlights: list[dict],
        interactive: bool = True,
) -> list[Path]:
    """
    Main cutter entry point.

    Args:
        vod_path:    Path to source VOD
        highlights:  List of highlight dicts from clip engine
        interactive: If True, asks user to approve clips before cutting.
                     Set to False for fully automatic mode.

    Data contract:
        Input:  vod_path, highlights list
        Output: list of Paths to successfully cut clips
    """
    log.info("=" * 60)
    log.info("MODULE 4: CUTTER")
    log.info(f"VOD: {vod_path.name}")
    log.info(f"Highlights to cut: {len(highlights)}")
    log.info("=" * 60)

    if not highlights:
        log.warning("No highlights to cut.")
        return []

    if not vod_path.exists():
        log.error(f"VOD not found: {vod_path}")
        return []

    # --- Interactive review ---
    if interactive:
        approved = show_highlight_preview(highlights, vod_path.name)
    else:
        approved = highlights
        log.info("Automatic mode — cutting all highlights.")

    if not approved:
        log.info("No clips approved. Exiting cutter.")
        return []

    log.info(f"Cutting {len(approved)} clip(s)...")

    # --- Cut each clip ---
    cut_paths = []
    results   = []
    batch_dir = paths.CLIPS_DIR / safe_folder_name(vod_path.name)
    batch_dir.mkdir(parents=True, exist_ok=True)

    n_approved = max(1, len(approved))
    for i, highlight in enumerate(approved, start=1):
        clip_id     = generate_clip_name(highlight, i)
        output_path = batch_dir / f"{clip_id}.mp4"

        log.info(
            f"[{i}/{len(approved)}] Cutting: {clip_id} "
            f"({_seconds_to_timestamp(highlight['start'])} → "
            f"{_seconds_to_timestamp(highlight['end'])}, "
            f"{highlight['duration']:.0f}s, "
            f"score: {highlight['peak_score']:.3f})"
        )
        emit_progress(
            stage="cutting",
            percent=round((i - 1) / n_approved * 100, 1),
            processed=i - 1,
            total=len(approved),
            message=f"Cutting clip {i}/{len(approved)}: {clip_id}",
        )

        success = cut_clip(
            vod_path=vod_path,
            start=highlight["start"],
            end=highlight["end"],
            output_path=output_path,
        )

        result = {
            "clip_id":       clip_id,
            "output":        str(output_path) if success else None,
            "success":       success,
            "start":         highlight["start"],
            "end":           highlight["end"],
            "duration":      highlight["duration"],
            "score":         highlight["peak_score"],
            "quality_score": highlight.get("quality_score"),
            "final_score":   highlight.get("final_score", highlight["peak_score"]),
            "triggers":      highlight.get("triggers", []),
            "peak_text":     highlight.get("peak_text", ""),
            "peak_signals":  highlight.get("peak_signals", {}),
            "hazard_flags":  list(highlight.get("hazard_flags") or []),
        }
        results.append(result)

        if success:
            cut_paths.append(output_path)
            log.info(f"  ✓ Saved: {output_path.name}")
        else:
            log.error(f"  ✗ Failed: {clip_id}")

    # --- Save results metadata ---
    results_path = paths.METADATA_DIR / f"{vod_path.stem}_results.json"
    save_json({
        "vod":          vod_path.name,
        "total_cut":    len(cut_paths),
        "total_failed": len(approved) - len(cut_paths),
        "clips":        results,
    }, results_path)

    # --- Summary ---
    log.info("=" * 60)
    log.info("CUTTER COMPLETE")
    log.info(f"  Cut successfully: {len(cut_paths)}/{len(approved)}")
    log.info(f"  Clips saved to:   {batch_dir}")
    log.info(f"  Results saved:    {results_path.name}")
    log.info("=" * 60)

    if cut_paths:
        log.info("PIPELINE COMPLETE — review clips in output/clips/")
        log.info("Move good clips to data/old_clips/ to improve the profile.")
    log.info("=" * 60)

    return cut_paths


# =============================================================================
# HELPERS
# =============================================================================

def _seconds_to_timestamp(seconds: float) -> str:
    """Convert seconds to HH:MM:SS format."""
    s = int(seconds)
    h = s // 3600
    m = (s % 3600) // 60
    s = s % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


# =============================================================================
# STANDALONE ENTRY POINT
# =============================================================================
if __name__ == "__main__":
    import sys
    import json
    if len(sys.argv) < 3:
        print("Usage: python cutter.py <highlights.json> <vod_path>")
        sys.exit(1)
    with open(sys.argv[1]) as f:
        data = json.load(f)
    highlights = data.get("highlights", data)
    cut_clips(Path(sys.argv[2]), highlights)
