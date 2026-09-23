import { defineConfig, devices } from '@playwright/test';
import path from 'path';

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:8000';

export default defineConfig({
  testDir: './',
  testMatch: /school_erp_demo\.spec\.ts$/,
  fullyParallel: false,
  workers: 1, // Single worker for smooth, sequential presentation recording
  retries: 0,
  timeout: 600000, // 10 minutes maximum duration for full product presentation
  expect: {
    timeout: 15000,
  },
  reporter: [
    ['list'],
    ['html', { outputFolder: path.join(__dirname, '..', 'playwright-report-demo'), open: 'never' }],
  ],
  outputDir: path.join(__dirname, 'recordings'),
  use: {
    baseURL: BASE_URL,
    // Desktop presentation viewport (1440x900 / 16:10 standard)
    viewport: { width: 1440, height: 900 },
    // Force video recording for product demonstration
    video: {
      mode: 'on',
      size: { width: 1440, height: 900 },
    },
    screenshot: 'only-on-failure',
    trace: 'off',
    actionTimeout: 15000,
    navigationTimeout: 25000,
    ignoreHTTPSErrors: true,
  },
  projects: [
    {
      name: 'demo-recording-chrome',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
        deviceScaleFactor: 1,
        launchOptions: {
          args: [
            '--disable-infobars',
            '--start-maximized',
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--font-render-hinting=medium',
          ],
        },
      },
    },
  ],
  webServer: {
    command: 'cd .. && ./venv/bin/python manage.py runserver 127.0.0.1:8000',
    url: BASE_URL,
    reuseExistingServer: true,
    timeout: 30000,
    stdout: 'pipe',
    stderr: 'pipe',
  },
});
