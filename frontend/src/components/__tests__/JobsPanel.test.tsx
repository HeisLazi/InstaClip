import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { JobInfo } from "@/api/client";
import { JobCardView } from "@/components/JobsPanel";

function job(overrides: Partial<JobInfo> = {}): JobInfo {
  return {
    id: "job-1",
    kind: "pipeline",
    status: "running",
    progress: { stage: "transcribing", percent: 42 },
    result: null,
    error: null,
    started_at: 100,
    finished_at: 0,
    cancel_requested: false,
    ...overrides,
  };
}

function render(item: JobInfo, options: { requestingCancel?: boolean; cancelError?: string } = {}) {
  return renderToStaticMarkup(
    <JobCardView
      job={item}
      requestingCancel={options.requestingCancel}
      cancelError={options.cancelError}
      onCancel={() => undefined}
    />,
  );
}

describe("JobCardView", () => {
  it("renders an accessible running state and stop action", () => {
    const html = render(job());
    expect(html).toContain("Transcribing");
    expect(html).toContain('role="status"');
    expect(html).toContain("Running");
    expect(html).toContain('aria-label="Stop pipeline job"');
    expect(html).toContain('role="progressbar"');
    expect(html).toContain('aria-valuenow="42"');
  });

  it("announces stopping immediately and disables duplicate cancellation", () => {
    const html = render(job(), { requestingCancel: true });
    expect(html).toContain("Stopping at next safe checkpoint…");
    expect(html).toContain("Some media steps must finish before they can stop.");
    expect(html).toContain('aria-label="Stopping pipeline job"');
    expect(html).toContain("disabled");
  });

  it("renders a terminal stopped state without a cancel button", () => {
    const html = render(job({ status: "cancelled", cancel_requested: true, finished_at: 120 }));
    expect(html).toContain("Stopped");
    expect(html).toContain("Processing stopped safely.");
    expect(html).not.toContain('aria-label="Stop pipeline job"');
    expect(html).not.toContain('aria-label="Stopping pipeline job"');
  });

  it("announces cancellation failures", () => {
    const html = render(job(), { cancelError: "Backend unavailable" });
    expect(html).toContain('role="alert"');
    expect(html).toContain("Backend unavailable");
  });
});
