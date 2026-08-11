import type { JobInfo } from "@/api/client";

export const STOPPED_RETENTION_SECONDS = 8;

export type JobPhase = "queued" | "running" | "stopping" | "stopped" | "finished";

export function jobPhase(job: Pick<JobInfo, "status" | "cancel_requested">, requestingCancel = false): JobPhase {
  if (job.status === "cancelled") return "stopped";
  if ((job.status === "queued" || job.status === "running") && (job.cancel_requested || requestingCancel)) {
    return "stopping";
  }
  if (job.status === "queued") return "queued";
  if (job.status === "running") return "running";
  return "finished";
}

export function selectVisibleJobs(
  jobs: JobInfo[],
  nowSeconds: number,
  stoppedRetentionSeconds = STOPPED_RETENTION_SECONDS,
): JobInfo[] {
  return jobs
    .filter((job) => {
      const phase = jobPhase(job);
      if (phase === "queued" || phase === "running" || phase === "stopping") return true;
      if (phase !== "stopped" || !job.finished_at) return false;
      return job.finished_at + stoppedRetentionSeconds >= nowSeconds;
    })
    .sort((left, right) => right.started_at - left.started_at);
}

export function nextStoppedExpiry(
  jobs: JobInfo[],
  nowSeconds: number,
  stoppedRetentionSeconds = STOPPED_RETENTION_SECONDS,
): number | null {
  const expiries = jobs
    .filter((job) => job.status === "cancelled" && job.finished_at > 0)
    .map((job) => job.finished_at + stoppedRetentionSeconds)
    .filter((expiry) => expiry >= nowSeconds)
    .sort((left, right) => left - right);
  return expiries[0] ?? null;
}

export function replaceJobSnapshot(jobs: JobInfo[] | undefined, snapshot: JobInfo): JobInfo[] {
  if (!jobs) return [snapshot];
  const found = jobs.some((job) => job.id === snapshot.id);
  if (!found) return [snapshot, ...jobs];
  return jobs.map((job) => job.id === snapshot.id ? snapshot : job);
}
