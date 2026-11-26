"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowLeft, Plus, Trash2 } from "lucide-react";

import { mapServerFieldErrors, validateReportForm, type FormErrors, type ReportFormValues } from "@/lib/report-form";
import { createReport, ReportApiError } from "@/lib/reports-api";

type SubmitState = "idle" | "submitting" | "error" | "auth" | "conflict";

const fieldClass = "mt-2 block min-h-11 w-full rounded-xl border border-neutral-300 bg-white px-4 py-3 text-base text-neutral-950 outline-none transition-colors placeholder:text-neutral-400 focus:border-[var(--accent)] focus:ring-2 focus:ring-emerald-100 aria-invalid:border-red-500 aria-invalid:focus:ring-red-100";
const labelClass = "block text-sm font-semibold text-neutral-800";

export function ReportForm() {
  const router = useRouter();
  const [values, setValues] = useState<ReportFormValues>({
    name: "", startDate: "", endDate: "", objectives: [""],
  });
  const [errors, setErrors] = useState<FormErrors>({});
  const [formMessage, setFormMessage] = useState("");
  const [state, setState] = useState<SubmitState>("idle");
  const commandRef = useRef<{ fingerprint: string; key: string } | null>(null);
  const blockedFingerprint = useRef<string | null>(null);
  const inFlight = useRef(false);
  const errorSummary = useRef<HTMLDivElement>(null);
  const focusError = useRef(false);

  useEffect(() => {
    if (focusError.current) {
      errorSummary.current?.focus();
      focusError.current = false;
    }
  }, [errors, formMessage]);

  function change(next: ReportFormValues) {
    setValues(next);
    setErrors({});
    setFormMessage("");
    setState("idle");
  }

  function changeObjective(index: number, text: string) {
    change({ ...values, objectives: values.objectives.map((item, position) => position === index ? text : item) });
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inFlight.current) return;
    const validation = validateReportForm(values);
    if (!validation.command) {
      setErrors(validation.errors);
      setFormMessage("Please correct the highlighted fields.");
      focusError.current = true;
      return;
    }
    const fingerprint = JSON.stringify(validation.command);
    if (blockedFingerprint.current === fingerprint) {
      setState("conflict");
      setFormMessage("Change the report details before submitting this command again.");
      focusError.current = true;
      return;
    }
    if (commandRef.current?.fingerprint !== fingerprint) {
      commandRef.current = { fingerprint, key: crypto.randomUUID() };
    }
    inFlight.current = true;
    setState("submitting");
    setErrors({});
    setFormMessage("");
    try {
      const report = await createReport(validation.command, commandRef.current.key);
      router.push(`/?created=${encodeURIComponent(report.id)}`);
    } catch (error) {
      if (error instanceof ReportApiError) {
        if (error.status === 422) {
          const mapped = mapServerFieldErrors(error.details);
          setErrors(mapped.errors);
          setFormMessage(mapped.formMessages[0] ?? "Please correct the highlighted fields.");
          setState("error");
        } else if (error.status === 401) {
          setFormMessage("Authentication is required to create a report.");
          setState("auth");
        } else if (error.status === 409 && error.code === "idempotency_conflict") {
          blockedFingerprint.current = fingerprint;
          setFormMessage("This command key was used for another report. Change the report details before trying again.");
          setState("conflict");
        } else {
          setFormMessage(error.message);
          setState("error");
        }
      } else {
        setFormMessage("The report could not be created. Try again.");
        setState("error");
      }
      focusError.current = true;
    } finally {
      inFlight.current = false;
    }
  }

  const hasError = Boolean(formMessage || Object.keys(errors).length);
  return (
    <div className="mx-auto w-full max-w-3xl px-5 pb-20 pt-8 sm:px-8 sm:pt-12">
      <Link href="/" className="inline-flex min-h-11 items-center gap-2 rounded-lg text-sm font-semibold text-neutral-600 hover:text-neutral-950 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"><ArrowLeft size={17} aria-hidden="true" /> Back to reports</Link>
      <header className="mt-6 border-b border-neutral-200 pb-8">
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-[var(--accent)]">New report</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-neutral-950 sm:text-5xl">Start with the essentials</h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-neutral-600 sm:text-base">Set a clear reporting period and the questions this report should answer.</p>
      </header>
      <form noValidate onSubmit={(event) => void submit(event)} className="mt-8 space-y-8">
        {hasError && (
          <div ref={errorSummary} tabIndex={-1} role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-950 outline-none focus-visible:ring-2 focus-visible:ring-red-800">
            <p className="font-semibold">{state === "auth" ? "Authentication required" : state === "conflict" ? "Submission conflict" : "Check your report details"}</p>
            <p className="mt-1">{formMessage}</p>
          </div>
        )}
        <section className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm sm:p-8" aria-labelledby="report-details-heading">
          <h2 id="report-details-heading" className="text-lg font-semibold text-neutral-950">Report details</h2>
          <p className="mt-1 text-sm text-neutral-600">Choose a descriptive name and inclusive dates.</p>
          <div className="mt-6">
            <label htmlFor="report-name" className={labelClass}>Report name</label>
            <input id="report-name" name="name" type="text" value={values.name} onChange={(event) => change({ ...values, name: event.target.value })} aria-invalid={Boolean(errors.name)} aria-describedby={errors.name ? "report-name-error" : "report-name-hint"} className={fieldClass} placeholder="e.g. Q1 acquisition performance" />
            <p id="report-name-hint" className="mt-2 text-xs text-neutral-500">1 to 200 characters.</p>
            {errors.name && <p id="report-name-error" className="mt-2 text-sm text-red-700">{errors.name}</p>}
          </div>
          <div className="mt-6 grid gap-5 sm:grid-cols-2">
            <div>
              <label htmlFor="period-start" className={labelClass}>Start date</label>
              <input id="period-start" name="startDate" type="date" value={values.startDate} onChange={(event) => change({ ...values, startDate: event.target.value })} aria-invalid={Boolean(errors.startDate)} aria-describedby={errors.startDate ? "period-start-error" : undefined} className={fieldClass} />
              {errors.startDate && <p id="period-start-error" className="mt-2 text-sm text-red-700">{errors.startDate}</p>}
            </div>
            <div>
              <label htmlFor="period-end" className={labelClass}>End date</label>
              <input id="period-end" name="endDate" type="date" value={values.endDate} onChange={(event) => change({ ...values, endDate: event.target.value })} aria-invalid={Boolean(errors.endDate)} aria-describedby={errors.endDate ? "period-end-error" : undefined} className={fieldClass} />
              {errors.endDate && <p id="period-end-error" className="mt-2 text-sm text-red-700">{errors.endDate}</p>}
            </div>
          </div>
        </section>
        <section className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm sm:p-8" aria-labelledby="objectives-heading">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h2 id="objectives-heading" className="text-lg font-semibold text-neutral-950">Analysis objectives</h2>
              <p className="mt-1 text-sm text-neutral-600">What should this report help you understand?</p>
            </div>
            <span className="rounded-full bg-neutral-100 px-3 py-1 text-xs font-semibold text-neutral-600">{values.objectives.length} of 20</span>
          </div>
          {errors.objectives && <p id="objectives-error" className="mt-4 text-sm text-red-700">{errors.objectives}</p>}
          <div className="mt-6 space-y-5">
            {values.objectives.map((objective, index) => (
              <div key={index} className="rounded-xl border border-neutral-200 bg-neutral-50 p-4">
                <div className="flex items-center justify-between gap-3">
                  <label htmlFor={`objective-${index}`} className={labelClass}>Objective {index + 1}</label>
                  <button type="button" onClick={() => change({ ...values, objectives: values.objectives.filter((_, position) => position !== index) })} disabled={values.objectives.length === 1} aria-label={`Remove objective ${index + 1}`} className="inline-flex min-h-10 items-center gap-1 rounded-lg px-2 text-xs font-semibold text-neutral-600 hover:bg-white hover:text-red-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-40"><Trash2 size={15} aria-hidden="true" /> Remove</button>
                </div>
                <textarea id={`objective-${index}`} name={`objectives.${index}`} rows={3} value={objective} onChange={(event) => changeObjective(index, event.target.value)} aria-invalid={Boolean(errors[`objectives.${index}`])} aria-describedby={errors[`objectives.${index}`] ? `objective-${index}-error` : undefined} className={`${fieldClass} resize-y`} placeholder="e.g. Identify the campaigns driving qualified leads" />
                {errors[`objectives.${index}`] && <p id={`objective-${index}-error`} className="mt-2 text-sm text-red-700">{errors[`objectives.${index}`]}</p>}
              </div>
            ))}
          </div>
          <button type="button" onClick={() => change({ ...values, objectives: [...values.objectives, ""] })} disabled={values.objectives.length >= 20} className="mt-5 inline-flex min-h-11 items-center gap-2 rounded-xl border border-neutral-300 bg-white px-4 py-2 text-sm font-semibold text-neutral-800 hover:bg-neutral-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-40"><Plus size={17} aria-hidden="true" /> Add objective</button>
        </section>
        <div className="flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-end">
          <Link href="/" className="inline-flex min-h-11 items-center justify-center rounded-xl px-5 py-3 text-sm font-semibold text-neutral-600 hover:text-neutral-950 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]">Cancel</Link>
          <button type="submit" disabled={state === "submitting"} className="inline-flex min-h-11 items-center justify-center rounded-xl bg-[var(--accent)] px-6 py-3 text-sm font-semibold text-white shadow-sm hover:bg-emerald-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)] disabled:cursor-wait disabled:opacity-60">{state === "submitting" ? "Creating report…" : state === "error" ? "Try creating again" : "Create report"}</button>
        </div>
        {state === "submitting" && <p role="status" aria-live="polite" className="text-right text-sm text-neutral-600">Submitting your report…</p>}
      </form>
    </div>
  );
}
