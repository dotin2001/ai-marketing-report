import { afterEach, describe, expect, it, vi } from "vitest";

import nextConfig from "@/next.config";

afterEach(() => vi.unstubAllEnvs());

describe("same-origin API rewrite", () => {
  it("forwards the browser API path to the validated backend origin", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://127.0.0.1:8000/untrusted/path");
    expect(await nextConfig.rewrites?.()).toEqual([{
      source: "/api/v1/:path*",
      destination: "http://127.0.0.1:8000/api/v1/:path*",
    }]);
  });

  it("does not introduce a secret or bypass rewrite when no backend is configured", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "");
    expect(await nextConfig.rewrites?.()).toEqual([]);
  });
});
