import { expect, test } from '@playwright/test'

test('kiosk shows the current schedule and opens true browser fullscreen', async ({ page }) => {
  const snapshot = {
    laboratory_id: 'lab-kiosk-test',
    laboratory_name: 'Lab Kimia 1',
    session_id: null,
    subject: 'Praktikum Larutan',
    class_name: 'Kelas XI MIPA 2',
    status: 'scheduled',
    opened_at: null,
    present_count: 0,
    late_count: 0,
    total_roster: 0,
    students: [],
  }

  await page.route('**/api/v1/public/laboratories', (route) =>
    route.fulfill({
      status: 200,
      json: [{ id: 'lab-kiosk-test', code: 'K-1', name: 'Lab Kimia 1' }],
    }),
  )
  await page.route('**/api/v1/public/kiosk-screens**', (route) =>
    route.fulfill({ status: 200, json: [] }),
  )
  await page.route('**/api/v1/public/display/session', (route) =>
    route.fulfill({
      status: 200,
      json: {
        display_token: 'synthetic-kiosk-display-token',
        expires_in_seconds: 3600,
        snapshot,
      },
    }),
  )
  await page.route('**/api/v1/public/display?*', (route) =>
    route.fulfill({ status: 200, json: snapshot }),
  )
  await page.route('**/api/v1/public/display/stream', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: `event: snapshot\ndata: ${JSON.stringify(snapshot)}\n\n`,
    }),
  )
  await page.route('http://127.0.0.1:8765/**', (route) => route.abort())

  await page.goto('/presensi')
  await page.getByTestId('display-pin-input').fill('1234')
  await page.getByRole('button', { name: 'Mulai Layar Presensi' }).click()

  await expect(page.getByTestId('display-session-state')).toHaveText('Sesi belum dibuka')
  await expect(page.getByTestId('display-session-details')).toContainText(
    'Praktikum Larutan · Kelas XI MIPA 2 · Lab Kimia 1',
  )
  await expect(page.getByTestId('display-session-opened')).toHaveText(
    'Belum dibuka oleh guru atau laboran.',
  )
  await expect(page.getByText(/478 titik/)).toHaveCount(0)

  await expect(page.locator('.display-view.kiosk:fullscreen')).toHaveCount(1)
  await expect(page.getByRole('button', { name: 'Keluar fullscreen' })).toBeVisible()
  const cameraFrame = await page.locator('.camera-frame__viewport').boundingBox()
  const cameraActions = await page.locator('.kiosk__board-actions').boundingBox()
  expect(cameraFrame).not.toBeNull()
  expect(cameraActions).not.toBeNull()
  expect(Math.abs(cameraFrame!.width / cameraFrame!.height - 4 / 3)).toBeLessThan(0.03)
  expect(cameraFrame!.y + cameraFrame!.height).toBeLessThanOrEqual(cameraActions!.y)

  await page.getByRole('button', { name: 'Keluar fullscreen' }).click()
  await expect(page.locator('.display-view.kiosk:fullscreen')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Fullscreen' })).toBeVisible()

  await page.reload()
  await expect(page.getByTestId('display-board')).toBeVisible()
  await expect(page.getByTestId('display-pin-input')).toHaveCount(0)
})
