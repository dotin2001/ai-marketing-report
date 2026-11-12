import { describe, expect, it } from "vitest";

import { getPublicApiBaseUrl } from "@/lib/env";

describe("public API base URL", () => {
  it("accepts an absolute HTTP(S) origin", () => {
    expect(getPublicApiBaseUrl("http://127.0.0.1:8000/path")).toBe("http://127.0.0.1:8000");
    expect(getPublicApiBaseUrl("https://api.example.test")).toBe("https://api.example.test");
  });

  it("allows the foundation page to run without a backend setting", () => {
    expect(getPublicApiBaseUrl(undefined)).toBeUndefined();
  });

  it.each([
    "relative/path",
    "ftp://api.example.test",
    "https://user:secret@api.example.test",
    "https://api.example.test?token=secret",
    "https://api.example.test#secret",
  ])("rejects an unsafe value without echoing it: %s", (value) => {
    expect(() => getPublicApiBaseUrl(value)).toThrow(/safe|absolute/);
    try {
      getPublicApiBaseUrl(value);
    } catch (error) {
      expect(String(error)).not.toContain(value);
    }
  });
});

