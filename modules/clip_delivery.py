"""Deliver a rendered / edited clip to Discord so editors can actually grab it.

Public portfolio edition: the Cloudflare quick-tunnel fallback has been removed.
This module still measures file size against the Discord attachment limit and
routes small files through the configured gateway, but when a rendered clip is
too large to attach it simply logs a local notice instead of exposing a public
URL. All other delivery logic is unchanged.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("clip_delivery")

# Safely under Discord's 10 MiB non-boosted upload cap (Discord lowered it from
# 25 MiB; a 17MB attach on the real server came back 413 Payload Too Large).
# Boosted servers can raise this via INSTACLIP_DISCORD_ATTACH_MB.
DISCORD_ATTACH_LIMIT = int(float(
    __import__("os").environ.get("INSTACLIP_DISCORD_ATTACH_MB", "9.5")
) * 1024 * 1024)
# Kept for API compatibility; no longer used to keep a tunnel alive.
DEFAULT_LINK_TTL = 2 * 60 * 60


def _resolve_gateway(gateway=None):
    if gateway is not None:
        return gateway
    from modules.clip_room import clip_room
    return clip_room.gateway


def deliver_clip(
    path: str | Path,
    *,
    thread_id: Optional[str] = None,
    version_id: str = "",
    kind: str = "edit",
    title: str = "🎬 Edited clip ready",
    gateway=None,
    link_ttl: int = DEFAULT_LINK_TTL,
    url_provider: Optional[Any] = None,
) -> dict[str, Any]:
    """Post one rendered clip to Discord, choosing attach-vs-link by file size.

    Returns a small report describing how it was delivered. Never raises for a
    normal missing/oversize file — only genuinely unexpected gateway errors bubble.
    """
    gw = _resolve_gateway(gateway)
    p = Path(str(path))
    version_info = {"id": version_id, "path": str(p), "kind": kind}
    size = p.stat().st_size if p.is_file() else 0

    if size > DISCORD_ATTACH_LIMIT:
        log.info("file exceeds the attachment limit; tunnel delivery is not part of this public edition")
        # Keep the "too big" path from exposing any public URL. Fall through to
        # the normal gateway notification so the bot can still say "get it from
        # the app" without changing any other behavior.

    try:
        gw.post_render_result(thread_id, version_info)
    except Exception as exc:  # noqa: BLE001
        # Attach can fail even under our limit (Discord 413 on low-cap servers,
        # transient upload errors). NEVER lose the delivery — degrade to a
        # plain local notice; quick-tunnel links are not part of this edition.
        log.warning("attach delivery failed for %s (%s) — falling back to local notice", p.name, exc)
        gw.notify(f"{title}: **{p.name}** is rendered and ready in the InstaClip app "
                  "(too large to attach; public tunnel delivery is not included in this edition).")
        log.info("delivery-audit | mode=notice-fallback | file=%s | bytes=%d | thread=%s",
                 p.name, size, thread_id or "-")
        return {"delivered": "notice", "bytes": size, "error": str(exc)}

    delivered = "file" if 0 < size <= DISCORD_ATTACH_LIMIT else "notice"
    # Structured audit line (WS1): every outbound delivery is traceable —
    # what left the machine, how, and where it was headed (no URLs logged).
    log.info("delivery-audit | mode=%s | file=%s | bytes=%d | thread=%s",
             delivered, p.name, size, thread_id or "-")
    return {"delivered": delivered, "bytes": size}


__all__ = ["deliver_clip", "DISCORD_ATTACH_LIMIT", "DEFAULT_LINK_TTL"]
