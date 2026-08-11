import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

const debugSourceMaps = process.env.VITE_DEBUG_SOURCEMAPS === "true";

// Tauri expects a fixed dev port and serves from src-tauri/target.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  // Tauri-specific dev-server tweaks.
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
    host: "127.0.0.1",
    proxy: {
      // Proxy /api → the FastAPI backend during dev so we don't fight CORS.
      "/api": {
        target: "http://127.0.0.1:8765",
        changeOrigin: true,
        ws: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
  envPrefix: ["VITE_", "TAURI_"],
  build: {
    target: "es2021",
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: debugSourceMaps,
  },
});
