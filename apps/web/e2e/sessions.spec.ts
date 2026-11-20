import { expect, test, type Page } from '@playwright/test'
import { stubNoActiveBrowserSession } from './session-fixture'

async function loginAsTeacher(page: Page): Promise<void> {
  await stubNoActiveBrowserSession(page)
  await page.route('**/api/v1/auth/login', (route) =>
    route.fulfill({
      status: 200,
      json: {
        access_token: 'session-test-token',
        token_type: 'bearer',
        expires_in_seconds: 900,
      },
    }),
  )
  await page.route('**/api/v1/auth/me', (route) =>
    route.fulfill({
      status: 200,
      json: {
        id: 'teacher-1',
        email: 'teacher@example.test',
        full_name: 'Guru Praktikum',
        roles: ['TEACHER'],
        permissions: [
          'roster_read',
          'laboratory_read',
          'schedule_read',
          'schedule_manage',
          'session_view',
          'session_operate',
          'attendance_manual',
          'attendance_read',
          'reports_read',
        ],
      },
    }),
  )
  await page.goto('/auth/login')
  await page.getByLabel('Email sekolah').fill('teacher@example.test')
  await page.getByLabel('Kata sandi').fill('synthetic-password')
  await page.getByRole('button', { name: 'Masuk' }).click()
  await expect(page).toHaveURL(/\/app\/dashboard$/)
}

test('teacher opens and manually closes a session with a roster snapshot', async ({ page }) => {
  const timestamp = '2026-10-01T10:00:00Z'
  const policy = {
    mode: 'manual',
    auto_open_minutes_before: 0,
    auto_open_minutes_after: 15,
    default_grace_period_minutes: 15,
    revision: 0,
    updated_at: null,
  }
  let session: Record<string, unknown> | null = null
  // Fallback generik DULU agar tidak menutupi stub spesifik di bawah:
  // request yang belum di-stub tidak boleh jatuh ke API dev lokal (401 -> logout).
  await page.route('**/api/v1/**', (route) =>
    route.fulfill({
      status: 200,
      json: { items: [], pagination: { total: 0, limit: 100, offset: 0 } },
    }),
  )
  await page.route('**/api/v1/sessions**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.pathname.endsWith('/policy')) {
      return route.fulfill({ status: 200, json: policy })
    }
    if (url.pathname.endsWith('/openable-schedules')) {
      return route.fulfill({
        status: 200,
        json: [
          {
            id: 'schedule-1',
            subject: 'Praktikum Biologi',
            class_name: 'Kelas X A',
            laboratory_name: 'Lab Biologi',
            teacher_name: 'Guru Praktikum',
            weekday: 3,
            start_time: '09:00:00',
            end_time: '11:00:00',
            timezone_name: 'Asia/Jakarta',
          },
        ],
      })
    }
    if (request.method() === 'POST' && url.pathname === '/api/v1/sessions') {
      const body = request.postDataJSON() as { grace_period_minutes: number }
      session = {
        id: 'session-1',
        practicum_schedule_id: 'schedule-1',
        status: 'active',
        opened_automatically: false,
        opened_at: timestamp,
        closed_at: null,
        grace_period_minutes: body.grace_period_minutes,
        student_count: 2,
        subject: 'Praktikum Biologi',
        class_name: 'Kelas X A',
        laboratory_name: 'Lab Biologi',
        teacher_name: 'Guru Praktikum',
        weekday: 3,
        start_time: '09:00:00',
        end_time: '11:00:00',
        timezone_name: 'Asia/Jakarta',
        scheduled_end_at: '2026-10-01T04:00:00Z',
      }
      return route.fulfill({ status: 201, json: session })
    }
    if (request.method() === 'POST' && url.pathname.endsWith('/close')) {
      if (session) {
        session.status = 'closed'
        session.closed_at = timestamp
      }
      return route.fulfill({ status: 200, json: session })
    }
    if (request.method() === 'GET' && url.pathname.endsWith('/roster')) {
      return route.fulfill({ status: 200, json: [] })
    }
    if (request.method() === 'GET' && url.pathname.endsWith('/session-1')) {
      return route.fulfill({ status: 200, json: session })
    }
    return route.fulfill({
      status: 200,
      json: {
        items: session ? [session] : [],
        pagination: { total: session ? 1 : 0, limit: 50, offset: 0 },
      },
    })
  })

  await loginAsTeacher(page)
  await page.getByTestId('sessions-link').click()
  await expect(page.getByRole('heading', { name: 'Sesi presensi' })).toBeVisible()
  await page.getByTestId('open-session-schedule-1').click()
  await expect(page.getByRole('dialog')).toContainText('grace 15 mnt')
  await page.getByTestId('confirm-open-session').click()
  await expect(page.locator('p.st-alert--success')).toContainText('2 siswa di roster')
  // Sesi aktif tampil di kartu "Sedang Berlangsung", bukan di tabel riwayat.
  await expect(page.getByTestId('close-session-session-1')).toBeVisible()

  await page.getByTestId('close-session-session-1').click()
  await page.getByTestId('confirm-close-session').click()
  await expect(page.locator('p.st-alert--success')).toContainText('telah ditutup')
  // Sesi yang ditutup pindah ke tabel "Riwayat Sesi Terakhir".
  await expect(page.getByRole('cell', { name: /Praktikum Biologi/ })).toBeVisible()
  await expect(page.getByRole('cell', { name: /grace 15 mnt/ })).toBeVisible()
  await expect(page.getByRole('cell', { name: 'Ditutup' })).toBeVisible()
})

