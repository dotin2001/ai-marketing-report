import { afterEach, describe, expect, it, vi } from "vitest";

import { createReport, getReport, listReports, ReportApiError } from "@/lib/reports-api";

const summary = {
  id: "9bc2cebd-523a-4a59-b647-9a686ab489d4",
  name: "Quarterly report",
  period: { start_date: "2026-01-01", end_date: "2026-01-31" },
  stage: "created",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("report API boundary", () => {
  it("requests an opaque cursor with browser credentials and parses the page", async () => {
    const fetcher = vi.fn().mockResolvedValue(json({
      data: [summary],
      page: { limit: 25, has_more: true, next_cursor: "opaque+/cursor" },
    }));
    vi.stubGlobal("fetch", fetcher);

    const page = await listReports("opaque+/cursor");

    expect(page.data[0].name).toBe("Quarterly report");
    expect(page.page.next_cursor).toBe("opaque+/cursor");
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/reports?limit=25&cursor=opaque%2B%2Fcursor",
      expect.objectContaining({ credentials: "same-origin", cache: "no-store" }),
    );
  });

  it("sends the creation key and keeps the report detail typed", async () => {
    const fetcher = vi.fn().mockImplementation(async () =>
      json({ data: { ...summary, objectives: ["Growth"] } }, 201));
    vi.stubGlobal("fetch", fetcher);

    const command = {
      name: "Quarterly report",
      period: summary.period,
      objectives: ["Growth"],
    };
    expect((await createReport(command, "command-123")).id).toBe(summary.id);
    expect(fetcher).toHaveBeenCalledWith("/api/v1/reports", expect.objectContaining({
      method: "POST",
      headers: expect.objectContaining({ "Idempotency-Key": "command-123" }),
      body: JSON.stringify(command),
    }));
    expect((await getReport(summary.id)).objectives).toEqual(["Growth"]);
  });

  it("keeps authentication separate from an empty collection", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({
      error: { code: "unauthenticated", message: "Authentication is required.", retryable: false },
    }, 401)));
    await expect(listReports()).rejects.toMatchObject({ status: 401, code: "unauthenticated" });
  });

  it("retains safe 422 field paths", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ error: {
      code: "validation_failed", message: "Invalid fields.", retryable: false,
      details: [{ code: "invalid_period", message: "End date is too early.", path: ["period", "end_date"] }],
    } }, 422)));
    const command = { name: "Report", period: summary.period, objectives: ["Growth"] };
    await expect(createReport(command, "key")).rejects.toMatchObject({
      status: 422, code: "validation_failed",
      details: [{ path: ["period", "end_date"] }],
    });
  });

  it("normalizes a network or malformed success response without provider text", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("provider-secret")));
    await expect(listReports()).rejects.toMatchObject({
      code: "network_error", message: "Could not connect to the report service.",
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ data: [], page: {} })));
    await expect(listReports()).rejects.toBeInstanceOf(ReportApiError);
  });
});
