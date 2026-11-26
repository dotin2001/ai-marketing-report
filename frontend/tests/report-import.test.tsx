import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ImportPage } from "@/app/reports/[reportId]/import/report-import";
import { ReportApiError } from "@/lib/reports-api";

vi.mock("@/lib/reports-api", async (original) => ({
  ...await original<typeof import("@/lib/reports-api")>(), getReport: vi.fn(),
}));
vi.mock("@/lib/sources-api", async (original) => ({
  ...await original<typeof import("@/lib/sources-api")>(),
  getSource: vi.fn(), getSourcePreview: vi.fn(), attachCsv: vi.fn(), attachText: vi.fn(),
}));
const { getReport } = await import("@/lib/reports-api");
const { getSource, getSourcePreview, attachCsv, attachText } = await import("@/lib/sources-api");
const reportMock = vi.mocked(getReport);
const sourceMock = vi.mocked(getSource);
const previewMock = vi.mocked(getSourcePreview);
const csvMock = vi.mocked(attachCsv);
const textMock = vi.mocked(attachText);

const reportId = "22222222-2222-4222-8222-222222222222";
const sourceId = "11111111-1111-4111-8111-111111111111";
const report = {
  id: reportId, name: "Import report", period: { start_date: "2026-01-01", end_date: "2026-01-31" },
  stage: "created", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
  objectives: ["Growth"], current_source_id: null,
};
const source = {
  id: sourceId, report_id: reportId, source_type: "csv" as const, byte_size: 12,
  checksum_sha256: "a".repeat(64), media_type: "text/csv", encoding: "utf-8",
  display_filename: "safe.csv", created_at: "2026-01-01T00:00:00Z",
};
const preview = {
  source_type: "csv" as const, confirmed: false as const, validation_status: "unvalidated" as const,
  columns: [{ ordinal: 0, original_header: "repeat" }, { ordinal: 1, original_header: "repeat" }],
  rows: [{ record_index: 1, values: ["<script>alert(1)</script>", "=HYPERLINK(1)"] }],
  total_records: 4, excerpt: null, truncated: true,
};

beforeEach(() => {
  reportMock.mockReset().mockResolvedValue(report);
  sourceMock.mockReset().mockResolvedValue(source);
  previewMock.mockReset().mockResolvedValue(preview);
  csvMock.mockReset(); textMock.mockReset();
  let index = 0;
  vi.stubGlobal("crypto", { randomUUID: () => `command-${++index}` });
});

