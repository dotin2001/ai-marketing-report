const allowedProtocols = new Set(["http:", "https:"]);

export function getPublicApiBaseUrl(
  value = process.env.NEXT_PUBLIC_API_BASE_URL,
): string | undefined {
  if (value === undefined || value === "") {
    return undefined;
  }

  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error("NEXT_PUBLIC_API_BASE_URL must be an absolute HTTP(S) URL");
  }

  if (
    !allowedProtocols.has(parsed.protocol) ||
    parsed.username !== "" ||
    parsed.password !== "" ||
    parsed.search !== "" ||
    parsed.hash !== ""
  ) {
    throw new Error("NEXT_PUBLIC_API_BASE_URL must be a safe absolute HTTP(S) URL");
  }

  return parsed.origin;
}

