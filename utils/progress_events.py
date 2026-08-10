"""
Tiny thread-local progress publisher used by the deep pipeline modules
(listener, clip_engine, cutter, etc.) to surface stage / percent updates
without taking a hard dependency on the FastAPI backend.

Wiring:
  backend.job_manager._run wraps each job and calls
      progress_events._set_publisher(handle.progress)
  before invoking the user function. Any module that calls
      progress_events.emit(stage="...", percent=12.3)
  while inside that thread routes through the JobHandle.

When no publisher is registered (CLI runs, Tkinter app) `emit` is a no-op,
so this is safe to call from anywhere.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Optional

log = logging.getLogger("progress_events")

_PublisherFn = Callable[..., None]
_CancelChecker = Callable[[], bool]
_local = threading.local()


class JobCancelled(Exception):
    """Raised when the user has requested cancellation of the running job."""


def _set_publisher(fn: Optional[_PublisherFn]) -> None:
    _local.publisher = fn


def _set_cancel_checker(fn: Optional[_CancelChecker]) -> None:
    _local.cancel_checker = fn


def _get_publisher() -> Optional[_PublisherFn]:
    return getattr(_local, "publisher", None)


def _get_cancel_checker() -> Optional[_CancelChecker]:
    return getattr(_local, "cancel_checker", None)


def check_cancelled() -> None:
    """
    Raises JobCancelled if the user has hit Cancel on this job.
    Modules call this at any safe interrupt point (between segments,
    between clips, between VODs in a batch, etc.).
    """
    checker = _get_cancel_checker()
    if checker and checker():
        raise JobCancelled("cancelled by user")


def emit(**fields: Any) -> None:
    """
    Publish a progress update from inside a module. Recognised keys:
      stage   (str)  — short human label, e.g. "transcribing"
      percent (float) — 0-100 overall progress of THIS stage
      detail  (dict / str) — anything else, free-form
      message (str)  — single-line status to show to the user
    Every emit also acts as a cancellation checkpoint.
    """
    # Raise immediately if cancelled, before publishing the new state.
    check_cancelled()
    pub = _get_publisher()
    if pub is None:
        return
    try:
        pub(**fields)
    except Exception as e:  # pragma: no cover — never crash the pipeline
        log.debug(f"progress emit failed: {e}")
