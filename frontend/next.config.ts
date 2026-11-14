import type { NextConfig } from "next";

// Same-origin API proxy: with NEXT_PUBLIC_API_BASE="/" the browser calls a-eon.engineer/api/v1/*
// and Vercel forwards it server-side to the backend. Visitors never connect to the backend IP
// directly, so ISP-level IP blocks and CORS cannot break the site.
const AEON_API_ORIGIN = (process.env.AEON_API_ORIGIN || "https://api.a-eon.engineer").replace(/\/+$/, "");

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${AEON_API_ORIGIN}/api/v1/:path*` }];
  },
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
