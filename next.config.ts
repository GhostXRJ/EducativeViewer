import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  distDir: 'nextBuild',
  productionBrowserSourceMaps: false,
};

export default nextConfig;
