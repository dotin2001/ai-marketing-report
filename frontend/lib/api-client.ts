/** Same-origin API transport and safe public error boundary. */
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

export function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}

const messages: Record<string, string> = {
  unauthenticated: "Authentication is required.",
  resource_not_found: "The requested resource was not found.",
  payload_too_large: "The source exceeds the server size limit. Choose a smaller input.",
  unsupported_media_type: "The selected file type is not supported. Choose a CSV file.",
  unsupported_encoding: "The source encoding is not supported. Use UTF-8 content.",
  validation_failed: "The source input is invalid. Review the highlighted fields.",
  idempotency_conflict: "This submission key was used for another input. Select or enter a new input.",
  invalid_cursor: "The report list changed. Start from the first page.",
  storage_unavailable: "The source service is temporarily unavailable. Try again.",
  request_failed: "The request could not be completed. Try again.",
};

function details(value: unknown): ApiFieldDetail[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    const entry = record(item);
    if (!entry || typeof entry.code !== "string" || !/^[a-z][a-z0-9_]{0,63}$/.test(entry.code) ||
      !Array.isArray(entry.path) || entry.path.length > 5 ||
      !entry.path.every((part) => typeof part === "string" && /^[a-z][a-z0-9_]{0,63}$/.test(part) || Number.isInteger(part) && part >= 0)) return [];
    return [{ code: entry.code, path: entry.path as (string | number)[], message: "This field is invalid." }];
  });
}

export function errorFromResponse(status: number, body: unknown): ReportApiError {
  const envelope = record(record(body)?.error);
  const suppliedCode = envelope?.code;
  const code = typeof suppliedCode === "string" && Object.hasOwn(messages, suppliedCode)
    ? suppliedCode : status === 401 ? "unauthenticated" : status === 404 ? "resource_not_found" : "request_failed";
  return new ReportApiError(status, code, messages[code], envelope?.retryable === true, details(envelope?.details));
}

export function networkError(): ReportApiError {
  return new ReportApiError(0, "network_error", "Could not connect to the report service.", true);
}

export function invalidResponse(): ReportApiError {
  return new ReportApiError(502, "invalid_response", "The report response was invalid.", true);
}

export async function request(path: string, init?: RequestInit): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, { credentials: "same-origin", cache: "no-store", ...init });
  } catch {
    throw networkError();
  }
  let body: unknown;
  try { body = await response.json(); } catch { body = null; }
  if (!response.ok) throw errorFromResponse(response.status, body);
  return body;
}
