import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReportForm } from "@/app/reports/new/report-form";
import { mapServerFieldErrors, validateReportForm } from "@/lib/report-form";
import { ReportApiError } from "@/lib/reports-api";

const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/reports-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/reports-api")>();
  return { ...actual, createReport: vi.fn() };
});
const { createReport } = await import("@/lib/reports-api");
const createMock = vi.mocked(createReport);

const report = {
  id: "11111111-1111-4111-8111-111111111111",
  name: "Campaign performance",
  period: { start_date: "2026-01-01", end_date: "2026-01-31" },
  stage: "created",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  objectives: ["Understand lead quality"],
  current_source_id: null,
};

function fillValid() {
  fireEvent.change(screen.getByLabelText("Report name"), { target: { value: "  Campaign performance  " } });
  fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-01-01" } });
  fireEvent.change(screen.getByLabelText("End date"), { target: { value: "2026-01-31" } });
  fireEvent.change(screen.getByLabelText("Objective 1"), { target: { value: "  Understand lead quality  " } });
}

beforeEach(() => {
  push.mockReset();
  createMock.mockReset();
  vi.stubGlobal("crypto", { randomUUID: vi.fn()
    .mockReturnValueOnce("first-command-key")
    .mockReturnValueOnce("second-command-key") });
});

describe("report form validation", () => {
  it("accepts inclusive dates and trimmed boundary values", () => {
    const result = validateReportForm({
      name: ` ${"N".repeat(200)} `, startDate: "2026-02-28", endDate: "2026-02-28",
      objectives: Array.from({ length: 20 }, () => ` ${"O".repeat(2000)} `),
    });
    expect(result.errors).toEqual({});
    expect(result.command?.name).toHaveLength(200);
    expect(result.command?.objectives).toHaveLength(20);
  });

  it("blocks blank, oversized, malformed, and reversed values", () => {
    const result = validateReportForm({
      name: " ", startDate: "2026-02-30", endDate: "2026-02-01",
      objectives: [" ", "X".repeat(2001)],
    });
    expect(result.command).toBeNull();
    expect(result.errors).toMatchObject({ name: expect.any(String), startDate: expect.any(String),
      "objectives.0": expect.any(String), "objectives.1": expect.any(String) });
    expect(validateReportForm({ name: "Name", startDate: "2026-02-02", endDate: "2026-02-01", objectives: ["Goal"] }).errors.endDate).toMatch(/precede/);
    expect(validateReportForm({ name: "Name", startDate: "2026-01-01", endDate: "2026-01-01", objectives: [] }).errors.objectives).toMatch(/1 to 20/);
  });

  it("maps known server paths and retains unknown paths at form level", () => {
    expect(mapServerFieldErrors([
      { code: "invalid_field", message: "Choose another date.", path: ["period", "end_date"] },
      { code: "invalid_field", message: "Objective is invalid.", path: ["objectives", 0] },
      { code: "invalid_field", message: "Unknown field.", path: ["other"] },
    ])).toEqual({ errors: { endDate: "Choose another date.", "objectives.0": "Objective is invalid." }, formMessages: ["Unknown field."] });
  });
});

describe("report creation interaction", () => {
  it("shows labels, objective controls, and blocks invalid submissions with focus", async () => {
    render(<ReportForm />);
    expect(screen.getByLabelText("Report name")).toBeInTheDocument();
    expect(screen.getByLabelText("Start date")).toBeInTheDocument();
    expect(screen.getByLabelText("End date")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove objective 1" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Add objective" }));
    expect(screen.getByLabelText("Objective 2")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove objective 2" }));
    expect(screen.queryByLabelText("Objective 2")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Create report" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveFocus();
    expect(screen.getByLabelText("Report name")).toHaveAttribute("aria-invalid", "true");
    expect(createMock).not.toHaveBeenCalled();
  });

  it("blocks repeated clicks, reuses a key after uncertain failure, and routes on success", async () => {
    let reject!: (error: Error) => void;
    createMock.mockReturnValueOnce(new Promise((_, fail) => { reject = fail; }))
      .mockResolvedValueOnce(report);
    render(<ReportForm />);
    fillValid();
    fireEvent.click(screen.getByRole("button", { name: "Create report" }));
    expect(screen.getByRole("button", { name: "Creating report…" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Creating report…" }));
    expect(createMock).toHaveBeenCalledTimes(1);
    reject(new ReportApiError(0, "network_error", "Could not connect.", true));
    fireEvent.click(await screen.findByRole("button", { name: "Try creating again" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith(`/?created=${report.id}`));
    expect(createMock).toHaveBeenCalledTimes(2);
    expect(createMock.mock.calls[0][1]).toBe("first-command-key");
    expect(createMock.mock.calls[1][1]).toBe("first-command-key");
    expect(createMock.mock.calls[0][0]).toEqual({
      name: "Campaign performance", period: report.period,
      objectives: ["Understand lead quality"],
    });
  });

  it("rotates a key after a semantic edit and preserves entries on server 422", async () => {
    createMock.mockRejectedValueOnce(new ReportApiError(422, "validation_failed", "Invalid fields.", false,
      [{ code: "invalid_field", message: "Date needs correction.", path: ["period", "end_date"] }]))
      .mockRejectedValueOnce(new ReportApiError(503, "dependency_unavailable", "Try again later.", true));
    render(<ReportForm />);
    fillValid();
    fireEvent.click(screen.getByRole("button", { name: "Create report" }));
    expect(await screen.findByText("Date needs correction.")).toBeInTheDocument();
    expect(screen.getByLabelText("Report name")).toHaveValue("  Campaign performance  ");
    fireEvent.change(screen.getByLabelText("Objective 1"), { target: { value: "Different goal" } });
    fireEvent.click(screen.getByRole("button", { name: "Create report" }));
    await screen.findByText("Try again later.");
    expect(createMock.mock.calls.map((call) => call[1])).toEqual(["first-command-key", "second-command-key"]);
  });

  it("distinguishes authentication and idempotency conflicts", async () => {
    createMock.mockRejectedValueOnce(new ReportApiError(401, "unauthenticated", "Login needed.", false))
      .mockRejectedValueOnce(new ReportApiError(409, "idempotency_conflict", "Key conflict.", false));
    render(<ReportForm />);
    fillValid();
    fireEvent.click(screen.getByRole("button", { name: "Create report" }));
    expect(await screen.findByText("Authentication is required to create a report.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Create report" }));
    expect(await screen.findByText(/This command key was used/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Create report" }));
    expect(createMock).toHaveBeenCalledTimes(2);
  });
});
