import { expect, test, type Page } from '@playwright/test'
import { stubNoActiveBrowserSession } from './session-fixture'

const timestamp = '2026-10-01T10:00:00Z'

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
          'attendance_read',
          'attendance_correct',
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

test('teacher sees live roster counts on the active session card and detail', async ({ page }) => {
  // Fallback generik DULU agar request yang belum di-stub tidak jatuh ke API dev lokal (401 -> logout).
  await page.route('**/api/v1/**', (route) => {
    return route.fulfill({
      status: 200,
      json: { items: [], pagination: { total: 0, limit: 100, offset: 0 } },
    })
  })

  let presentCount = 1
  const session = {
    id: 'session-1',
    practicum_schedule_id: 'schedule-1',
    status: 'active',
    opened_at: timestamp,
    closed_at: null,
    opened_automatically: false,
    grace_period_minutes: 15,
    student_count: 3,
    subject: 'Praktikum Biologi',
    class_name: 'Kelas X A',
    laboratory_name: 'Lab Biologi',
    teacher_name: 'Guru Praktikum',
    teacher_user_id: 'teacher-1',
    weekday: 3,
    start_time: '09:00:00',
    end_time: '11:00:00',
    timezone_name: 'Asia/Jakarta',
    scheduled_end_at: timestamp,
  }
  const rosterEntries = () =>
    [
      { student_id: 'student-1', student_number: 'S-001', full_name: 'Siswa Satu' },
      { student_id: 'student-2', student_number: 'S-002', full_name: 'Siswa Dua' },
      { student_id: 'student-3', student_number: 'S-003', full_name: 'Siswa Tiga' },
    ].map((entry, index) => ({
      ...entry,
      record_status: index < presentCount ? 'present' : null,
      record_note: null,
      recorded_at: index < presentCount ? timestamp : null,
      minutes_late: null,
      attendance_record_id: index < presentCount ? `record-${index}` : null,
    }))

  await page.route('**/api/v1/sessions**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/policy')) {
      return route.fulfill({
        status: 200,
        json: { mode: 'manual', default_grace_period_minutes: 15 },
      })
    }
    if (url.pathname.endsWith('/openable-schedules')) {
      return route.fulfill({ status: 200, json: [] })
    }
    if (url.pathname.endsWith('/session-1/roster') && route.request().method() === 'GET') {
      return route.fulfill({ status: 200, json: rosterEntries() })
    }
    if (url.pathname.endsWith('/sessions/session-1') && route.request().method() === 'GET') {
      return route.fulfill({ status: 200, json: session })
    }
    if (url.pathname === '/api/v1/sessions' && route.request().method() === 'GET') {
      return route.fulfill({
        status: 200,
        json: { items: [session], pagination: { total: 1, limit: 50, offset: 0 } },
      })
    }
    return route.fulfill({ status: 404, json: { error: { code: 'not_found' } } })
  })

  await loginAsTeacher(page)
  await page.getByTestId('sessions-link').click()
  await expect(page.getByRole('heading', { name: 'Sesi Presensi' })).toBeVisible()

  const livePanel = page.getByLabel('Roster langsung')
  await expect(livePanel).toContainText('Live roster kehadiran')
  await expect(livePanel).toContainText('1 / 3 Terdata')

  await page.getByTestId('show-status-session-1').click()
  await expect(page).toHaveURL(/\/app\/sessions\/session-1$/)
  await expect(page.getByRole('heading', { name: 'Sesi Presensi' })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Detail Sesi: Praktikum Biologi' })).toBeVisible()
  await expect(page.getByTestId('roster-filter-present')).toHaveText('Hadir (1)')
  await expect(page.getByTestId('roster-filter-unmarked')).toHaveText('Belum tercatat (2)')
  await expect(
    page.getByTestId('roster-table').getByText('Siswa Satu', { exact: true }),
  ).toBeVisible()

  // Data roster diambil ulang setiap panel dibuka: simulasi siswa kedua terdata.
  presentCount = 2
  await page.getByRole('button', { name: /Kembali ke daftar sesi/ }).click()
  await expect(page).toHaveURL(/\/app\/sessions$/)
  await page.getByTestId('show-status-session-1').click()
  await expect(page.getByTestId('roster-filter-present')).toHaveText('Hadir (2)')
  await expect(
    page.getByTestId('roster-table').getByText('Siswa Dua', { exact: true }),
  ).toBeVisible()
  // Kartu sesi me-refresh saat halaman dimuat; panel detail mengambil ulang setiap dibuka.
  await expect(page.getByTestId('roster-filter-unmarked')).toHaveText('Belum tercatat (1)')
  await expect(page.getByText(/embedding|foto wajah/i)).toHaveCount(0)

  await page.getByTestId('edit-attendance-student-1').click()
  const attendanceDrawer = page.getByRole('dialog', { name: 'Ubah kehadiran' })
  await expect(attendanceDrawer).toBeVisible()
  await expect(attendanceDrawer).toContainText('Status saat ini: Hadir')
  await page.getByTestId('submit-attendance-edit').click()
  await expect(attendanceDrawer).toContainText('Alasan perubahan wajib diisi')
  await page.getByRole('button', { name: 'Batal' }).click()
  await expect(attendanceDrawer).toHaveCount(0)
})
