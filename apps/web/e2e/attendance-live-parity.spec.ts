import { expect, test } from '@playwright/test'

/**
 * P2-2 live parity smoke test: runs ONLY against a real stack
 * (`PRESENSI_E2E_LIVE=1`), with zero API route stubbing. It proves the
 * deployed web UI, Core API, and dashboard snapshot path are wired together.
 * Full seeded field scenarios stay in docs/pengujian.md (manual, hardware).
 */
const LIVE = process.env.PRESENSI_E2E_LIVE === '1'
const API_URL = process.env.PRESENSI_E2E_API_URL ?? 'http://127.0.0.1:8000'
const EMAIL = process.env.PRESENSI_E2E_EMAIL ?? 'admin@local.test'
const PASSWORD = process.env.PRESENSI_E2E_PASSWORD ?? ''

test.skip(!LIVE, 'requires a live stack: PRESENSI_E2E_LIVE=1')

test('live stack serves health, login, and dashboard snapshot path', async ({ page, request }) => {
  test.skip(!PASSWORD, 'set PRESENSI_E2E_PASSWORD for the live account')

  const health = await request.get(`${API_URL}/api/v1/health`)
  expect(health.status()).toBe(200)

  await page.goto('/auth/login')
  await page.getByLabel('Email sekolah').fill(EMAIL)
  await page.getByLabel('Kata sandi').fill(PASSWORD)
  await page.getByRole('button', { name: 'Masuk' }).click()
  await expect(page).toHaveURL(/\/app\/dashboard$/)

  const dashboard = page.locator('.dashboard-view')
  await expect(dashboard).toBeVisible()
  // The dashboard loads sessions + snapshot asynchronously; wait for either
  // the populated metrics or the empty state instead of counting instantly.
  await expect(
    page.getByTestId('metric-roster').or(page.getByTestId('no-active-session')).first(),
  ).toBeVisible({ timeout: 15_000 })
})
