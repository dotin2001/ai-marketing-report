"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, ClipboardPaste, RotateCcw, Upload } from "lucide-react";

import { ReportApiError, getReport, type ReportDetail } from "@/lib/reports-api";
import { attachCsv, attachText, getSource, getSourcePreview, type SourceDetail, type SourcePreview, type UploadUpdate } from "@/lib/sources-api";
import { csvSelectionError, formatBytes, sourceLimits, textSelectionError, utf8Bytes } from "@/lib/source-limits";

type ReportState = "loading" | "ready" | "auth" | "missing" | "error";
type SourceState = "idle" | "loading" | "error";
type PreviewState = "idle" | "loading" | "ready" | "error";
type SubmitState = "idle" | "uploading" | "processing" | "submitting" | "accepted" | "error" | "conflict";
type Mode = "csv" | "text";

const limits = sourceLimits();
const focusClass = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]";
const buttonClass = `inline-flex min-h-11 items-center justify-center gap-2 rounded-xl px-5 py-3 text-sm font-semibold ${focusClass}`;

function safeFailure(error: unknown): string {
  return error instanceof ReportApiError ? error.message : "The request could not be completed. Try again.";
}

function SourceReview({ source, preview, previewState, onRetry }: {
  source: SourceDetail;
  preview: SourcePreview | null;
  previewState: PreviewState;
  onRetry: () => void;
}) {
  return (
    <section className="mt-10 rounded-2xl border border-emerald-200 bg-white p-5 shadow-sm sm:p-8" aria-labelledby="source-heading">
      <p className="text-xs font-bold uppercase tracking-[0.15em] text-emerald-800">Attached source</p>
      <h2 id="source-heading" className="mt-2 break-words text-xl font-semibold text-neutral-950">{source.source_type === "csv" ? source.display_filename ?? "CSV source" : "Pasted content"}</h2>
      <p className="mt-2 text-sm text-neutral-700">Unvalidated source · Not confirmed</p>
      <dl className="mt-5 grid gap-3 text-sm sm:grid-cols-2">
        <div><dt className="font-semibold text-neutral-700">Type</dt><dd className="text-neutral-900">{source.source_type === "csv" ? "CSV" : "Pasted text"}</dd></div>
        <div><dt className="font-semibold text-neutral-700">Size</dt><dd className="text-neutral-900">{formatBytes(source.byte_size)}</dd></div>
      </dl>
      <p className="mt-5 text-sm text-neutral-600">Mapping and confirmation follow in a later step. Attachment has not calculated metrics or started analysis.</p>
      {previewState === "loading" && <p role="status" aria-live="polite" className="mt-6 text-sm text-neutral-700">Loading bounded preview…</p>}
      {previewState === "error" && <div role="alert" className="mt-6 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-950"><p>Preview could not be loaded. The source remains attached.</p><button type="button" onClick={onRetry} className={`mt-3 underline ${focusClass}`}>Retry preview</button></div>}
      {previewState === "ready" && preview && (
        <div className="mt-7 border-t border-neutral-200 pt-6">
          <h3 className="text-lg font-semibold text-neutral-950">Source preview</h3>
          <p className="mt-1 text-sm text-neutral-600">Unvalidated, unconfirmed source data. {preview.truncated ? "Only a bounded sample is shown." : "The returned preview is not truncated."}</p>
          {preview.source_type === "csv" ? (
            <>
              <p className="mt-3 text-sm text-neutral-700">{preview.total_records ?? 0} source records · {preview.rows?.length ?? 0} preview rows</p>
              <div className="mt-4 max-w-full overflow-x-auto rounded-xl border border-neutral-200">
                <table className="min-w-full border-collapse text-left text-sm">
                  <caption className="sr-only">Unvalidated CSV sample with source column ordinals and record indexes</caption>
                  <thead className="bg-neutral-50"><tr><th scope="col" className="whitespace-nowrap border-b border-neutral-200 px-4 py-3">Record</th>{preview.columns?.map((column) => <th scope="col" key={column.ordinal} className="min-w-36 border-b border-neutral-200 px-4 py-3 align-top"><span className="block text-xs text-neutral-500">Column {column.ordinal}</span><span className="break-words">{column.original_header || "(blank header)"}</span></th>)}</tr></thead>
                  <tbody>{preview.rows?.map((row) => <tr key={row.record_index}><th scope="row" className="border-b border-neutral-100 px-4 py-3 font-semibold">{row.record_index}</th>{preview.columns?.map((column) => <td key={column.ordinal} className="max-w-64 break-words border-b border-neutral-100 px-4 py-3 align-top">{row.values[column.ordinal] ?? ""}</td>)}</tr>)}</tbody>
                </table>
              </div>
            </>
          ) : <pre className="mt-4 max-w-full overflow-x-auto whitespace-pre-wrap break-words rounded-xl border border-neutral-200 bg-neutral-50 p-4 text-sm text-neutral-900">{preview.excerpt ?? ""}</pre>}
        </div>
      )}
    </section>
  );
}

