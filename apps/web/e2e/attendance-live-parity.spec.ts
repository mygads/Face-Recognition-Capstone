import { expect, test } from '@playwright/test'

/**
 * P2-2 live parity smoke test: runs ONLY against a real stack
 * (`PRESENSI_E2E_LIVE=1`), with zero API route stubbing. It verifies that
 * login reaches the current admin dashboard and its API-backed summary renders.
 * Full seeded field scenarios stay in docs/pengujian.md (manual, hardware).
 */
const LIVE = process.env.PRESENSI_E2E_LIVE === '1'
const API_URL = process.env.PRESENSI_E2E_API_URL ?? 'http://127.0.0.1:8000'
const EMAIL = process.env.PRESENSI_E2E_EMAIL ?? 'admin@local.test'
const PASSWORD = process.env.PRESENSI_E2E_PASSWORD ?? ''

test.skip(!LIVE, 'requires a live stack: PRESENSI_E2E_LIVE=1')

test('live stack serves health, login, and admin dashboard', async ({ page, request }) => {
  test.skip(!PASSWORD, 'set PRESENSI_E2E_PASSWORD for the live account')

  const health = await request.get(`${API_URL}/api/v1/health`)
  expect(health.status()).toBe(200)

  await page.goto('/auth/login')
  await page.getByLabel('Email sekolah').fill(EMAIL)
  await page.getByLabel('Kata sandi').fill(PASSWORD)
  await page.getByRole('button', { name: 'Masuk' }).click()
  await expect(page).toHaveURL(/\/app\/dashboard$/)

  const dashboard = page.getByTestId('dashboard-page')
  await expect(dashboard).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Dashboard Admin' })).toBeVisible()
  await expect(dashboard.getByText('Sesi Praktikum Aktif')).toBeVisible()
})
