"""WebSocket endpoints for live log + job progress streaming."""

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend import log_bus
from backend.job_manager import jobs
from backend.durable_pipeline import durable_pipeline

log = logging.getLogger("backend.stream")
router = APIRouter(tags=["stream"])


@router.websocket("/stream/logs")
async def stream_logs(ws: WebSocket):
    await ws.accept()
    # Send the recent buffer first so the UI can hydrate fast.
    for line in log_bus.bus.recent(200):
        await ws.send_json(line.to_dict())

    q = log_bus.bus.subscribe()
    try:
        while True:
            try:
                line = await asyncio.wait_for(q.get(), timeout=30.0)
                await ws.send_json(line.to_dict())
            except asyncio.TimeoutError:
                # Heartbeat ping so client knows we're alive.
                await ws.send_json({"keepalive": True})
    except WebSocketDisconnect:
        pass
    finally:
        log_bus.bus.unsubscribe(q)


@router.websocket("/stream/job/{job_id}")
async def stream_job(ws: WebSocket, job_id: str):
    await ws.accept()
    job = jobs.get(job_id)
    if not job:
        durable = durable_pipeline.get(job_id)
        if not durable:
            await ws.send_json({"error": "no such job"})
            await ws.close()
            return
        await ws.send_json(durable)
        if durable["status"] in ("done", "failed", "cancelled"):
            await ws.close()
            return
        while True:
            await asyncio.sleep(1)
            durable = durable_pipeline.get(job_id)
            if not durable:
                break
            await ws.send_json(durable)
            if durable["status"] in ("done", "failed", "cancelled"):
                break
        await ws.close()
        return

    # Send current state immediately.
    await ws.send_json(job.to_dict())
    if job.status in ("done", "failed", "cancelled"):
        await ws.close()
        return

    q = jobs.subscribe(job_id)
    try:
        while True:
            try:
                payload = await asyncio.wait_for(q.get(), timeout=30.0)
                await ws.send_json(payload)
                if payload.get("status") in ("done", "failed", "cancelled"):
                    break
            except asyncio.TimeoutError:
                await ws.send_json({"keepalive": True, "job_id": job_id})
    except WebSocketDisconnect:
        pass
    finally:
        jobs.unsubscribe(job_id, q)
