import type { NextConfig } from "next";
import { getPublicApiBaseUrl } from "./lib/env";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  turbopack: {
    root: process.cwd(),
  },
  async rewrites() {
    const backendOrigin = getPublicApiBaseUrl();
    return backendOrigin
      ? [{ source: "/api/v1/:path*", destination: `${backendOrigin}/api/v1/:path*` }]
      : [];
  },
};

export default nextConfig;
