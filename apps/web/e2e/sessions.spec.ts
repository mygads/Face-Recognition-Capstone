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
  let session: Record<string, unknown> | null = null
  await page.route('**/api/v1/sessions**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
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
  await page.getByLabel('Grace period dalam menit').fill('5')
  await page.getByTestId('open-session-schedule-1').click()
  await expect(page.getByRole('status')).toContainText('2 siswa di roster')
  await expect(page.getByRole('cell', { name: /Praktikum Biologi/ })).toBeVisible()
  await expect(page.getByRole('cell', { name: /grace 5 menit/ })).toBeVisible()

  await page.getByRole('button', { name: 'Tutup sesi' }).click()
  await expect(page.getByRole('cell', { name: 'Ditutup' })).toBeVisible()
  await expect(page.getByRole('status')).toContainText('telah ditutup')
})
