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

async function stubSettingsApi(page: Page): Promise<void> {
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
        deployment_profile: 'AI_CENTRAL',
        enrollment_models_ready: true,
        enrollment_quality_revision: 0,
        central_ai_status: 'degraded',
        central_ai_models_ready: true,
        central_ai_model_version: 'synthetic-model-v1',
        central_ai_thresholds_configured: false,
        central_ai_recognition_ready: false,
        central_ai_config_desired_revision: 0,
        central_ai_config_applied_revision: 0,
        central_ai_config_sync_status: 'pending',
      },
    }),
  )
  await page.route('**/api/v1/devices?**', (route) =>
    route.fulfill({
      status: 200,
      json: { items: [], pagination: { total: 0, limit: 100, offset: 0 } },
    }),
  )
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
