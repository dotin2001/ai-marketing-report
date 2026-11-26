import type { ApiFieldDetail, CreateReportCommand } from "@/lib/reports-api";

export interface ReportFormValues {
  name: string;
  startDate: string;
  endDate: string;
  objectives: string[];
}

export type FormErrors = Record<string, string>;

function validCalendarDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

function length(value: string): number {
  return Array.from(value).length;
}

export function validateReportForm(values: ReportFormValues): {
  command: CreateReportCommand | null;
  errors: FormErrors;
} {
  const errors: FormErrors = {};
  const name = values.name.trim();
  const objectives = values.objectives.map((item) => item.trim());
  if (length(name) < 1 || length(name) > 200) {
    errors.name = "Enter a report name of 1 to 200 characters.";
  }
  if (!validCalendarDate(values.startDate)) {
    errors.startDate = "Enter a valid start date in YYYY-MM-DD format.";
  }
  if (!validCalendarDate(values.endDate)) {
    errors.endDate = "Enter a valid end date in YYYY-MM-DD format.";
  } else if (validCalendarDate(values.startDate) && values.endDate < values.startDate) {
    errors.endDate = "End date must not precede start date.";
  }
  if (objectives.length < 1 || objectives.length > 20) {
    errors.objectives = "Add 1 to 20 objectives.";
  }
  objectives.forEach((item, index) => {
    if (length(item) < 1 || length(item) > 2000) {
      errors[`objectives.${index}`] = "Enter an objective of 1 to 2,000 characters.";
    }
  });
  if (Object.keys(errors).length > 0) return { command: null, errors };
  return {
    command: {
      name,
      period: { start_date: values.startDate, end_date: values.endDate },
      objectives,
    },
    errors,
  };
}

export function mapServerFieldErrors(details: ApiFieldDetail[]): {
  errors: FormErrors;
  formMessages: string[];
} {
  const errors: FormErrors = {};
  const formMessages: string[] = [];
  for (const detail of details) {
    const path = detail.path;
    let key: string | null = null;
    if (path.length === 1 && path[0] === "name") key = "name";
    if (path.length === 1 && path[0] === "objectives") key = "objectives";
    if (path.length === 2 && path[0] === "period" && path[1] === "start_date") key = "startDate";
    if (path.length === 2 && path[0] === "period" && path[1] === "end_date") key = "endDate";
    if (path.length === 2 && path[0] === "objectives" && typeof path[1] === "number") {
      key = `objectives.${path[1]}`;
    }
    if (key) errors[key] = detail.message;
    else formMessages.push(detail.message);
  }
  return { errors, formMessages };
}
