"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FileText, Plus, RotateCcw } from "lucide-react";

import { formatCalendarDate, stageLabel, uniqueReports } from "@/lib/report-display";
import { getReport, listReports, ReportApiError, type ReportSummary } from "@/lib/reports-api";

type InitialState = "loading" | "ready" | "first-error" | "auth";
type PageState = "idle" | "loading" | "error" | "invalid-cursor";

const createLinkClasses = "inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-[var(--accent)] px-5 py-3 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-emerald-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]";

function ReportCard({ report }: { report: ReportSummary }) {
  return (
    <article className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm sm:p-6">
      <div className="flex items-start gap-4">
        <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-emerald-50 text-[var(--accent)]" aria-hidden="true"><FileText size={20} /></div>
        <div className="min-w-0 flex-1">
          <h2 className="break-words text-lg font-semibold tracking-tight text-neutral-950">{report.name}</h2>
          <p className="mt-1 text-sm text-neutral-600">{formatCalendarDate(report.period.start_date)} – {formatCalendarDate(report.period.end_date)}</p>
        </div>
      </div>
      <div className="mt-6 flex items-center justify-between border-t border-neutral-100 pt-4">
        <span className="inline-flex rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-800">{stageLabel(report.stage)}</span>
        <span className="text-xs text-neutral-500">Report</span>
      </div>
    </article>
  );
}

