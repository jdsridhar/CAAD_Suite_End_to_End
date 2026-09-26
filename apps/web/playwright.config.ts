import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:5174",
    browserName: "chromium",
    headless: true,
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "python tests/e2e/api_server.py",
      url: "http://127.0.0.1:8100/v1/workflows/capabilities",
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 5174 --strictPort",
      url: "http://127.0.0.1:5174",
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
});
