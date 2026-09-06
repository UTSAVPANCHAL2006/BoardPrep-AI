import path from "path";
import { loadEnvConfig } from "@next/env";
import type { NextConfig } from "next";

// Single root .env for backend + frontend (see project root .env.example)
loadEnvConfig(path.join(__dirname, ".."));

const nextConfig: NextConfig = {
  reactStrictMode: true,
};

export default nextConfig;
