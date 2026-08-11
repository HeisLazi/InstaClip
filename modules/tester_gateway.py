"""Optional authenticated bridge from the local clipper to a cloud judge gateway.

The public edition is local-first. The gateway is disabled unless the user sets
CLIPPER_GATEWAY_URL explicitly; when disabled, all functions degrade gracefully
so the app never crashes.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any

import requests

from config import paths
from modules.clip_judge import _complete_candidate_end
from utils.file_utils import save_json

log = logging.getLogger("tester_gateway")
_lock = threading.RLock()
_session: dict[str, str] = {}


def _configured_gateway_url() -> str:
    """Read the gateway base URL from the environment. No hardcoded hostname."""
    return (os.environ.get("CLIPPER_GATEWAY_URL") or "").strip().rstrip("/")


def attach_session(*, gateway_url: str, access_token: str, refresh_token: str, user_id: str) -> None:
    url = gateway_url.strip().rstrip("/")
    if not (url.startswith("https://") or url.startswith("http://127.0.0.1") or url.startswith("http://localhost")):
        raise ValueError("gateway URL must use HTTPS")
    if not access_token or not refresh_token or not user_id:
        raise ValueError("access token, refresh token, and user id are required")
    with _lock:
        _session.clear()
        _session.update({"gateway_url": url, "access_token": access_token, "refresh_token": refresh_token, "user_id": user_id})


def clear_session() -> None:
    with _lock:
        _session.clear()


def status() -> dict[str, Any]:
    with _lock:
        return {
            "attached": bool(_session),
            "user_id": _session.get("user_id", ""),
            "configured": bool(_configured_gateway_url()),
        }


def _snapshot() -> dict[str, str]:
    configured = _configured_gateway_url()
    with _lock:
        if not _session:
            raise RuntimeError("Sign in to the Clipper Beta before starting AI selection.")
        snapshot = dict(_session)
    # If the environment is no longer set, do not use a stale hardcoded URL.
    if configured and snapshot.get("gateway_url") != configured:
        snapshot["gateway_url"] = configured
    return snapshot


def _refresh(session: dict[str, str]) -> dict[str, str]:
    response = requests.post(
        session["gateway_url"] + "/auth/refresh",
        json={"refresh_token": session["refresh_token"]},
        timeout=30,
    )
    if not response.ok:
        raise RuntimeError("Tester session expired. Sign in again before resuming this job.")
    payload = response.json()
    with _lock:
        _session["access_token"] = str(payload["access_token"])
        _session["refresh_token"] = str(payload["refresh_token"])
        return dict(_session)


def _taste_text(user_id: str) -> str:
    from modules.tester_profile import load_profile, PRESETS

    profile = load_profile(user_id)
    preset = PRESETS.get(str(profile.get("preset") or "general"), PRESETS["general"])
    traits = ", ".join(str(item) for item in profile.get("traits") or [])
    duration = profile.get("preferred_duration") or [15, 60]
    examples = "\n".join(
        f"- {item.get('label', 'good')}: {item.get('reason', '')}"
        for item in profile.get("examples") or [] if item.get("reason")
    )
    return (
        f"Base style: {preset['description']}\n"
        f"Confirmed traits: {traits or 'complete setup and payoff'}\n"
        f"Preferred duration: {duration[0]}-{duration[1]} seconds\n"
        f"Creator notes: {profile.get('notes') or 'none'}\n"
        f"Confirmed examples:\n{examples or 'none'}"
    )


def select_highlights(transcript: dict[str, Any], vod_path: Path) -> list[dict[str, Any]]:
    if not _configured_gateway_url():
        log.warning("CLIPPER_GATEWAY_URL not set; cloud judge selection is unavailable.")
        return []
    try:
        session = _snapshot()
    except RuntimeError as exc:
        log.warning("%s", exc)
        return []
    segments = transcript.get("segments") or []
    lines = [
        f"[{float(item.get('start') or 0):.3f}-{float(item.get('end') or 0):.3f}] {item.get('text', '')}"
        for item in segments
    ]
    payload = {"transcript_chunks": ["\n".join(lines)], "taste_profile": _taste_text(session["user_id"])}

    def send(current: dict[str, str]):
        return requests.post(
            current["gateway_url"] + "/judge/clips",
            headers={"Authorization": f"Bearer {current['access_token']}"},
            json=payload,
            timeout=180,
        )

    response = send(session)
    if response.status_code == 401:
        session = _refresh(session)
        response = send(session)
    if not response.ok:
        try:
            detail = response.json().get("error") or response.text
        except Exception:
            detail = response.text
        raise RuntimeError(f"Clipper AI gateway rejected selection: {detail}")
    candidates = (response.json().get("result") or {}).get("candidates") or []
    transcript_end = max((float(item.get("end") or 0) for item in segments), default=0.0)
    highlights: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        try:
            selected_start = max(0.0, float(candidate.get("start") or 0))
            selected_end = min(transcript_end, float(candidate.get("end") or 0))
            score = max(0.0, min(1.0, float(candidate.get("score") or 0)))
        except (TypeError, ValueError):
            continue
        if selected_end <= selected_start:
            continue
        start = max(0.0, selected_start - 2.0)
        padded_end = min(transcript_end, selected_end + 4.0)
        end, completion_reason = _complete_candidate_end(padded_end, segments, transcript_end)
        highlights.append({
            "clip_id": f"{vod_path.stem}_{index + 1:03d}",
            "vod_name": vod_path.name,
            "start": round(start, 3), "end": round(end, 3), "duration": round(end - start, 3),
            "peak_time": round(selected_start, 3), "peak_score": score,
            "final_score": score, "quality_score": score,
            "peak_text": str(candidate.get("hook") or candidate.get("why") or ""),
            "why": str(candidate.get("why") or ""),
            "clip_type": "tester_personalized", "kind": "setup_payoff",
            "compilation": False, "needs_context": False,
            "triggers": ["tester_gateway"],
            "hazard_flags": list(candidate.get("risks") or []),
            "peak_signals": {},
            "judge_window": {"start": selected_start, "end": selected_end},
            "boundary_handles": {
                "pre_seconds": 2.0,
                "post_seconds": 4.0,
                "completion_extension_seconds": round(max(0.0, end - padded_end), 3),
                "completion_reason": completion_reason,
            },
        })
    highlights.sort(key=lambda item: item["final_score"], reverse=True)
    save_json(
        {"vod": vod_path.name, "engine": "tester_gateway", "highlights": highlights},
        paths.METADATA_DIR / f"{vod_path.stem}_highlights.json",
    )
    log.info("Tester gateway selected %d candidate(s) without local API keys", len(highlights))
    return highlights
