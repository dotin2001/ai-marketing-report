import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReportListing } from "@/app/report-listing";
import { ReportApiError, type ReportSummary } from "@/lib/reports-api";

vi.mock("@/lib/reports-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/reports-api")>();
  return { ...actual, listReports: vi.fn(), getReport: vi.fn() };
});

const { listReports, getReport } = await import("@/lib/reports-api");
const listMock = vi.mocked(listReports);
const detailMock = vi.mocked(getReport);

const report: ReportSummary = {
  id: "11111111-1111-4111-8111-111111111111",
  name: "Q1 acquisition",
  period: { start_date: "2026-01-01", end_date: "2026-03-31" },
  stage: "analysis_ready",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function page(data: ReportSummary[], cursor: string | null = null) {
  return { data, page: { limit: 25, has_more: cursor !== null, next_cursor: cursor } };
}

beforeEach(() => {
  listMock.mockReset();
  detailMock.mockReset();
});

describe("report listing", () => {
  it("shows loading, then server summary data and the creation route", async () => {
    let resolve!: (value: ReturnType<typeof page>) => void;
    listMock.mockReturnValue(new Promise((done) => { resolve = done; }));
    render(<ReportListing />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading reports");
    resolve(page([report]));
    expect(await screen.findByText("Q1 acquisition")).toBeInTheDocument();
    expect(screen.getByText("Jan 1, 2026 – Mar 31, 2026")).toBeInTheDocument();
    expect(screen.getByText("Ready for analysis")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New report" })).toHaveAttribute("href", "/reports/new");
  });

  it("shows an empty state only for a successful empty response", async () => {
    listMock.mockResolvedValue(page([]));
    render(<ReportListing />);
    expect(await screen.findByText("No reports yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create a report" })).toHaveAttribute("href", "/reports/new");
  });

  it("recovers from an initial failure", async () => {
    listMock.mockRejectedValueOnce(new ReportApiError(503, "dependency_unavailable", "Service unavailable.", true))
      .mockResolvedValueOnce(page([report]));
    render(<ReportListing />);
    expect(await screen.findByText("Service unavailable.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Q1 acquisition")).toBeInTheDocument();
  });

  it("shows authentication required without claiming the list is empty", async () => {
    listMock.mockRejectedValue(new ReportApiError(401, "unauthenticated", "Authentication required.", false));
    render(<ReportListing />);
    expect(await screen.findByText("Authentication required")).toBeInTheDocument();
    expect(screen.queryByText("No reports yet")).not.toBeInTheDocument();
  });

  it("appends cursor pages without duplicate cards and retains cards on later error", async () => {
    const second = { ...report, id: "22222222-2222-4222-8222-222222222222", name: "Q2 pipeline" };
    listMock.mockResolvedValueOnce(page([report], "opaque-cursor"))
      .mockRejectedValueOnce(new ReportApiError(503, "dependency_unavailable", "More unavailable.", true))
      .mockResolvedValueOnce(page([report, second]));
    render(<ReportListing />);
    await screen.findByText("Q1 acquisition");
    fireEvent.click(screen.getByRole("button", { name: "Load more reports" }));
    expect(await screen.findByText("More unavailable.")).toBeInTheDocument();
    expect(screen.getByText("Q1 acquisition")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry this page" }));
    expect(await screen.findByText("Q2 pipeline")).toBeInTheDocument();
    expect(screen.getAllByText("Q1 acquisition")).toHaveLength(1);
    expect(listMock).toHaveBeenNthCalledWith(2, "opaque-cursor");
  });

  it("restarts after an invalid cursor while keeping existing cards", async () => {
    listMock.mockResolvedValueOnce(page([report], "opaque"))
      .mockRejectedValueOnce(new ReportApiError(400, "invalid_cursor", "Expired cursor.", false))
      .mockResolvedValueOnce(page([report]));
    render(<ReportListing />);
    await screen.findByText("Q1 acquisition");
    fireEvent.click(screen.getByRole("button", { name: "Load more reports" }));
    expect(await screen.findByText("The report list changed while you were browsing.")).toBeInTheDocument();
    expect(screen.getByText("Q1 acquisition")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Start from first page" }));
    await waitFor(() => expect(listMock).toHaveBeenCalledTimes(3));
    expect(listMock).toHaveBeenNthCalledWith(3);
  });

  it("reauthorizes a created ID and shows an older replay outside the first page", async () => {
    const newer = { ...report, id: "33333333-3333-4333-8333-333333333333", name: "Newer report" };
    listMock.mockResolvedValue(page([newer]));
    detailMock.mockResolvedValue({ ...report, objectives: ["Growth"] });
    render(<ReportListing createdId={report.id} />);
    expect(await screen.findByText("Q1 acquisition")).toBeInTheDocument();
    expect(screen.getByText("Newer report")).toBeInTheDocument();
    expect(detailMock).toHaveBeenCalledWith(report.id);
  });

  it("ignores a missing created ID and reconciles a duplicate by ID", async () => {
    listMock.mockResolvedValue(page([report]));
    detailMock.mockRejectedValue(new ReportApiError(404, "resource_not_found", "Not found.", false));
    const first = render(<ReportListing createdId={report.id} />);
    expect(await screen.findByText("Q1 acquisition")).toBeInTheDocument();
    expect(screen.getAllByText("Q1 acquisition")).toHaveLength(1);
    first.unmount();
    detailMock.mockResolvedValue({ ...report, objectives: ["Growth"] });
    render(<ReportListing createdId={report.id} />);
    await waitFor(() => expect(detailMock).toHaveBeenCalledTimes(2));
    expect(screen.getAllByText("Q1 acquisition")).toHaveLength(1);
  });
});