test('admin can configure the automatic opening window', async ({ page }) => {
  const timestamp = '2026-10-05T02:05:00Z'
  let policy: Record<string, unknown> = {
    mode: 'manual',
    auto_open_minutes_before: 0,
    auto_open_minutes_after: 15,
    default_grace_period_minutes: 15,
    revision: 0,
    updated_at: null,
  }
  let ewsPolicy: Record<string, unknown> = {
    window_days: 30,
    absence_pct_threshold: 20,
    late_count_threshold: 3,
  }

  await stubNoActiveBrowserSession(page)
  await page.route('**/api/v1/auth/login', (route) =>
    route.fulfill({
      status: 200,
      json: {
        access_token: 'automatic-session-admin-token',
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
        full_name: 'Admin Presensi',
        roles: ['ADMIN'],
        permissions: [
          'manage_master_data',
          'manage_accounts',
          'manage_settings',
          'roster_read',
          'laboratory_read',
          'device_operate',
          'schedule_read',
          'schedule_manage',
          'session_view',
          'session_operate',
          'enrollment_manage',
          'attendance_manual',
          'attendance_read',
          'reports_read',
        ],
      },
    }),
  )
  await page.route('**/api/v1/sessions/policy', async (route) => {
    const request = route.request()
    if (request.method() === 'PUT') {
      policy = {
        ...(request.postDataJSON() as Record<string, unknown>),
        revision: Number(policy['revision']) + 1,
        updated_at: timestamp,
      }
    }
    return route.fulfill({ status: 200, json: policy })
  })
  await page.route('**/api/v1/reports/attendance/at-risk/policy', async (route) => {
    const request = route.request()
    if (request.method() === 'PUT') {
      ewsPolicy = { ...(request.postDataJSON() as Record<string, unknown>) }
    }
    return route.fulfill({ status: 200, json: ewsPolicy })
  })

  await page.goto('/auth/login?redirect=/app/attendance-policy')
  await page.getByLabel('Email sekolah').fill('admin@example.test')
  await page.getByLabel('Kata sandi').fill('synthetic-password')
  await page.getByRole('button', { name: 'Masuk' }).click()
  await expect(page).toHaveURL(/\/app\/attendance-policy$/)
  await expect(page.getByRole('heading', { name: 'Kebijakan Presensi Laboratorium' })).toBeVisible()

  await page.getByTestId('policy-before').fill('10')
  await page.getByTestId('policy-after').fill('5')
  await page.getByTestId('policy-save').click()

  await expect(page.getByRole('status')).toContainText('Kebijakan tersimpan')
  expect(policy).toMatchObject({
    auto_open_minutes_before: 10,
    auto_open_minutes_after: 5,
  })
})
