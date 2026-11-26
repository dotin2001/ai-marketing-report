import type { ReportSummary } from "@/lib/reports-api";

const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function formatCalendarDate(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return value;
  const month = Number(match[2]);
  const day = Number(match[3]);
  return month >= 1 && month <= 12 && day >= 1 && day <= 31
    ? `${months[month - 1]} ${day}, ${match[1]}`
    : value;
}

const stageLabels: Record<string, string> = {
  created: "Created", source_review: "Source review", analysis_ready: "Ready for analysis",
  analysis_pending: "Analysis pending", reviewing: "Reviewing", versioned: "Versioned",
};

export function stageLabel(stage: ReportSummary["stage"]): string {
  return stageLabels[stage] ?? "Stage unavailable";
}

export function uniqueReports(reports: ReportSummary[]): ReportSummary[] {
  const seen = new Set<string>();
  return reports.filter((report) => {
    if (seen.has(report.id)) return false;
    seen.add(report.id);
    return true;
  });
}
