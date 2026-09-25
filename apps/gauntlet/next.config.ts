import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The engine hands out http://127.0.0.1:4747 links; Next dev blocks /_next/* for any origin it
  // does not list, which silently prevents hydration (no keyboard, no live dot). Dev-only setting.
  allowedDevOrigins: ["127.0.0.1", "localhost"],
};

export default nextConfig;
