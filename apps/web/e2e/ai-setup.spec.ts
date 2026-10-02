import { expect, test, type Page } from '@playwright/test'
import { stubNoActiveBrowserSession } from './session-fixture'

const calibrationReference = 'LAB-CALIBRATION-2026-01'

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
        access_token: 'synthetic-ai-settings-token',
        token_type: 'bearer',
        expires_in_seconds: 900,
      },
    }),
  )
  await page.route('**/api/v1/auth/me', (route) =>
    route.fulfill({
      status: 200,
      json: {
        id: 'admin-settings-test',
        email: 'admin@example.test',
        full_name: 'Synthetic Administrator',
        roles: ['ADMIN'],
      },
    }),
  )

  await page.goto('/auth/login')
  await page.getByLabel('Email sekolah').fill('admin@example.test')
  await page.getByLabel('Kata sandi').fill('synthetic-password')
  await page.getByRole('button', { name: 'Masuk' }).click()
  await expect(page).toHaveURL(/\/app\/dashboard$/)
  await page.getByTestId('ai-setup-link').click()
  await expect(page).toHaveURL(/\/app\/ai-setup$/)
}

type MockDevice = {
  id: string
  device_id: string
  name: string
  deployment_profile: 'AI_EDGE' | 'STB_GATEWAY'
  is_active: boolean
  laboratory_code: string
  laboratory_name: string
  model_version: string | null
  camera_status: string
  health_status: string
  config_apply_status: 'not_configured' | 'pending' | 'applied' | 'error'
  config_applied_revision: number
  config_error_code: string | null
}

async function stubSettingsApi(
  page: Page,
  profile: 'AI_EDGE' | 'AI_CENTRAL' = 'AI_CENTRAL',
  deviceItems: MockDevice[] = [],
): Promise<void> {
  const recognitionSettings = {
    min_face_pixels: 80,
    min_laplacian_variance: 45,
    min_brightness: 25,
    max_brightness: 235,
    min_top1_similarity: null,
    min_top1_top2_margin: null,
    minimum_agreeing_frames: 3,
    sample_every_n_frames: 5,
    best_frame_count: 5,
    max_history_frames: 10,
    calibration_reference: null,
  }
  const enrollmentSettings = {
    min_face_pixels: 80,
    min_sharpness: 45,
    min_brightness: 25,
    max_brightness: 235,
  }

  await page.route('**/api/v1/admin/system/ai-readiness', (route) =>
    route.fulfill({
      status: 200,
      json: {
        deployment_profile: profile,
        enrollment_models_ready: true,
        enrollment_quality_revision: 0,
        central_ai_status: profile === 'AI_CENTRAL' ? 'degraded' : 'disabled',
        central_ai_models_ready: profile === 'AI_CENTRAL' ? true : null,
        central_ai_model_version: profile === 'AI_CENTRAL' ? 'synthetic-model-v1' : null,
        central_ai_thresholds_configured: profile === 'AI_CENTRAL' ? false : null,
        central_ai_recognition_ready: profile === 'AI_CENTRAL' ? false : null,
        central_ai_config_desired_revision: profile === 'AI_CENTRAL' ? 0 : null,
        central_ai_config_applied_revision: profile === 'AI_CENTRAL' ? 0 : null,
        central_ai_config_sync_status: profile === 'AI_CENTRAL' ? 'pending' : null,
      },
    }),
  )
  await page.route('**/api/v1/devices?**', (route) =>
    route.fulfill({
      status: 200,
      json: {
        items: deviceItems,
        pagination: { total: deviceItems.length, limit: 100, offset: 0 },
      },
    }),
  )
  await page.route('**/api/v1/admin/settings/devices/**', (route) => {
    const method = route.request().method()
    const deviceConfiguration = route.request().url().includes('/device-edge')
    const settings = method === 'PUT' ? route.request().postDataJSON() : recognitionSettings
    return route.fulfill({
      status: 200,
      json: {
        device_id: 'device-edge',
        deployment_profile: deviceConfiguration ? 'AI_EDGE' : 'STB_GATEWAY',
        revision: method === 'PUT' ? 1 : 0,
        settings,
        applied_revision: 0,
        apply_status: method === 'PUT' ? 'pending' : 'not_configured',
        error_code: null,
        updated_at: null,
      },
    })
  })
  await page.route('**/api/v1/admin/settings/enrollment-quality', (route) => {
    if (route.request().method() === 'GET') {
      return route.fulfill({
        status: 200,
        json: {
          scope_key: 'enrollment',
          revision: 0,
          settings: enrollmentSettings,
          updated_at: null,
        },
      })
    }
    return route.fulfill({
      status: 200,
      json: {
        scope_key: 'enrollment',
        revision: 1,
        settings: route.request().postDataJSON(),
        updated_at: '2026-10-02T00:00:00Z',
      },
    })
  })
  await page.route('**/api/v1/admin/settings/ai-central', (route) => {
    if (route.request().method() === 'GET') {
      return route.fulfill({
        status: 200,
        json: {
          scope_key: 'AI_CENTRAL',
          revision: 0,
          settings: recognitionSettings,
          updated_at: null,
        },
      })
    }

    const settings = route.request().postDataJSON() as Record<string, unknown>
    if (settings.calibration_reference !== calibrationReference) {
      return route.fulfill({
        status: 422,
        json: {
          error: {
            code: 'calibration_reference_required',
            message: 'Isi referensi laporan kalibrasi sebelum menyimpan threshold.',
          },
        },
      })
    }
    return route.fulfill({
      status: 200,
      json: {
        scope_key: 'AI_CENTRAL',
        revision: 1,
        settings,
        updated_at: '2026-10-02T00:00:00Z',
      },
    })
  })
}

