import { defineConfig } from "@playwright/test";

// Expects the stack to be running: `docker compose up` or `make dev` (UI :5173, API :8000).
export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  reporter: "list",
  workers: 1, // both tests share one live plant
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5173",
    viewport: { width: 1440, height: 900 },
  },
});
