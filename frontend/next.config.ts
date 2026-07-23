import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Shrink the production image: only the standalone server + static assets ship.
  output: "standalone",
};

export default nextConfig;
