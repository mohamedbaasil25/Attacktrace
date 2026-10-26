import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const api = process.env.VITE_API_PROXY ?? "http://localhost:8000";

export default defineConfig({
  envDir: "..", // VITE_* values (e.g. VITE_API_KEY) come from the repo-root .env
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": api,
      "/ws": { target: api.replace(/^http/, "ws"), ws: true },
    },
  },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
