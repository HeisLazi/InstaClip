import { describe, expect, it } from "vitest";

import type { JobInfo } from "@/api/client";
import {
  jobPhase,
  nextStoppedExpiry,
  replaceJobSnapshot,
  selectVisibleJobs,
  STOPPED_RETENTION_SECONDS,
} from "@/components/jobsPanelModel";

function job(overrides: Partial<JobInfo> = {}): JobInfo {
  return {
    id: "job-1",
    kind: "pipeline",
    status: "running",
    progress: {},
    result: null,
    error: null,
    started_at: 100,
    finished_at: 0,
    cancel_requested: false,
    ...overrides,
  };
}

describe("jobPhase", () => {
  it("distinguishes running, stopping and stopped in that order", () => {
    expect(jobPhase(job())).toBe("running");
    expect(jobPhase(job({ cancel_requested: true }))).toBe("stopping");
    expect(jobPhase(job({ status: "cancelled", cancel_requested: true }))).toBe("stopped");
  });

  it("shows a local cancel request immediately while the API responds", () => {
    expect(jobPhase(job(), true)).toBe("stopping");
    expect(jobPhase(job({ status: "queued" }), true)).toBe("stopping");
  });
});

describe("selectVisibleJobs", () => {
  it("keeps active jobs and only recently stopped jobs, newest first", () => {
    const now = 1_000;
    const visible = selectVisibleJobs([
      job({ id: "done", status: "done", started_at: 500, finished_at: 900 }),
      job({ id: "old-stop", status: "cancelled", started_at: 400, finished_at: now - STOPPED_RETENTION_SECONDS - 1 }),
      job({ id: "recent-stop", status: "cancelled", started_at: 300, finished_at: now - 2 }),
      job({ id: "running", started_at: 800 }),
      job({ id: "queued", status: "queued", started_at: 900 }),
      job({ id: "stopping", cancel_requested: true, started_at: 850 }),
      job({ id: "failed", status: "failed", started_at: 950, finished_at: 999 }),
    ], now);

    expect(visible.map((item) => item.id)).toEqual(["queued", "stopping", "running", "recent-stop"]);
  });

  it("includes a stopped job at the retention boundary and removes it after", () => {
    const stopped = job({ status: "cancelled", finished_at: 100 });
    expect(selectVisibleJobs([stopped], 100 + STOPPED_RETENTION_SECONDS)).toHaveLength(1);
    expect(selectVisibleJobs([stopped], 100 + STOPPED_RETENTION_SECONDS + 0.001)).toHaveLength(0);
  });

  it("returns the next stopped-card expiry for a single precise wake-up", () => {
    const jobs = [
      job({ id: "first", status: "cancelled", finished_at: 100 }),
      job({ id: "second", status: "cancelled", finished_at: 104 }),
    ];
    expect(nextStoppedExpiry(jobs, 101)).toBe(100 + STOPPED_RETENTION_SECONDS);
    expect(nextStoppedExpiry(jobs, 200)).toBeNull();
  });
});

describe("replaceJobSnapshot", () => {
  it("replaces an existing websocket snapshot without duplicating the job", () => {
    const current = [job(), job({ id: "job-2" })];
    const next = job({ cancel_requested: true, progress: { cancel_requested: true } });
    const result = replaceJobSnapshot(current, next);
    expect(result).toHaveLength(2);
    expect(result[0]).toEqual(next);
  });
});
