/** Typed, same-origin boundary for the report-management API. */

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

export interface ApiFieldDetail {
  code: string;
  message: string;
  path: (string | number)[];
}

export class ReportApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly retryable: boolean,
    public readonly details: ApiFieldDetail[] = [],
  ) {
    super(message);
    this.name = "ReportApiError";
  }
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
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
  if (!Array.isArray(item?.objectives) || !item.objectives.every((entry) => typeof entry === "string")) {
    throw new ReportApiError(502, "invalid_response", "The report response was invalid.", true);
  }
  return { ...summary, objectives: item.objectives as string[] };
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

function parseFieldDetails(value: unknown): ApiFieldDetail[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((entry) => {
    const detail = record(entry);
    if (
      !detail || typeof detail.code !== "string" || typeof detail.message !== "string" ||
      !Array.isArray(detail.path) ||
      !detail.path.every((part) => typeof part === "string" || Number.isInteger(part))
    ) return [];
    return [{
      code: detail.code,
      message: detail.message,
      path: detail.path as (string | number)[],
    }];
  });
}

async function request(path: string, init?: RequestInit): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      credentials: "same-origin",
      cache: "no-store",
      ...init,
    });
  } catch {
    throw new ReportApiError(0, "network_error", "Could not connect to the report service.", true);
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) {
    const error = record(record(body)?.error);
    const code = string(error?.code) ?? (response.status === 401 ? "unauthenticated" : "request_failed");
    const message = string(error?.message) ?? (
      response.status === 401
        ? "Authentication is required to view reports."
        : "The report request could not be completed."
    );
    throw new ReportApiError(
      response.status,
      code,
      message,
      error?.retryable === true,
      parseFieldDetails(error?.details),
    );
  }
  return body;
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
