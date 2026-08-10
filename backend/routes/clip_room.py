"""Discord Clip Room endpoints (blueprint Phase 2).

The backend half of the desktop Clip Room viewer: read the workflow (candidates by
state, per-clip audit trail, review cards) and drive the lifecycle actions. Until
a Discord bot token is configured these actions are driven from the desktop app /
tests; the same service backs the bot interactions later.
"""

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/clip-room", tags=["clip-room"])


class ActorBody(BaseModel):
    actor: str = "lazi"


class EditBody(BaseModel):
    actor: str = "lazi"
    edit: dict


class ExtendBody(BaseModel):
    actor: str = "lazi"
    seconds: float


class CropBody(BaseModel):
    actor: str = "lazi"
    crop_box: list[float]


class RevisionBody(BaseModel):
    actor: str = "lazi"
    notes: str = ""


class RejectBody(BaseModel):
    actor: str = "lazi"
    reason: str = ""


class RenderDoneBody(BaseModel):
    actor: str = "worker"
    path: str
    kind: str = "edit"
    bucket: str = "edited"
    edit_plan: Optional[dict] = None


def _run(fn, *args, **kwargs):
    """Translate domain errors into HTTP status codes."""
    from db.state_machine import InvalidTransition
    from modules.clip_room import ClipRoomError, EditValidationError

    try:
        return fn(*args, **kwargs)
    except EditValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ClipRoomError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/states")
def states():
    """The state graph — for rendering the workflow in the UI."""
    from db.state_machine import TERMINAL_STATES, TRANSITIONS

    return {
        "transitions": {k: sorted(v) for k, v in TRANSITIONS.items()},
        "terminal": sorted(TERMINAL_STATES),
    }


@router.get("/candidates")
def candidates(
    state: Optional[str] = None,
    states: Optional[str] = None,
    q: str = "",
    vod_id: Optional[str] = None,
    min_score: Optional[float] = None,
    max_score: Optional[float] = None,
    min_duration: Optional[float] = None,
    max_duration: Optional[float] = None,
    claimed_by: Optional[str] = None,
    hazard: Optional[bool] = None,
    render_status: str = "any",
    tag: Optional[str] = None,
    sort: str = "score_desc",
    cursor: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
):
    from modules.clip_room import clip_room
    selected_states = [item for item in (states or state or "").split(",") if item]
    return _run(
        clip_room.query_candidates,
        states=selected_states,
        q=q,
        vod_id=vod_id,
        min_score=min_score,
        max_score=max_score,
        min_duration=min_duration,
        max_duration=max_duration,
        claimed_by=claimed_by,
        hazard=hazard,
        render_status=render_status,
        tag=tag,
        sort=sort,
        cursor=cursor,
        limit=limit,
    )


@router.get("/candidates/{candidate_id}/card")
def card(candidate_id: str):
    from modules.clip_room import clip_room
    return {"card": _run(clip_room.prepare_card, candidate_id)}


@router.get("/candidates/{candidate_id}/audit")
def audit(candidate_id: str):
    from modules.clip_room import clip_room
    return {"audit": clip_room.audit_trail(candidate_id)}


@router.get("/candidates/{candidate_id}/judgement")
def judgement(candidate_id: str):
    """Taste verdict is an optional cloud-extension in the public edition."""
    raise HTTPException(status_code=501, detail="Director judgement is not available in the public edition.")


@router.get("/candidates/{candidate_id}/preview")
def preview(candidate_id: str):
    """On-demand preview video for a candidate (handles metadata-only records that
    have no cut file yet). Serves an existing render, a cached preview, or cuts a
    short downscaled one from the source VOD. 404 if the source is unavailable."""
    from fastapi.responses import FileResponse
    from modules import clip_preview

    path, status = clip_preview.get_or_make_preview(candidate_id)
    if path is None:
        code = 404 if status in (clip_preview.NO_CANDIDATE, clip_preview.NO_SOURCE) else 500
        raise HTTPException(status_code=code, detail=f"no preview available ({status})")
    # FileResponse honours Range requests, so the player can seek.
    return FileResponse(path, media_type="video/mp4", headers={"X-Preview-Source": status})


@router.post("/candidates/{candidate_id}/promote")
def promote(candidate_id: str, body: ActorBody):
    from modules.clip_room import clip_room
    return {"candidate": _run(clip_room.promote, candidate_id, actor=body.actor)}


