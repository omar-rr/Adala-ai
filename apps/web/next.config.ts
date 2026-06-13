import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  output: "standalone",
  turbopack: {
    root: path.resolve(process.cwd(), "../.."),
  },
  async rewrites() {
    const internalApiBase = process.env.INTERNAL_API_BASE_URL;
    if (!internalApiBase) {
      return [];
    }
    return [
      {
        source: "/api/:path*",
        destination: `${internalApiBase.replace(/\/$/, "")}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
