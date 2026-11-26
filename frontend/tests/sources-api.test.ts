import { afterEach, describe, expect, it, vi } from "vitest";

import { errorFromResponse } from "@/lib/api-client";
import { attachCsv, attachText, getSource, getSourcePreview } from "@/lib/sources-api";
import { csvSelectionError, positiveByteLimit, textSelectionError, utf8Bytes } from "@/lib/source-limits";

const source = {
  id: "11111111-1111-4111-8111-111111111111", report_id: "22222222-2222-4222-8222-222222222222",
  source_type: "csv", byte_size: 12, checksum_sha256: "a".repeat(64), media_type: "text/csv",
  encoding: "utf-8", display_filename: "source.csv", original_filename_untrusted: "private.csv",
  created_at: "2026-01-01T00:00:00Z",
};
const preview = {
  source_type: "csv", confirmed: false, validation_status: "unvalidated",
  columns: [{ ordinal: 0, original_header: "date" }, { ordinal: 1, original_header: "date" }],
  rows: [{ record_index: 1, values: ["2026-01-01", "2026-01-02"] }],
  total_records: 4, excerpt: null, truncated: true,
};
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

afterEach(() => vi.unstubAllGlobals());

describe("source API boundary", () => {
  it("parses safe source detail and bounded preview fields", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(json({ data: source })).mockResolvedValueOnce(json({ data: preview }));
    vi.stubGlobal("fetch", fetcher);
    const result = await getSource(source.report_id, source.id);
    expect(result.display_filename).toBe("source.csv");
    expect(result).not.toHaveProperty("original_filename_untrusted");
    expect((await getSourcePreview(source.report_id, source.id)).columns).toEqual(preview.columns);
    expect(fetcher.mock.calls[0][0]).toContain(`/api/v1/reports/${source.report_id}/sources/${source.id}`);
  });

  it("sends exact pasted text and idempotency key", async () => {
    const fetcher = vi.fn().mockResolvedValue(json({ data: { ...source, source_type: "text", display_filename: null } }, 201));
    vi.stubGlobal("fetch", fetcher);
    await attachText(source.report_id, "a\n💡", "same-command");
    expect(fetcher.mock.calls[0][1]).toMatchObject({
      method: "POST", body: JSON.stringify({ content: "a\n💡" }),
      headers: { "Content-Type": "application/json", "Idempotency-Key": "same-command" },
    });
  });

  it("rejects malformed success without disclosing response content", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ data: { ...source, byte_size: "secret" } })));
    await expect(getSource(source.report_id, source.id)).rejects.toMatchObject({ code: "invalid_response" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ data: { ...preview, confirmed: true } })));
    await expect(getSourcePreview(source.report_id, source.id)).rejects.toMatchObject({ code: "invalid_response" });
  });

  it("normalizes intake, auth, missing, and malformed error envelopes safely", () => {
    expect(errorFromResponse(413, { error: { code: "payload_too_large", message: "secret contents", retryable: false } }).message).not.toContain("secret");
    expect(errorFromResponse(401, {}).code).toBe("unauthenticated");
    expect(errorFromResponse(404, {}).code).toBe("resource_not_found");
    expect(errorFromResponse(503, { error: { code: "storage_unavailable", retryable: true } }).retryable).toBe(true);
    const malformed = errorFromResponse(422, { error: { code: "unsafe", message: "=HYPERLINK(secret)", details: [{ code: "bad", message: "secret", path: ["content"] }] } });
    expect(malformed.message).not.toContain("secret");
    expect(malformed.details[0].message).toBe("This field is invalid.");
  });
});

describe("CSV transport", () => {
  class FakeXHR {
    static current: FakeXHR;
    upload: { onprogress?: (event: ProgressEvent) => void; onload?: () => void } = {};
    onload?: () => void;
    onerror?: () => void;
    onabort?: () => void;
    responseText = "";
    status = 0;
    withCredentials = false;
    headers: Record<string, string> = {};
    url = "";
    body?: FormData;
    constructor() { FakeXHR.current = this; }
    open(_method: string, url: string) { this.url = url; }
    setRequestHeader(name: string, value: string) { this.headers[name] = value; }
    send(body: FormData) { this.body = body; }
  }

  it("sends one file without setting a multipart boundary and distinguishes transfer from acceptance", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXHR);
    const updates: unknown[] = [];
    const file = new File(["a,b\n1,2"], "a.csv", { type: "text/csv" });
    const pending = attachCsv(source.report_id, file, "upload-key", (event) => updates.push(event));
    const xhr = FakeXHR.current;
    expect(xhr.url).toBe(`/api/v1/reports/${source.report_id}/sources/csv`);
    expect(xhr.withCredentials).toBe(true);
    expect(xhr.headers).toEqual({ "Idempotency-Key": "upload-key" });
    expect([...xhr.body!.keys()]).toEqual(["file"]);
    expect(xhr.body!.get("file")).toBe(file);
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 5, total: 10 } as ProgressEvent);
    xhr.upload.onload?.();
    expect(updates).toEqual([
      { kind: "uploading", loaded: null, total: null },
      { kind: "uploading", loaded: 5, total: 10 },
      { kind: "processing" },
    ]);
    xhr.status = 201; xhr.responseText = JSON.stringify({ data: source }); xhr.onload?.();
    expect((await pending).id).toBe(source.id);
  });

  it("uses indeterminate progress and safe failure on response loss", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXHR);
    const updates: unknown[] = [];
    const pending = attachCsv(source.report_id, new File(["a"], "a.csv"), "retry-key", (event) => updates.push(event));
    FakeXHR.current.upload.onprogress?.({ lengthComputable: false, loaded: 1, total: 0 } as ProgressEvent);
    FakeXHR.current.onerror?.();
    expect(updates.at(-1)).toEqual({ kind: "uploading", loaded: null, total: null });
    await expect(pending).rejects.toMatchObject({ code: "network_error", retryable: true });
  });
});

describe("public limits", () => {
  it("counts UTF-8 bytes and checks file and text boundaries", () => {
    expect(utf8Bytes("é💡")).toBe(6);
    expect(textSelectionError("é💡", 5)).toContain("exceeds");
    expect(textSelectionError("   ", 100)).toContain("Enter");
    expect(csvSelectionError(new File([], "empty.csv", { type: "text/csv" }), 10)).toContain("empty");
    expect(csvSelectionError(new File(["abc"], "a.pdf", { type: "application/pdf" }), 10)).toContain("CSV");
    expect(csvSelectionError(new File(["abc"], "a.csv", { type: "text/csv" }), 2)).toContain("exceeds");
    expect(csvSelectionError(new File(["abc"], "a.csv", { type: "text/csv" }), 3)).toBeNull();
  });

  it("requires a positive safe integer configuration", () => {
    expect(positiveByteLimit(undefined, 10, "LIMIT")).toBe(10);
    expect(() => positiveByteLimit("0", 10, "LIMIT")).toThrow();
    expect(() => positiveByteLimit("1.5", 10, "LIMIT")).toThrow();
  });
});
