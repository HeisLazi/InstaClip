"""Run a single VOD or kick off a batch."""

from fastapi import APIRouter, HTTPException
from pathlib import Path

from backend.job_manager import jobs
from backend.durable_pipeline import durable_pipeline
from backend.schemas import PipelineRunRequest, PipelineBatchRequest

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.post("/run")
def run_pipeline(req: PipelineRunRequest):
    raw = req.source.strip()
    # Windows' "Copy as path" wraps the result in double quotes; some shells
    # also leave single quotes. Strip whichever the user pasted in.
    src = raw.strip().strip('"').strip("'").strip()
    if not src:
        raise HTTPException(400, "source required")

    is_url = src.startswith("http://") or src.startswith("https://")
    if not is_url:
        p = Path(src)
        if not p.exists():
            # Be specific so the user can self-diagnose.
            parent_exists = p.parent.exists()
            siblings = []
            if parent_exists:
                try:
                    siblings = [c.name for c in p.parent.iterdir() if c.is_file()][:5]
                except PermissionError:
                    siblings = ["<permission denied listing parent>"]
            raise HTTPException(
                404,
                detail={
                    "error":         "file_not_found",
                    "received_raw":  raw,
                    "tried_path":    str(p),
                    "parent_exists": parent_exists,
                    "sample_files_in_parent": siblings,
                    "hint": (
                        "Backslashes are fine. If you copied from File Explorer "
                        "with 'Copy as path', the surrounding double quotes were "
                        "stripped automatically. Make sure the file is at exactly "
                        "the path above (case matters)."
                    ),
                },
            )
        if not p.is_file():
            raise HTTPException(400, f"not a file: {p}")

    job = durable_pipeline.submit(src, force=req.force)
    return {"job_id": job["id"], "source": src, "durable": True}


@router.post("/batch")
def run_batch(req: PipelineBatchRequest):
    if req.paths is None and (req.size < 1 or req.size > 50):
        raise HTTPException(400, "size must be 1-50")

    explicit_paths: list[Path] = []
    if req.paths:
        for raw in req.paths:
            p = Path(raw.strip().strip('"').strip("'"))
            if not p.exists():
                raise HTTPException(404, f"file not found: {p}")
            explicit_paths.append(p)
        if not explicit_paths:
            raise HTTPException(400, "paths was empty")

    def _do(handle):
        from config import paths as cfg_paths
        from main import run_pipeline
        from modules.fetcher.fetcher import list_local_vods
        from utils.progress_events import check_cancelled

        if explicit_paths:
            picked = explicit_paths
        else:
            vods = list_local_vods()
            if not vods:
                return {"error": "no local VODs found"}
            picked = []
            for v in vods:
                if not (cfg_paths.TRANSCRIPTS_DIR / (v.stem + ".json")).exists():
                    picked.append(v)
                if len(picked) >= req.size:
                    break
            if not picked:
                picked = vods[:req.size]

        total_clips, successes = 0, 0
        for i, vod in enumerate(picked, start=1):
            check_cancelled()
            handle.progress(stage="processing", current=i, total=len(picked),
                            vod=vod.name,
                            message=f"Batch {i}/{len(picked)}: {vod.name}")
            res = run_pipeline(source=str(vod), interactive=False)
            if res and res.get("success"):
                successes += 1
                total_clips += res.get("clips_cut", 0)
        return {"vods_done": successes, "clips_cut": total_clips,
                "total": len(picked)}

    job = jobs.submit("batch", _do)
    return {"job_id": job.id, "queued": len(explicit_paths) or req.size}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    ok = durable_pipeline.cancel(job_id) or jobs.cancel(job_id)
    if not ok:
        raise HTTPException(404, "no such job")
    return {"ok": True}


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    durable = durable_pipeline.get(job_id)
    if durable:
        return durable
    j = jobs.get(job_id)
    if not j:
        raise HTTPException(404, "no such job")
    return j.to_dict()


@router.get("/jobs")
def list_jobs():
    durable = durable_pipeline.list(50)
    durable_ids = {item["id"] for item in durable}
    runtime = [j.to_dict() for j in jobs.list_recent(50) if j.id not in durable_ids]
    return sorted(durable + runtime, key=lambda item: item.get("started_at", 0), reverse=True)[:50]


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: str):
    snapshot = durable_pipeline.retry(job_id)
    if snapshot is None:
        raise HTTPException(404, "no such durable job")
    if snapshot["status"] != "queued":
        raise HTTPException(409, f"job is {snapshot['status']}, not queued")
    return snapshot


@router.get("/local-vods")
def list_local_vods():
    """List candidate VODs from the configured local folder for the batch picker."""
    from config import cfg, paths
    from modules.fetcher.fetcher import list_local_vods as do_list
    vods = do_list()
    out = []
    for v in vods:
        stat = v.stat()
        transcript = paths.TRANSCRIPTS_DIR / (v.stem + ".json")
        out.append({
            "name":         v.name,
            "path":         str(v),
            "size_mb":      round(stat.st_size / (1024 * 1024), 1),
            "mtime":        stat.st_mtime,
            "transcribed":  transcript.exists(),
        })
    return {
        "folder":   str(cfg.fetcher.local_vod_dir),
        "vods":     out,
        "count":    len(out),
    }
