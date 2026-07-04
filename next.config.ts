import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  output: "export",
  distDir: "out",  // Tek output dizini — fallback yok
  typescript: {
    ignoreBuildErrors: true,
  },
  reactStrictMode: false,
  images: {
    unoptimized: true,
  },
  // Next.js 16 Turbopack workspace root fix:
  // "We couldn't find the Next.js package" hatasını önler.
  // src/app dizininden Next.js çözümlenemediğinde workspace root
  // yanlış infer edilir. Turbopack.root ile explicitly belirt.
  turbopack: {
    root: path.join(__dirname),
  },
};

export default nextConfig;