export function ImportPage({ reportId }: { reportId: string }) {
  const [report, setReport] = useState<ReportDetail | null>(null);
  const [reportState, setReportState] = useState<ReportState>("loading");
  const [source, setSource] = useState<SourceDetail | null>(null);
  const [sourceState, setSourceState] = useState<SourceState>("idle");
  const [preview, setPreview] = useState<SourcePreview | null>(null);
  const [previewState, setPreviewState] = useState<PreviewState>("idle");
  const [mode, setMode] = useState<Mode>("csv");
  const [file, setFile] = useState<File | null>(null);
  const [content, setContent] = useState("");
  const [submitState, setSubmitState] = useState<SubmitState>("idle");
  const [upload, setUpload] = useState<UploadUpdate>({ kind: "uploading", loaded: null, total: null });
  const [message, setMessage] = useState("");
  const fileKey = useRef<string | null>(null);
  const textKey = useRef<string | null>(null);
  const blockedKey = useRef<string | null>(null);
  const activeSourceId = useRef<string | null>(null);
  const inFlight = useRef(false);
  const mounted = useRef(true);
  const alertRef = useRef<HTMLDivElement>(null);
  const focusAlert = useRef(false);

  useEffect(() => {
    if (focusAlert.current) { alertRef.current?.focus(); focusAlert.current = false; }
  }, [message]);

  const loadPreview = useCallback(async (sourceId: string) => {
    setPreviewState("loading");
    try {
      const result = await getSourcePreview(reportId, sourceId);
      if (mounted.current) { setPreview(result); setPreviewState("ready"); }
    } catch (error) {
      if (!mounted.current) return;
      if (error instanceof ReportApiError && error.status === 401) { setSource(null); setReportState("auth"); }
      else setPreviewState("error");
    }
  }, [reportId]);

  const loadSource = useCallback(async (sourceId: string) => {
    activeSourceId.current = sourceId;
    setSourceState("loading");
    try {
      const detail = await getSource(reportId, sourceId);
      if (!mounted.current) return;
      setSource(detail);
      setSourceState("idle");
      void loadPreview(detail.id);
    } catch (error) {
      if (!mounted.current) return;
      if (error instanceof ReportApiError && error.status === 401) { setReportState("auth"); setSource(null); }
      else { setSourceState("error"); if (error instanceof ReportApiError && error.status === 404) setSource(null); }
    }
  }, [loadPreview, reportId]);

  const loadReport = useCallback(async () => {
    setReportState("loading");
    try {
      const detail = await getReport(reportId);
      if (!mounted.current) return;
      setReport(detail);
      setReportState("ready");
      if (detail.current_source_id) void loadSource(detail.current_source_id);
    } catch (error) {
      if (!mounted.current) return;
      setReport(null); setSource(null);
      setReportState(error instanceof ReportApiError && error.status === 401 ? "auth" :
        error instanceof ReportApiError && error.status === 404 ? "missing" : "error");
    }
  }, [loadSource, reportId]);

  useEffect(() => {
    mounted.current = true;
    void Promise.resolve().then(() => loadReport());
    return () => { mounted.current = false; };
  }, [loadReport]);

  function selectFile(next: File | null) {
    setFile(next); fileKey.current = next ? crypto.randomUUID() : null;
    blockedKey.current = null; setSubmitState("idle"); setMessage("");
  }

  function editContent(next: string) {
    setContent(next); textKey.current = crypto.randomUUID();
    blockedKey.current = null; setSubmitState("idle"); setMessage("");
  }

  function showFailure(error: unknown, key: string) {
    const issue = error instanceof ReportApiError ? error : null;
    if (issue?.status === 401) setReportState("auth");
    else if (issue?.status === 404) setReportState("missing");
    else {
      setSubmitState(issue?.code === "idempotency_conflict" ? "conflict" : "error");
      if (issue?.code === "idempotency_conflict") blockedKey.current = key;
      setMessage(safeFailure(error)); focusAlert.current = true;
    }
  }

  async function submit() {
    if (inFlight.current || reportState !== "ready") return;
    const issue = mode === "csv" ? csvSelectionError(file, limits.csv) : textSelectionError(content, limits.text);
    if (issue) { setMessage(issue); setSubmitState("error"); focusAlert.current = true; return; }
    const key = mode === "csv" ? fileKey.current ?? crypto.randomUUID() : textKey.current ?? crypto.randomUUID();
    if (mode === "csv") fileKey.current = key; else textKey.current = key;
    if (blockedKey.current === key) { setMessage("Choose a different file or edit the text before submitting again."); setSubmitState("conflict"); focusAlert.current = true; return; }
    inFlight.current = true; setMessage(""); setSubmitState(mode === "csv" ? "uploading" : "submitting");
    try {
      const accepted = mode === "csv"
        ? await attachCsv(reportId, file!, key, (update) => {
            if (!mounted.current) return;
            setUpload(update); setSubmitState(update.kind === "processing" ? "processing" : "uploading");
          })
        : await attachText(reportId, content, key);
      if (!mounted.current) return;
      setSource(accepted); setPreview(null); setPreviewState("idle"); setSubmitState("accepted");
      void loadSource(accepted.id);
    } catch (error) {
      if (mounted.current) showFailure(error, key);
    } finally { inFlight.current = false; }
  }

  if (reportState !== "ready" || !report) return (
    <div className="mx-auto max-w-5xl px-5 py-10 sm:px-8">
      <Link href="/" className={`${buttonClass} text-neutral-700`}>← Back to reports</Link>
      {reportState === "loading" && <p role="status" className="mt-8">Loading report…</p>}
      {reportState === "auth" && <div role="alert" className="mt-8 rounded-xl border border-amber-200 bg-amber-50 p-6"><h1 className="text-xl font-semibold">Authentication required</h1><p>Sign in through your organization’s configured authentication to import data.</p></div>}
      {reportState === "missing" && <div role="alert" className="mt-8 rounded-xl border border-neutral-200 bg-white p-6"><h1 className="text-xl font-semibold">Report unavailable</h1><p>The requested report was not found.</p></div>}
      {reportState === "error" && <div role="alert" className="mt-8 rounded-xl border border-red-200 bg-red-50 p-6"><h1 className="text-xl font-semibold">Report could not be loaded</h1><button type="button" onClick={() => void loadReport()} className={`${buttonClass} mt-4 border border-red-300 bg-white`}>Try again</button></div>}
    </div>
  );

  const busy = submitState === "uploading" || submitState === "processing" || submitState === "submitting";
  const percent = upload.kind === "uploading" && upload.loaded !== null && upload.total !== null
    ? Math.min(100, Math.round(upload.loaded / upload.total * 100)) : null;
  return (
    <div className="mx-auto w-full max-w-5xl px-5 pb-20 pt-8 sm:px-8 sm:pt-12">
      <Link href="/" className={`${buttonClass} px-0 text-neutral-700`}><ArrowLeft size={17} aria-hidden="true" /> Back to reports</Link>
      <header className="mt-5 border-b border-neutral-200 pb-8">
        <p className="text-xs font-bold uppercase tracking-[0.15em] text-emerald-800">Data import</p>
        <h1 className="mt-2 break-words text-3xl font-semibold text-neutral-950 sm:text-5xl">{report.name}</h1>
        <p className="mt-3 text-sm leading-6 text-neutral-600">Attach an original CSV or pasted content. You will review and confirm it before analysis.</p>
      </header>
      {sourceState === "loading" && <p role="status" className="mt-8 text-sm text-neutral-700">Loading current source…</p>}
      {sourceState === "error" && <div role="alert" className="mt-8 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-950"><p>Source detail could not be loaded.</p><button type="button" onClick={() => activeSourceId.current && void loadSource(activeSourceId.current)} className={`mt-2 underline ${focusClass}`}>Retry source</button></div>}
      {source && <SourceReview source={source} preview={preview} previewState={previewState} onRetry={() => void loadPreview(source.id)} />}
      <section className="mt-10 rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm sm:p-8" aria-labelledby="attach-heading">
        <h2 id="attach-heading" className="text-xl font-semibold text-neutral-950">Attach source data</h2>
        <div className="mt-5 flex flex-wrap gap-3" role="group" aria-label="Source type">
          <button type="button" disabled={busy} onClick={() => { setMode("csv"); setMessage(""); setSubmitState("idle"); }} aria-pressed={mode === "csv"} className={`${buttonClass} border ${mode === "csv" ? "border-emerald-700 bg-emerald-50 text-emerald-900" : "border-neutral-300 bg-white text-neutral-800"}`}><Upload size={17} aria-hidden="true" /> CSV file</button>
          <button type="button" disabled={busy} onClick={() => { setMode("text"); setMessage(""); setSubmitState("idle"); }} aria-pressed={mode === "text"} className={`${buttonClass} border ${mode === "text" ? "border-emerald-700 bg-emerald-50 text-emerald-900" : "border-neutral-300 bg-white text-neutral-800"}`}><ClipboardPaste size={17} aria-hidden="true" /> Paste content</button>
        </div>
        {mode === "csv" ? <div className="mt-7">
          <label htmlFor="source-file" className="block text-sm font-semibold text-neutral-900">CSV file</label>
          <p id="csv-hint" className="mt-1 text-sm text-neutral-600">Choose one CSV file, up to {formatBytes(limits.csv)}. The server checks its contents and encoding.</p>
          <input id="source-file" type="file" accept=".csv,text/csv,application/csv" disabled={busy} aria-describedby="csv-hint" onChange={(event) => { selectFile(event.target.files?.[0] ?? null); event.target.value = ""; }} className={`mt-3 block w-full min-w-0 rounded-xl border border-neutral-300 p-3 text-sm text-neutral-900 file:mr-4 file:rounded-lg file:border-0 file:bg-emerald-50 file:px-4 file:py-2 file:font-semibold file:text-emerald-900 ${focusClass}`} />
          {file && <p className="mt-2 break-words text-sm text-neutral-700">Selected: {file.name} · {formatBytes(file.size)}</p>}
        </div> : <div className="mt-7">
          <label htmlFor="source-text" className="block text-sm font-semibold text-neutral-900">Pasted content</label>
          <p id="text-hint" className="mt-1 text-sm text-neutral-600">Paste the original content, up to {formatBytes(limits.text)} UTF-8. Claims remain unvalidated.</p>
          <textarea id="source-text" value={content} onChange={(event) => editContent(event.target.value)} disabled={busy} aria-describedby="text-hint text-count" rows={8} className={`mt-3 block w-full min-w-0 rounded-xl border border-neutral-300 p-4 text-base text-neutral-950 ${focusClass}`} />
          <p id="text-count" className="mt-2 text-sm text-neutral-600">{utf8Bytes(content).toLocaleString()} of {limits.text.toLocaleString()} bytes</p>
        </div>}
        {message && <div ref={alertRef} tabIndex={-1} role="alert" className="mt-6 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-950 outline-none focus-visible:ring-2 focus-visible:ring-red-800"><p>{message}</p>{submitState === "error" && <p className="mt-1">Correct the input or retry the same submission.</p>}</div>}
        {submitState === "uploading" && (percent === null
          ? <p role="status" aria-live="polite" className="mt-5 text-sm text-neutral-700">Uploading CSV… Progress unavailable.</p>
          : <div className="mt-5"><p role="status" aria-live="polite" className="text-sm text-neutral-700">Uploading CSV: {percent}%</p><progress value={percent} max={100} aria-label="CSV upload progress" className="mt-2 w-full accent-emerald-700" /></div>)}
        {submitState === "processing" && <p role="status" aria-live="polite" className="mt-5 text-sm text-neutral-700">Transfer complete. Waiting for server acceptance…</p>}
        {submitState === "submitting" && <p role="status" aria-live="polite" className="mt-5 text-sm text-neutral-700">Submitting pasted content…</p>}
        {submitState === "accepted" && <p role="status" aria-live="polite" className="mt-5 text-sm font-semibold text-emerald-900">Source accepted. Loading its bounded preview…</p>}
        <button type="button" disabled={busy || submitState === "conflict"} onClick={() => void submit()} className={`${buttonClass} mt-7 bg-[var(--accent)] text-white hover:bg-emerald-800 disabled:cursor-not-allowed disabled:opacity-50`}><RotateCcw size={17} aria-hidden="true" /> {busy ? "Submitting…" : submitState === "error" ? "Retry attachment" : mode === "csv" ? "Attach CSV" : "Attach pasted content"}</button>
      </section>
    </div>
  );
}