describe("report import page", () => {
  it("links through report identity and distinguishes loading, auth, missing, and service failure", async () => {
    let resolve!: (value: typeof report) => void;
    reportMock.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    const first = render(<ImportPage reportId={reportId} />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading report");
    resolve(report);
    expect(await screen.findByRole("heading", { name: "Import report" })).toBeInTheDocument();
    first.unmount();
    reportMock.mockRejectedValueOnce(new ReportApiError(401, "unauthenticated", "Authentication is required.", false));
    const second = render(<ImportPage reportId={reportId} />);
    expect(await screen.findByText("Authentication required")).toBeInTheDocument();
    second.unmount();
    reportMock.mockRejectedValueOnce(new ReportApiError(404, "resource_not_found", "Not found.", false));
    const third = render(<ImportPage reportId={reportId} />);
    expect(await screen.findByText("Report unavailable")).toBeInTheDocument();
    third.unmount();
    reportMock.mockRejectedValueOnce(new ReportApiError(503, "request_failed", "Service unavailable.", true));
    render(<ImportPage reportId={reportId} />);
    expect(await screen.findByText("Report could not be loaded")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Import report" })).toBeInTheDocument();
  });

  it("recovers current source, renders duplicate headers and inert bounded data", async () => {
    reportMock.mockResolvedValue({ ...report, current_source_id: sourceId });
    render(<ImportPage reportId={reportId} />);
    expect(await screen.findByText("safe.csv")).toBeInTheDocument();
    expect(await screen.findByText("Only a bounded sample is shown.", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("Column 0")).toBeInTheDocument();
    expect(screen.getByText("Column 1")).toBeInTheDocument();
    expect(screen.getAllByText("repeat")).toHaveLength(2);
    expect(screen.getByText("<script>alert(1)</script>")).toBeInTheDocument();
    expect(document.querySelector("script")).toBeNull();
    expect(screen.getByText("=HYPERLINK(1)")).toBeInTheDocument();
    expect(screen.getByText("Unvalidated source · Not confirmed")).toBeInTheDocument();
    expect(sourceMock).toHaveBeenCalledWith(reportId, sourceId);
  });

  it("keeps a header-only CSV preview readable", async () => {
    reportMock.mockResolvedValue({ ...report, current_source_id: sourceId });
    previewMock.mockResolvedValue({ ...preview, rows: [], total_records: 0, truncated: false });
    render(<ImportPage reportId={reportId} />);
    expect(await screen.findByText("0 source records · 0 preview rows")).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
  });

  it("preserves selection after failure, reuses key on retry, and loads accepted preview", async () => {
    csvMock.mockRejectedValueOnce(new ReportApiError(0, "network_error", "Could not connect.", true)).mockResolvedValue(source);
    render(<ImportPage reportId={reportId} />);
    await screen.findByRole("heading", { name: "Import report" });
    const file = new File(["date,clicks\n2026-01-01,3"], "input.csv", { type: "text/csv" });
    fireEvent.change(screen.getByLabelText("CSV file"), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "Attach CSV" }));
    expect(await screen.findByText("Correct the input or retry the same submission.")).toBeInTheDocument();
    expect(screen.getByText(/Selected: input.csv/)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "Retry attachment" }));
    expect(await screen.findByText("safe.csv")).toBeInTheDocument();
    await waitFor(() => expect(previewMock).toHaveBeenCalledWith(reportId, sourceId));
    expect(csvMock.mock.calls[0][2]).toBe(csvMock.mock.calls[1][2]);
    expect(csvMock.mock.calls[0][1]).toBe(file);
  });

  it("blocks bad local files, rotates identity on new selection, and shows measured upload", async () => {
    let resolve!: (value: typeof source) => void;
    csvMock.mockImplementationOnce((_reportId, _file, _key, onUpdate) => {
      onUpdate({ kind: "uploading", loaded: 4, total: 8 });
      return new Promise((done) => { resolve = done; });
    }).mockResolvedValue(source);
    render(<ImportPage reportId={reportId} />);
    await screen.findByRole("heading", { name: "Import report" });
    fireEvent.change(screen.getByLabelText("CSV file"), { target: { files: [new File([], "empty.csv", { type: "text/csv" })] } });
    fireEvent.click(screen.getByRole("button", { name: "Attach CSV" }));
    expect(await screen.findByText("The selected file is empty.")).toBeInTheDocument();
    expect(csvMock).not.toHaveBeenCalled();
    const file = new File(["a,b"], "good.csv", { type: "text/csv" });
    fireEvent.change(screen.getByLabelText("CSV file"), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "Attach CSV" }));
    expect(await screen.findByText("Uploading CSV: 50%")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("value", "50");
    expect(screen.getByRole("button", { name: "Submitting…" })).toBeDisabled();
    resolve(source);
    expect(await screen.findByText("safe.csv")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("CSV file"), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "Attach CSV" }));
    await waitFor(() => expect(csvMock).toHaveBeenCalledTimes(2));
    expect(csvMock.mock.calls[0][2]).not.toBe(csvMock.mock.calls[1][2]);
  });

  it("submits exact Unicode text, preserves it on error, and renders inert excerpt", async () => {
    const textSource = { ...source, source_type: "text" as const, display_filename: null };
    textMock.mockRejectedValueOnce(new ReportApiError(503, "storage_unavailable", "Try again.", true)).mockResolvedValue(textSource);
    sourceMock.mockResolvedValue(textSource);
    previewMock.mockResolvedValue({ source_type: "text", confirmed: false, validation_status: "unvalidated", columns: null, rows: null, total_records: null, excerpt: "<b>claim</b>\n=SUM(1)", truncated: false });
    render(<ImportPage reportId={reportId} />);
    await screen.findByRole("heading", { name: "Import report" });
    fireEvent.click(screen.getByRole("button", { name: "Paste content" }));
    const textbox = screen.getByLabelText("Pasted content");
    fireEvent.change(textbox, { target: { value: "💡\nRaw claim" } });
    expect(screen.getByText(/14 of 1,048,576 bytes/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Attach pasted content" }));
    await screen.findByText("Correct the input or retry the same submission.");
    expect(textbox).toHaveValue("💡\nRaw claim");
    fireEvent.click(screen.getByRole("button", { name: "Retry attachment" }));
    expect(await screen.findByText("<b>claim</b>", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("=SUM(1)", { exact: false })).toBeInTheDocument();
    expect(textMock.mock.calls[0][1]).toBe("💡\nRaw claim");
    expect(textMock.mock.calls[0][2]).toBe(textMock.mock.calls[1][2]);
  });

  it("keeps accepted source when preview fails and retries only preview", async () => {
    csvMock.mockResolvedValue(source);
    previewMock.mockRejectedValueOnce(new Error("temporary")).mockResolvedValue(preview);
    render(<ImportPage reportId={reportId} />);
    await screen.findByRole("heading", { name: "Import report" });
    fireEvent.change(screen.getByLabelText("CSV file"), { target: { files: [new File(["a,b"], "good.csv", { type: "text/csv" })] } });
    fireEvent.click(screen.getByRole("button", { name: "Attach CSV" }));
    expect(await screen.findByText("Preview could not be loaded. The source remains attached.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry preview" }));
    expect(await screen.findByText("Only a bounded sample is shown.", { exact: false })).toBeInTheDocument();
    expect(csvMock).toHaveBeenCalledTimes(1);
  });

  it("rotates a pasted command after edits and requires correction after key conflict", async () => {
    textMock.mockRejectedValueOnce(new ReportApiError(409, "idempotency_conflict", "Conflict.", false))
      .mockResolvedValue({ ...source, source_type: "text", display_filename: null });
    sourceMock.mockResolvedValue({ ...source, source_type: "text", display_filename: null });
    previewMock.mockResolvedValue({ source_type: "text", confirmed: false, validation_status: "unvalidated", columns: null, rows: null, total_records: null, excerpt: "revised", truncated: false });
    render(<ImportPage reportId={reportId} />);
    await screen.findByRole("heading", { name: "Import report" });
    fireEvent.click(screen.getByRole("button", { name: "Paste content" }));
    const textbox = screen.getByLabelText("Pasted content");
    fireEvent.change(textbox, { target: { value: "first" } });
    fireEvent.click(screen.getByRole("button", { name: "Attach pasted content" }));
    expect(await screen.findByText("Conflict.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Attach pasted content" })).toBeDisabled();
    fireEvent.change(textbox, { target: { value: "revised" } });
    fireEvent.click(screen.getByRole("button", { name: "Attach pasted content" }));
    expect(await screen.findByText("revised")).toBeInTheDocument();
    expect(textMock.mock.calls[0][2]).not.toBe(textMock.mock.calls[1][2]);
  });

  it("announces indeterminate upload and processing without claiming success early", async () => {
    let resolve!: (value: typeof source) => void;
    csvMock.mockImplementation((_reportId, _file, _key, onUpdate) => {
      onUpdate({ kind: "uploading", loaded: null, total: null });
      return new Promise((done) => { resolve = done; });
    });
    render(<ImportPage reportId={reportId} />);
    await screen.findByRole("heading", { name: "Import report" });
    fireEvent.change(screen.getByLabelText("CSV file"), { target: { files: [new File(["a,b"], "good.csv", { type: "text/csv" })] } });
    fireEvent.click(screen.getByRole("button", { name: "Attach CSV" }));
    expect(await screen.findByText(/Progress unavailable/)).toBeInTheDocument();
    expect(screen.queryByText("safe.csv")).not.toBeInTheDocument();
    const onUpdate = csvMock.mock.calls[0][3];
    onUpdate({ kind: "processing" });
    expect(await screen.findByText(/Waiting for server acceptance/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Submitting…" }));
    expect(csvMock).toHaveBeenCalledTimes(1);
    resolve(source);
    expect(await screen.findByText("safe.csv")).toBeInTheDocument();
  });
});
