import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  timeout: 90_000,
  expect: { timeout: 20_000 },
  retries: 0,
  workers: 1,
  reporter: [["list"], ["json", { outputFile: "results.json" }]],
  use: { baseURL: process.env.AEON_WEB ?? "http://localhost:3000", trace: "retain-on-failure" },
});
