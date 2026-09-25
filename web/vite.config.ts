import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const API_TARGET = process.env.HEXTRACK_API_URL ?? "http://localhost:8000";

/**
 * Vendor chunks. Each group takes only the modules its own `test` matches
 * (`includeDependenciesRecursively: false`): with the default, a group swallows its
 * dependencies, which put React inside the Recharts chunk and made every page download
 * 400 kB of charting to get React. Anything not listed falls into `vendor`, so a library's
 * own dependencies belong in its group's test.
 */
const VENDOR_GROUPS = [
  { name: "react", test: /node_modules[\\/](react|react-dom|react-is|scheduler)[\\/]/, priority: 40 },
  {
    name: "charts",
    test: /node_modules[\\/](recharts|d3-[a-z-]+|internmap|delaunator|robust-predicates|victory-vendor|es-toolkit|eventemitter3|reselect|immer|redux|redux-thunk|react-redux|@reduxjs|decimal\.js)[\\/]/,
    priority: 30,
  },
  { name: "tanstack", test: /node_modules[\\/]@tanstack[\\/]/, priority: 20 },
  { name: "motion", test: /node_modules[\\/](motion|motion-dom|motion-utils|framer-motion)[\\/]/, priority: 20 },
  { name: "ui", test: /node_modules[\\/](radix-ui|@radix-ui|cmdk)[\\/]/, priority: 20 },
  { name: "vendor", test: /node_modules/, priority: 10 },
];

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    // PORT lets a preview tool pick a free port; `make web` keeps 5173.
    port: Number(process.env.PORT) || 5173,
    strictPort: true,
    proxy: {
      "/api": { target: API_TARGET, changeOrigin: true },
    },
  },
  preview: {
    port: 4173,
    proxy: {
      "/api": { target: API_TARGET, changeOrigin: true },
    },
  },
  build: {
    target: "es2023",
    sourcemap: true,
    chunkSizeWarningLimit: 500,
    rolldownOptions: {
      output: {
        codeSplitting: { includeDependenciesRecursively: false, groups: VENDOR_GROUPS },
      },
    },
  },
});
