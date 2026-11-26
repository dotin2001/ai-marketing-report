/** Typed, same-origin boundary for the report-management API. */
import { record, request, ReportApiError } from "@/lib/api-client";

export { ReportApiError } from "@/lib/api-client";
export type { ApiFieldDetail } from "@/lib/api-client";

export type ReportStage =
  | "created"
  | "source_review"
  | "analysis_ready"
  | "analysis_pending"
  | "reviewing"
  | "versioned";

export interface ReportSummary {
  id: string;
  name: string;
  period: { start_date: string; end_date: string };
  stage: ReportStage | (string & {});
  created_at: string;
  updated_at: string;
}

export interface ReportDetail extends ReportSummary {
  objectives: string[];
  current_source_id: string | null;
}

export interface PageInfo {
  limit: number;
  has_more: boolean;
  next_cursor: string | null;
}

export interface ReportPage {
  data: ReportSummary[];
  page: PageInfo;
}

export interface CreateReportCommand {
  name: string;
  period: { start_date: string; end_date: string };
  objectives: string[];
}

function string(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function parseSummary(value: unknown): ReportSummary {
  const item = record(value);
  const period = record(item?.period);
  if (
    !item || !period || !string(item.id) || !string(item.name) ||
    !string(period.start_date) || !string(period.end_date) ||
    !string(item.stage) || !string(item.created_at) || !string(item.updated_at)
  ) {
    throw new ReportApiError(502, "invalid_response", "The report response was invalid.", true);
  }
  return {
    id: item.id as string,
    name: item.name as string,
    period: { start_date: period.start_date as string, end_date: period.end_date as string },
    stage: item.stage as string,
    created_at: item.created_at as string,
    updated_at: item.updated_at as string,
  };
}

function parseDetail(value: unknown): ReportDetail {
  const summary = parseSummary(value);
  const item = record(value);
  if (!Array.isArray(item?.objectives) || !item.objectives.every((entry) => typeof entry === "string") ||
    !(item.current_source_id === null || typeof item.current_source_id === "string")) {
    throw new ReportApiError(502, "invalid_response", "The report response was invalid.", true);
  }
  return { ...summary, objectives: item.objectives as string[], current_source_id: item.current_source_id as string | null };
}

function parsePage(value: unknown): ReportPage {
  const envelope = record(value);
  const page = record(envelope?.page);
  if (
    !envelope || !Array.isArray(envelope.data) || !page ||
    typeof page.limit !== "number" || typeof page.has_more !== "boolean" ||
    !(page.next_cursor === null || typeof page.next_cursor === "string") ||
    (page.has_more && !page.next_cursor)
  ) {
    throw new ReportApiError(502, "invalid_response", "The report response was invalid.", true);
  }
  return {
    data: envelope.data.map(parseSummary),
    page: {
      limit: page.limit,
      has_more: page.has_more,
      next_cursor: page.next_cursor as string | null,
    },
  };
}

export async function listReports(cursor?: string): Promise<ReportPage> {
  const query = new URLSearchParams({ limit: "25" });
  if (cursor) query.set("cursor", cursor);
  return parsePage(await request(`/reports?${query.toString()}`));
}

export async function getReport(reportId: string): Promise<ReportDetail> {
  const envelope = record(await request(`/reports/${encodeURIComponent(reportId)}`));
  return parseDetail(envelope?.data);
}

export async function createReport(
  command: CreateReportCommand,
  idempotencyKey: string,
): Promise<ReportDetail> {
  const envelope = record(await request("/reports", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify(command),
  }));
  return parseDetail(envelope?.data);
}
