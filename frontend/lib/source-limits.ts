export const DEFAULT_CSV_MAX_BYTES = 10_485_760;
export const DEFAULT_TEXT_MAX_BYTES = 1_048_576;

export function positiveByteLimit(value: string | undefined, fallback: number, name: string): number {
  if (value === undefined || value === "") return fallback;
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < 1) throw new Error(`${name} must be a positive byte count`);
  return parsed;
}

export function sourceLimits() {
  return {
    csv: positiveByteLimit(process.env.NEXT_PUBLIC_SOURCE_CSV_MAX_BYTES, DEFAULT_CSV_MAX_BYTES, "NEXT_PUBLIC_SOURCE_CSV_MAX_BYTES"),
    text: positiveByteLimit(process.env.NEXT_PUBLIC_SOURCE_TEXT_MAX_BYTES, DEFAULT_TEXT_MAX_BYTES, "NEXT_PUBLIC_SOURCE_TEXT_MAX_BYTES"),
  };
}

export function utf8Bytes(value: string): number { return new TextEncoder().encode(value).byteLength; }
export function formatBytes(bytes: number): string {
  return bytes % 1_048_576 === 0 ? `${bytes / 1_048_576} MiB` : `${bytes.toLocaleString()} bytes`;
}

export function csvSelectionError(file: File | null, maxBytes: number): string | null {
  if (!file) return "Choose a CSV file.";
  if (file.size === 0) return "The selected file is empty.";
  if (file.size > maxBytes) return `The selected file exceeds ${formatBytes(maxBytes)}.`;
  const type = file.type.toLowerCase();
  if (type && type !== "text/csv" && type !== "application/csv") {
    return "Choose a CSV file.";
  }
  return null;
}

export function textSelectionError(content: string, maxBytes: number): string | null {
  if (!content.trim()) return "Enter source content before submitting.";
  if (utf8Bytes(content) > maxBytes) return `Pasted content exceeds ${formatBytes(maxBytes)}.`;
  return null;
}
