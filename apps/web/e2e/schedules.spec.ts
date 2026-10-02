import { expect, test, type Page } from '@playwright/test'
import { stubNoActiveBrowserSession } from './session-fixture'

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
        access_token: 'schedule-test-token',
        token_type: 'bearer',
        expires_in_seconds: 900,
      },
    }),
  )
  await page.route('**/api/v1/auth/me', (route) =>
    route.fulfill({
      status: 200,
      json: {
        id: 'admin-1',
        email: 'admin@example.test',
        full_name: 'Test Administrator',
        roles: ['ADMIN'],
      },
    }),
  )
  await page.goto('/auth/login')
  await page.getByLabel('Email sekolah').fill('admin@example.test')
  await page.getByLabel('Kata sandi').fill('synthetic-password')
  await page.getByRole('button', { name: 'Masuk' }).click()
  await expect(page).toHaveURL(/\/app\/dashboard$/)
}

test('shows schedule conflict and saves a corrected schedule', async ({ page }) => {
  let schedule: Record<string, unknown> | null = null
  let createAttempt = 0
  const timestamp = '2026-10-01T00:00:00Z'

  await page.route('**/api/v1/classes**', (route) =>
    route.fulfill({
      status: 200,
      json: {
        items: [
          {
            id: 'class-1',
            code: 'X-A',
            name: 'Kelas X A',
            grade: 10,
            academic_year: '2026-2027',
            homeroom_teacher_id: null,
            is_active: true,
            created_at: timestamp,
            updated_at: timestamp,
          },
        ],
        pagination: { total: 1, limit: 100, offset: 0 },
      },
    }),
  )
  await page.route('**/api/v1/laboratories**', (route) =>
    route.fulfill({
      status: 200,
      json: {
        items: [
          {
            id: 'lab-1',
            code: 'LAB-A',
            name: 'Lab Biologi',
            location: null,
            is_active: true,
            created_at: timestamp,
            updated_at: timestamp,
          },
        ],
        pagination: { total: 1, limit: 100, offset: 0 },
      },
    }),
  )
  await page.route('**/api/v1/schedules**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.pathname.endsWith('/teachers')) {
      return route.fulfill({
        status: 200,
        json: [{ id: 'teacher-1', full_name: 'Guru Praktikum' }],
      })
    }
    if (request.method() === 'POST') {
      createAttempt += 1
      if (createAttempt === 1) {
        return route.fulfill({
          status: 409,
          json: {
            error: {
              code: 'schedule_conflict',
              message:
                'Jadwal bertabrakan untuk kelas, laboratorium, atau guru pada waktu yang sama.',
            },
          },
        })
      }
      const body = request.postDataJSON() as Record<string, unknown>
      schedule = {
        ...body,
        id: 'schedule-1',
        class_name: 'Kelas X A',
        laboratory_name: 'Lab Biologi',
        teacher_name: 'Guru Praktikum',
        effective_through: null,
        is_active: true,
        created_at: timestamp,
        updated_at: timestamp,
      }
      return route.fulfill({ status: 201, json: schedule })
    }
    return route.fulfill({
      status: 200,
      json: {
        items: schedule ? [schedule] : [],
        pagination: { total: schedule ? 1 : 0, limit: 10, offset: 0 },
      },
    })
  })

  await loginAsAdmin(page)
  await page.getByTestId('schedules-link').click()
  await expect(page.getByRole('heading', { name: 'Jadwal praktikum' })).toBeVisible()
  await page.getByTestId('create-schedule').click()
  await page.getByLabel('Mata pelajaran').fill('Praktikum Biologi')
  await page.getByLabel('Kelas').selectOption('class-1')
  await page.getByLabel('Laboratorium').selectOption('lab-1')
  await page.getByLabel('Guru').selectOption('teacher-1')
  await page.getByLabel('Jam mulai').fill('09:00')
  await page.getByLabel('Jam selesai').fill('10:00')

  await page.getByRole('button', { name: 'Simpan jadwal' }).click()
  await expect(page.getByRole('alert')).toContainText('Jadwal bertabrakan')
  await page.getByLabel('Jam mulai').fill('10:00')
  await page.getByLabel('Jam selesai').fill('11:00')
  await page.getByRole('button', { name: 'Simpan jadwal' }).click()

  await expect(page.getByRole('cell', { name: 'Praktikum Biologi' })).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
})
