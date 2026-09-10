import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 45000,
  expect: { timeout: 12000 },
  reporter: [['list'], ['junit', { outputFile: 'test-results/e2e-junit.xml' }]],
  use: {
    baseURL: process.env.OMNIAGENT_WEB_URL ?? 'http://127.0.0.1:5173',
    viewport: { width: 1440, height: 1050 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
})
