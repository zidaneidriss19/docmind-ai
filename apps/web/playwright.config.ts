import { defineConfig } from '@playwright/test'
import { fileURLToPath } from 'node:url'

const apiDirectory = fileURLToPath(new URL('../api', import.meta.url))
const python = process.env.DOCMIND_E2E_PYTHON ?? 'python'
const channel = process.env.DOCMIND_E2E_BROWSER_CHANNEL

export default defineConfig({
  testDir: './e2e',
  timeout: 45000,
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:5190',
    channel,
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: `"${python}" -m uvicorn e2e_api:app --app-dir tests --host 127.0.0.1 --port 8010`,
      cwd: apiDirectory,
      url: 'http://127.0.0.1:8010/health',
      reuseExistingServer: false,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 5190 --strictPort',
      url: 'http://127.0.0.1:5190',
      env: { DOCMIND_DEV_API_URL: 'http://127.0.0.1:8010' },
      reuseExistingServer: false,
    },
  ],
})