export function ReportListing({ createdId }: { createdId?: string }) {
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [createdReport, setCreatedReport] = useState<ReportSummary | null>(null);
  const [initialState, setInitialState] = useState<InitialState>("loading");
  const [pageState, setPageState] = useState<PageState>("idle");
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [firstError, setFirstError] = useState("Reports could not be loaded.");
  const [pageError, setPageError] = useState("More reports could not be loaded.");
  const mounted = useRef(true);
  const loadingPage = useRef(false);

  const loadFirst = useCallback(async (preserve = false) => {
    try {
      const page = await listReports();
      if (!mounted.current) return;
      setReports(uniqueReports(page.data));
      setNextCursor(page.page.has_more ? page.page.next_cursor : null);
      setInitialState((current) => current === "auth" ? "auth" : "ready");
    } catch (error) {
      if (!mounted.current) return;
      if (error instanceof ReportApiError && error.status === 401) {
        setInitialState("auth");
        return;
      }
      const message = error instanceof ReportApiError ? error.message : "Reports could not be loaded.";
      if (preserve) {
        setPageError(message);
        setPageState("error");
      } else {
        setFirstError(message);
        setInitialState("first-error");
      }
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void Promise.resolve().then(() => loadFirst());
    if (createdId) {
      void getReport(createdId).then((report) => {
        if (mounted.current) setCreatedReport(report);
      }).catch((error: unknown) => {
        if (mounted.current && error instanceof ReportApiError && error.status === 401) setInitialState("auth");
      });
    }
    return () => { mounted.current = false; };
  }, [createdId, loadFirst]);

  const visible = useMemo(() => {
    if (!createdReport) return reports;
    const current = reports.find((report) => report.id === createdReport.id) ?? createdReport;
    return uniqueReports([current, ...reports]);
  }, [createdReport, reports]);

  async function loadMore() {
    if (!nextCursor || loadingPage.current || initialState !== "ready") return;
    loadingPage.current = true;
    setPageState("loading");
    try {
      const page = await listReports(nextCursor);
      if (!mounted.current) return;
      setReports((current) => uniqueReports([...current, ...page.data]));
      setNextCursor(page.page.has_more ? page.page.next_cursor : null);
      setPageState("idle");
    } catch (error) {
      if (!mounted.current) return;
      if (error instanceof ReportApiError && error.status === 401) {
        setInitialState("auth");
      } else if (error instanceof ReportApiError && error.code === "invalid_cursor") {
        setPageState("invalid-cursor");
      } else {
        setPageError(error instanceof ReportApiError ? error.message : "More reports could not be loaded.");
        setPageState("error");
      }
    } finally {
      loadingPage.current = false;
    }
  }

  return (
    <div className="mx-auto w-full max-w-6xl px-5 pb-20 pt-8 sm:px-8 sm:pt-12">
      <header className="flex flex-col gap-5 border-b border-neutral-200 pb-8 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-[var(--accent)]">Workspace</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-neutral-950 sm:text-5xl">Your reports</h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-neutral-600 sm:text-base">Keep every reporting period organized, from first draft to saved version.</p>
        </div>
        <Link href="/reports/new" className={createLinkClasses}><Plus size={18} aria-hidden="true" /> New report</Link>
      </header>

      {initialState === "loading" && <div role="status" aria-live="polite" className="mt-12 rounded-2xl border border-neutral-200 bg-white p-8 text-neutral-600">Loading reports…</div>}
      {initialState === "auth" && (
        <section role="alert" className="mt-12 rounded-2xl border border-amber-200 bg-amber-50 p-8">
          <h2 className="text-lg font-semibold text-amber-950">Authentication required</h2>
          <p className="mt-2 text-sm text-amber-900">Sign in through your organization’s configured authentication to view reports.</p>
        </section>
      )}
      {initialState === "first-error" && (
        <section role="alert" className="mt-12 rounded-2xl border border-red-200 bg-red-50 p-8">
          <h2 className="text-lg font-semibold text-red-950">Reports could not be loaded</h2>
          <p className="mt-2 text-sm text-red-900">{firstError}</p>
          <button type="button" onClick={() => { setInitialState("loading"); void loadFirst(); }} className="mt-5 inline-flex min-h-11 items-center gap-2 rounded-lg border border-red-300 bg-white px-4 py-2 text-sm font-semibold text-red-950 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-800"><RotateCcw size={16} aria-hidden="true" /> Try again</button>
        </section>
      )}
      {initialState === "ready" && visible.length === 0 && (
        <section className="mt-12 rounded-3xl border border-dashed border-neutral-300 bg-white px-6 py-14 text-center sm:px-10">
          <div className="mx-auto flex size-14 items-center justify-center rounded-2xl bg-emerald-50 text-[var(--accent)]" aria-hidden="true"><FileText size={26} /></div>
          <h2 className="mt-5 text-xl font-semibold tracking-tight text-neutral-950">No reports yet</h2>
          <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-neutral-600">Create your first report to set its reporting period and analysis objectives.</p>
          <Link href="/reports/new" className={`${createLinkClasses} mt-6`}>Create a report</Link>
        </section>
      )}
      {initialState === "ready" && visible.length > 0 && (
        <section aria-label="Report list" className="mt-10">
          <div className="mb-5 flex items-center justify-between gap-4">
            <h2 className="text-sm font-semibold uppercase tracking-[0.12em] text-neutral-500">All reports</h2>
            <span className="text-sm text-neutral-500">{visible.length} shown</span>
          </div>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{visible.map((report) => <ReportCard key={report.id} report={report} />)}</div>
          {pageState === "loading" && <p role="status" className="mt-6 text-sm text-neutral-600">Loading more reports…</p>}
          {pageState === "error" && (
            <div role="alert" className="mt-6 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-900">
              <p>{pageError}</p>
              <button type="button" onClick={() => void loadMore()} className="mt-3 rounded-lg underline underline-offset-4 focus-visible:outline-2 focus-visible:outline-offset-2">Retry this page</button>
            </div>
          )}
          {pageState === "invalid-cursor" && (
            <div role="alert" className="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
              <p>The report list changed while you were browsing.</p>
              <button type="button" onClick={() => { setPageState("idle"); void loadFirst(true); }} className="mt-3 rounded-lg underline underline-offset-4 focus-visible:outline-2 focus-visible:outline-offset-2">Start from first page</button>
            </div>
          )}
          {nextCursor && pageState === "idle" && (
            <button type="button" onClick={() => void loadMore()} className="mt-8 inline-flex min-h-11 items-center justify-center rounded-xl border border-neutral-300 bg-white px-5 py-3 text-sm font-semibold text-neutral-800 hover:bg-neutral-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]">Load more reports</button>
          )}
        </section>
      )}
    </div>
  );
}
