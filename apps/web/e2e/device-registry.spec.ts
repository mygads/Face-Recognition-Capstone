import { expect, test, type Page } from '@playwright/test'
import { stubNoActiveBrowserSession } from './session-fixture'

const deviceId = 'f0591f13-e2ab-4b6e-8ba2-23ebca5d18ce'

async function loginAsAdmin(page: Page): Promise<void> {
  await stubNoActiveBrowserSession(page)
  await page.route('**/api/v1/sessions?**', (route) =>
    route.fulfill({
      status: 200,
      json: { items: [], pagination: { total: 0, limit: 100, offset: 0 } },
    }),
  )
  await page.route('**/api/v1/auth/login', (route) =>
    route.fulfill({
      status: 200,
      json: {
        access_token: 'synthetic-device-registry-token',
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
      },
    }),
  )

  await page.goto('/auth/login?redirect=/app/devices')
  await page.getByLabel('Email sekolah').fill('admin@example.test')
  await page.getByLabel('Kata sandi').fill('synthetic-password')
  await page.getByRole('button', { name: 'Masuk' }).click()
  await expect(page).toHaveURL(/\/app\/devices$/)
}

test('AI_EDGE admin confirms device removal and can inspect the inactive device', async ({
  page,
}) => {
  let isActive = true
  let deleteRequests = 0
  const device = {
    device_id: deviceId,
    laboratory_id: 'synthetic-lab-id',
    laboratory_code: 'K-1',
    laboratory_name: 'Kimia 1',
    name: 'tes-perangkat1',
    device_type: 'edge_pc',
    deployment_profile: 'AI_EDGE',
    app_version: null,
    model_version: null,
    camera_status: 'unknown',
    camera_enabled: true,
    latency_summary: null,
    config_applied_revision: 0,
    config_apply_status: 'not_configured',
    config_error_code: null,
    health_status: 'offline',
    heartbeat_timeout_seconds: 60,
    is_active: true,
    last_seen_at: null,
    created_at: '2026-10-01T00:00:00Z',
  }

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
  await page.route('**/api/v1/laboratories?**', (route) =>
    route.fulfill({
      status: 200,
      json: { items: [], pagination: { total: 0, limit: 100, offset: 0 } },
    }),
  )
  await page.route('**/api/v1/devices**', async (route) => {
    const request = route.request()
    if (request.method() === 'DELETE') {
      deleteRequests += 1
      isActive = false
      return route.fulfill({ status: 204 })
    }
    const url = new URL(request.url())
    const activeFilter = url.searchParams.get('is_active')
    const profileFilter = url.searchParams.get('deployment_profile')
    const visible =
      (profileFilter === null || profileFilter === 'AI_EDGE') &&
      (activeFilter === null || String(isActive) === activeFilter)
    return route.fulfill({
      status: 200,
      json: {
        items: visible ? [{ ...device, is_active: isActive }] : [],
        pagination: { total: visible ? 1 : 0, limit: 10, offset: 0 },
      },
    })
  })

  await loginAsAdmin(page)
  await expect(page.getByText('tes-perangkat1')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Daftarkan perangkat' })).toHaveCount(0)

  await page.getByRole('button', { name: 'Hapus', exact: true }).click()
  const confirmation = page.getByRole('alertdialog')
  await expect(confirmation).toContainText('Data presensi dan audit lama tetap tersimpan')
  await expect(confirmation.getByRole('button', { name: 'Ya, hapus perangkat' })).toBeVisible()
  expect(deleteRequests).toBe(0)

  await confirmation.getByRole('button', { name: 'Ya, hapus perangkat' }).click()
  await expect(page.getByText('Belum ada perangkat yang cocok.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Daftarkan perangkat' })).toBeVisible()
  expect(deleteRequests).toBe(1)

  await page.getByLabel('Tampilkan perangkat nonaktif').check()
  await expect(page.getByText('tes-perangkat1')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Kredensial' })).toBeDisabled()
})

test('AI_EDGE admin can pause and reactivate the camera without removing the device', async ({
  page,
}) => {
  let cameraEnabled = true
  const cameraCommands: boolean[] = []
  const device = {
    device_id: deviceId,
    laboratory_id: 'synthetic-lab-id',
    laboratory_code: 'K-1',
    laboratory_name: 'Kimia 1',
    name: 'tes-perangkat1',
    device_type: 'edge_pc',
    deployment_profile: 'AI_EDGE',
    app_version: null,
    model_version: null,
    camera_status: 'unknown',
    latency_summary: null,
    config_applied_revision: 0,
    config_apply_status: 'not_configured',
    config_error_code: null,
    health_status: 'offline',
    heartbeat_timeout_seconds: 60,
    is_active: true,
    last_seen_at: null,
    created_at: '2026-10-01T00:00:00Z',
  }

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
  await page.route('**/api/v1/laboratories?**', (route) =>
    route.fulfill({
      status: 200,
      json: { items: [], pagination: { total: 0, limit: 100, offset: 0 } },
    }),
  )
  await page.route('**/api/v1/devices**', async (route) => {
    if (route.request().method() === 'PUT') {
      cameraEnabled = Boolean((route.request().postDataJSON() as { enabled: boolean }).enabled)
      cameraCommands.push(cameraEnabled)
      return route.fulfill({ status: 200, json: { ...device, camera_enabled: cameraEnabled } })
    }
    return route.fulfill({
      status: 200,
      json: {
        items: [{ ...device, camera_enabled: cameraEnabled }],
        pagination: { total: 1, limit: 10, offset: 0 },
      },
    })
  })

  await loginAsAdmin(page)
  const row = page.getByRole('row').filter({ hasText: 'tes-perangkat1' })
  await expect(row.getByRole('button', { name: 'Jeda kamera' })).toBeVisible()
  await row.getByRole('button', { name: 'Jeda kamera' }).click()
  const pauseDialog = page.getByRole('dialog')
  await expect(pauseDialog).toContainText('akan berhenti mengambil frame')
  await pauseDialog.getByRole('button', { name: 'Jeda kamera' }).click()
  await expect(row.getByRole('button', { name: 'Aktifkan kamera' })).toBeVisible()
  await expect(row).toContainText('Menunggu agent dijeda')
  expect(cameraEnabled).toBe(false)

  await row.getByRole('button', { name: 'Aktifkan kamera' }).click()
  const activateDialog = page.getByRole('dialog')
  await activateDialog.getByRole('button', { name: 'Aktifkan kamera' }).click()
  await expect(row.getByRole('button', { name: 'Jeda kamera' })).toBeVisible()
  expect(cameraCommands).toEqual([false, true])
})