test('admin can publish enrollment quality settings from the dashboard', async ({ page }) => {
  await stubSettingsApi(page)
  await loginAsAdmin(page)

  await expect(page.getByRole('heading', { name: 'AI & kamera' }).first()).toBeVisible()
  await page.getByLabel('Ukuran wajah minimum (piksel)').fill('96')
  await page.getByRole('button', { name: 'Simpan pengaturan enrollment' }).click()

  await expect(page.getByRole('status')).toContainText('Kualitas enrollment diterbitkan')
  await expect(page.getByText('Core API · revisi 1')).toBeVisible()
})

test('central thresholds require a calibration reference before publish', async ({ page }) => {
  await stubSettingsApi(page)
  await loginAsAdmin(page)
  await page.getByRole('button', { name: 'AI Central' }).click()

  await page.getByLabel('Top-1 similarity').fill('0.74')
  await page.getByLabel('Margin Top-1 − Top-2').fill('0.08')
  await page.getByRole('button', { name: 'Simpan dan terapkan' }).click()
  await expect(page.getByRole('alert')).toContainText('laporan kalibrasi')

  await page.getByLabel('Referensi laporan kalibrasi').fill(calibrationReference)
  await page.getByRole('button', { name: 'Simpan dan terapkan' }).click()
  await expect(page.getByRole('status')).toContainText('Pengaturan AI Central diterbitkan')
})

test('edge profile hides central settings and lists only active edge devices', async ({ page }) => {
  const devices: MockDevice[] = [
    {
      id: 'device-edge',
      device_id: 'device-edge',
      name: 'tes-local',
      deployment_profile: 'AI_EDGE',
      is_active: true,
      laboratory_code: 'K-1',
      laboratory_name: 'Kimia 1',
      model_version: null,
      camera_status: 'unknown',
      health_status: 'offline',
      config_apply_status: 'not_configured',
      config_applied_revision: 0,
      config_error_code: null,
    },
    {
      id: 'deleted-device',
      device_id: 'deleted-device',
      name: 'tes-perangkat1',
      deployment_profile: 'AI_EDGE',
      is_active: false,
      laboratory_code: 'K-1',
      laboratory_name: 'Kimia 1',
      model_version: null,
      camera_status: 'offline',
      health_status: 'offline',
      config_apply_status: 'not_configured',
      config_applied_revision: 0,
      config_error_code: null,
    },
    {
      id: 'gateway-device',
      device_id: 'gateway-device',
      name: 'stb-gateway',
      deployment_profile: 'STB_GATEWAY',
      is_active: true,
      laboratory_code: 'K-2',
      laboratory_name: 'Fisika 1',
      model_version: null,
      camera_status: 'offline',
      health_status: 'offline',
      config_apply_status: 'not_configured',
      config_applied_revision: 0,
      config_error_code: null,
    },
  ]
  await stubSettingsApi(page, 'AI_EDGE', devices)
  await loginAsAdmin(page)

  await expect(page.getByText('AI Central', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Tidak digunakan pada profile ini')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'AI Central' })).toHaveCount(0)
  await expect(page.getByText('tes-local')).toBeVisible()
  await expect(page.getByText('tes-perangkat1')).toHaveCount(0)
  await expect(page.getByText('stb-gateway')).toHaveCount(0)

  await page.getByRole('button', { name: 'PC edge' }).click()
  await expect(page.getByRole('heading', { name: 'Perangkat AI_EDGE' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Pratinjau konfigurasi' })).toBeVisible()
  await expect(page.getByText('Belum aktif — menunggu kalibrasi')).toBeVisible()
  await page.getByRole('button', { name: 'Terapkan ke perangkat' }).click()
  await expect(
    page.getByText('Konfigurasi perangkat diterbitkan. Perangkat menerapkannya saat tersambung.'),
  ).toBeVisible()
  await expect(page.getByText('Belum aktif — menunggu kalibrasi')).toBeVisible()
})
