import { errorFromResponse, invalidResponse, networkError, record, request } from "@/lib/api-client";

export interface SourceDetail {
  id: string;
  report_id: string;
  source_type: "csv" | "text";
  byte_size: number;
  checksum_sha256: string;
  media_type: string;
  encoding: string | null;
  display_filename: string | null;
  created_at: string;
}

export interface SourcePreview {
  source_type: "csv" | "text";
  confirmed: false;
  validation_status: "unvalidated";
  columns: { ordinal: number; original_header: string }[] | null;
  rows: { record_index: number; values: string[] }[] | null;
  total_records: number | null;
  excerpt: string | null;
  truncated: boolean;
}

export type UploadUpdate =
  | { kind: "uploading"; loaded: number | null; total: number | null }
  | { kind: "processing" };

function text(value: unknown): value is string { return typeof value === "string"; }
function nonnegative(value: unknown): value is number { return Number.isSafeInteger(value) && (value as number) >= 0; }
function sourceType(value: unknown): value is "csv" | "text" { return value === "csv" || value === "text"; }

function parseSource(value: unknown): SourceDetail {
  const item = record(value);
  if (!item || !text(item.id) || !text(item.report_id) || !sourceType(item.source_type) ||
    !nonnegative(item.byte_size) || !text(item.checksum_sha256) || !text(item.media_type) ||
    !(item.encoding === null || text(item.encoding)) ||
    !(item.display_filename === null || text(item.display_filename)) || !text(item.created_at)) throw invalidResponse();
  return {
    id: item.id, report_id: item.report_id, source_type: item.source_type,
    byte_size: item.byte_size as number, checksum_sha256: item.checksum_sha256,
    media_type: item.media_type, encoding: item.encoding as string | null,
    display_filename: item.display_filename as string | null, created_at: item.created_at,
  };
}

function parsePreview(value: unknown): SourcePreview {
  const item = record(value);
  if (!item || !sourceType(item.source_type) || item.confirmed !== false ||
    item.validation_status !== "unvalidated" || typeof item.truncated !== "boolean" ||
    !(item.total_records === null || nonnegative(item.total_records)) ||
    !(item.excerpt === null || text(item.excerpt)) ||
    !(item.columns === null || Array.isArray(item.columns) && item.columns.every((column) => {
      const entry = record(column); return entry && nonnegative(entry.ordinal) && text(entry.original_header);
    })) ||
    !(item.rows === null || Array.isArray(item.rows) && item.rows.every((row) => {
      const entry = record(row); return entry && nonnegative(entry.record_index) && entry.record_index > 0 &&
        Array.isArray(entry.values) && entry.values.every(text);
    }))) throw invalidResponse();
  return {
    source_type: item.source_type, confirmed: false, validation_status: "unvalidated",
    columns: item.columns as SourcePreview["columns"], rows: item.rows as SourcePreview["rows"],
    total_records: item.total_records as number | null, excerpt: item.excerpt as string | null,
    truncated: item.truncated,
  };
}

function data(body: unknown): unknown { return record(body)?.data; }
const path = (reportId: string) => `/reports/${encodeURIComponent(reportId)}/sources`;

export async function getSource(reportId: string, sourceId: string): Promise<SourceDetail> {
  return parseSource(data(await request(`${path(reportId)}/${encodeURIComponent(sourceId)}`)));
}

export async function getSourcePreview(reportId: string, sourceId: string): Promise<SourcePreview> {
  return parsePreview(data(await request(`${path(reportId)}/${encodeURIComponent(sourceId)}/preview`)));
}

export async function attachText(reportId: string, content: string, key: string): Promise<SourceDetail> {
  return parseSource(data(await request(`${path(reportId)}/text`, {
    method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": key },
    body: JSON.stringify({ content }),
  })));
}

export function attachCsv(
  reportId: string, file: File, key: string, onUpdate: (update: UploadUpdate) => void,
): Promise<SourceDetail> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/v1${path(reportId)}/csv`);
    xhr.withCredentials = true;
    xhr.setRequestHeader("Idempotency-Key", key);
    xhr.upload.onprogress = (event) => {
      onUpdate(event.lengthComputable && event.total > 0
        ? { kind: "uploading", loaded: event.loaded, total: event.total }
        : { kind: "uploading", loaded: null, total: null });
    };
    xhr.upload.onload = () => onUpdate({ kind: "processing" });
    xhr.onerror = () => reject(networkError());
    xhr.onabort = () => reject(networkError());
    xhr.onload = () => {
      let body: unknown;
      try { body = JSON.parse(xhr.responseText); } catch { body = null; }
      if (xhr.status < 200 || xhr.status >= 300) { reject(errorFromResponse(xhr.status, body)); return; }
      try { resolve(parseSource(data(body))); } catch { reject(invalidResponse()); }
    };
    const form = new FormData();
    form.append("file", file);
    onUpdate({ kind: "uploading", loaded: null, total: null });
    try { xhr.send(form); } catch { reject(networkError()); }
  });
}