@router.post("/candidates/{candidate_id}/claim")
def claim(candidate_id: str, body: ActorBody):
    from modules.clip_room import clip_room
    return {"candidate": _run(clip_room.claim, candidate_id, actor=body.actor)}


@router.post("/candidates/{candidate_id}/request-raw")
def request_raw(candidate_id: str, body: ActorBody):
    from modules.clip_room import clip_room
    return {"candidate": _run(clip_room.request_raw, candidate_id, actor=body.actor)}


@router.post("/candidates/{candidate_id}/request-edit")
def request_edit(candidate_id: str, body: EditBody):
    from modules.clip_room import clip_room
    return {"candidate": _run(clip_room.request_edit, candidate_id, body.edit, actor=body.actor)}


@router.post("/candidates/{candidate_id}/extend-before")
def extend_before(candidate_id: str, body: ExtendBody):
    from modules.clip_room import clip_room
    return {"candidate": _run(clip_room.extend_before, candidate_id, body.seconds, actor=body.actor)}


@router.post("/candidates/{candidate_id}/extend-after")
def extend_after(candidate_id: str, body: ExtendBody):
    from modules.clip_room import clip_room
    return {"candidate": _run(clip_room.extend_after, candidate_id, body.seconds, actor=body.actor)}


@router.post("/candidates/{candidate_id}/different-crop")
def different_crop(candidate_id: str, body: CropBody):
    from modules.clip_room import clip_room
    return {"candidate": _run(clip_room.different_crop, candidate_id, body.crop_box, actor=body.actor)}


@router.post("/candidates/{candidate_id}/start-render")
def start_render(candidate_id: str, body: ActorBody):
    from modules.clip_room import clip_room
    return {"candidate": _run(clip_room.start_render, candidate_id, actor=body.actor)}


@router.post("/candidates/{candidate_id}/complete-render")
def complete_render(candidate_id: str, body: RenderDoneBody):
    from modules.clip_room import clip_room
    return {"candidate": _run(
        clip_room.complete_render, candidate_id,
        path=body.path, kind=body.kind, bucket=body.bucket,
        edit_plan=body.edit_plan, actor=body.actor,
    )}


@router.post("/candidates/{candidate_id}/render")
def render(candidate_id: str, body: ActorBody):
    """Kick off the render in the background (ffmpeg can take a while) and return
    a job id to poll. The durable job_store records the render itself; this
    in-memory job is just for live progress / responsiveness."""
    from db.state_machine import ClipState
    from backend.job_manager import jobs
    from modules.clip_room import clip_room
    from modules.render_worker import render_worker

    snap = clip_room.get(candidate_id)
    if snap is None:
        raise HTTPException(status_code=404, detail=f"candidate {candidate_id} not found")
    if snap["state"] not in (ClipState.RAW_REQUESTED, ClipState.EDIT_REQUESTED):
        raise HTTPException(status_code=409, detail=f"candidate is {snap['state']}, not awaiting render")

    job = jobs.submit("render_clip", lambda handle: render_worker.render_candidate(candidate_id, actor=body.actor))
    return {"job_id": job.id, "status": job.status}


@router.post("/candidates/{candidate_id}/approve")
def approve(candidate_id: str, body: ActorBody):
    from modules.clip_room import clip_room
    return {"candidate": _run(clip_room.approve, candidate_id, actor=body.actor)}


@router.post("/candidates/{candidate_id}/request-revision")
def request_revision(candidate_id: str, body: RevisionBody):
    from modules.clip_room import clip_room
    return {"candidate": _run(clip_room.request_revision, candidate_id, body.notes, actor=body.actor)}


@router.post("/candidates/{candidate_id}/reject")
def reject(candidate_id: str, body: RejectBody):
    from modules.clip_room import clip_room
    return {"candidate": _run(clip_room.reject, candidate_id, actor=body.actor, reason=body.reason)}


@router.get("/candidates/{candidate_id}/verdict")
def verdict(candidate_id: str):
    """The Director's latest LLM taste verdict for a candidate (fit/verdict/why),
    or null if none has been recorded yet."""
    raise HTTPException(status_code=501, detail="Director verdict is not available in the public edition.")
