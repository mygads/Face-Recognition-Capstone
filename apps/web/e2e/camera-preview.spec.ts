import { expect, test } from '@playwright/test'
import { stubNoActiveBrowserSession } from './session-fixture'

test('AI_EDGE dashboard shows its single preview and accepted student identity', async ({
  page,
}) => {
  await page.route('**/api/v1/**', (route) =>
    route.fulfill({
      status: 200,
      json: { items: [], pagination: { total: 0, limit: 100, offset: 0 } },
    }),
  )
  await stubNoActiveBrowserSession(page)
  await page.route('**/api/v1/auth/login', (route) =>
    route.fulfill({
      status: 200,
      json: {
        access_token: 'synthetic-preview-operator-token',
        token_type: 'bearer',
        expires_in_seconds: 900,
      },
    }),
  )
  await page.route('**/api/v1/auth/me', (route) =>
    route.fulfill({
      status: 200,
      json: {
        id: 'synthetic-admin',
        email: 'admin@example.test',
        full_name: 'Synthetic Administrator',
        roles: ['ADMIN'],
        must_change_password: false,
      },
    }),
  )
  await page.route('**/api/v1/admin/system/ai-readiness', (route) =>
    route.fulfill({
      status: 200,
      json: {
        deployment_profile: 'AI_EDGE',
        enrollment_models_ready: true,
        enrollment_model_version: 'opencv-zoo-sface-2021dec',
        enrollment_quality_revision: 0,
        central_ai_status: 'disabled',
        central_ai_models_ready: null,
        central_ai_model_version: null,
        central_ai_thresholds_configured: null,
        central_ai_recognition_ready: null,
        central_ai_config_desired_revision: null,
        central_ai_config_applied_revision: null,
        central_ai_config_sync_status: null,
      },
    }),
  )
  await page.route('**/api/v1/devices?**', (route) =>
    route.fulfill({
      status: 200,
      json: { items: [], pagination: { total: 0, limit: 10, offset: 0 } },
    }),
  )
  await page.route('**/api/v1/laboratories?**', (route) =>
    route.fulfill({
      status: 200,
      json: { items: [], pagination: { total: 0, limit: 100, offset: 0 } },
    }),
  )
  await page.route('http://127.0.0.1:8765/**', async (route) => {
    const request = route.request()
    const headers = {
      'Access-Control-Allow-Origin': 'http://127.0.0.1:4173',
      'Access-Control-Allow-Headers': 'Authorization, Content-Type, X-Presensi-Preview-Token',
      'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
      'Cache-Control': 'no-store',
    }
    if (request.method() === 'OPTIONS') {
      await route.fulfill({ status: 204, headers })
    } else if (request.url().endsWith('/v1/session') && request.method() === 'POST') {
      await route.fulfill({
        status: 201,
        headers,
        json: { preview_token: 'synthetic-local-preview-token' },
      })
    } else if (request.url().endsWith('/v1/frame.jpg')) {
      await route.fulfill({
        status: 200,
        headers: { ...headers, 'Content-Type': 'image/jpeg' },
        body: Buffer.from('/9j/4AAQSkZJRgABAQAAAQABAAD/2Q==', 'base64'),
      })
    } else if (request.url().endsWith('/v1/status')) {
      await route.fulfill({
        status: 200,
        headers,
        json: {
          camera_open: true,
          session_active: true,
          recognition_state: 'accepted',
          display_name: 'Yoga',
          updated_at: Date.now() / 1000,
        },
      })
    } else {
      await route.fulfill({ status: 200, headers, json: { closed: true } })
    }
  })

  await page.goto('/auth/login')
  await page.getByLabel('Email sekolah').fill('admin@example.test')
  await page.getByLabel('Kata sandi').fill('synthetic-password')
  await page.getByRole('button', { name: 'Masuk' }).click()
  await expect(page).toHaveURL(/\/app\/dashboard$/)
  await expect(page.getByTestId('devices-link')).toBeVisible({ timeout: 5000 })
  await page.getByTestId('devices-link').click()
  await expect(page.getByRole('heading', { name: 'Registry perangkat' })).toBeVisible()
  await page.getByRole('link', { name: 'Preview kamera' }).click()

  await expect(page.getByRole('heading', { name: 'Preview kamera presensi' })).toBeVisible()
  await expect(page.getByRole('img', { name: 'Preview langsung kamera presensi' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Yoga' })).toBeVisible()
  await expect(page.getByText(/Presensi menunggu validasi Core API/)).toBeVisible()
  await expect(page.getByRole('img')).toHaveCount(1)
})
