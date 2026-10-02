import { expect, test, type Page } from '@playwright/test'
import { stubNoActiveBrowserSession } from './session-fixture'

const sessionId = '6f512941-780f-4650-a720-6d0bdd5635bf'
const studentId = '0d32e04f-676e-4a84-a781-78ebd7c373a6'

async function signInAsTeacher(page: Page): Promise<void> {
  await stubNoActiveBrowserSession(page)
  await page.route('**/api/v1/auth/login', async (route) => {
    await route.fulfill({
      status: 200,
      json: { access_token: 'e2e-report-token', token_type: 'bearer', expires_in_seconds: 900 },
    })
  })
  await page.route('**/api/v1/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      json: {
        id: 'a5268097-f1f8-4557-9680-cc5337882249',
        email: 'teacher@example.test',
        full_name: 'Test Teacher',
        roles: ['TEACHER'],
      },
    })
  })
  await page.goto('/auth/login')
  await page.getByLabel('Email sekolah').fill('teacher@example.test')
  await page.getByLabel('Kata sandi').fill('e2e-password')
  await page.getByRole('button', { name: 'Masuk' }).click()
  await expect(page).toHaveURL(/\/app\/dashboard$/)
}

test('teacher can filter attendance and download a CSV report', async ({ page }) => {
  const row = {
    attendance_record_id: '281718b7-d74f-4fd4-9a55-110f0a4ed1c2',
    session_id: sessionId,
    student_id: studentId,
    student_number: 'S-001',
    student_name: 'Synthetic Student',
    class_id: '46aa4453-6e80-4b14-9b6a-82c1daeeded1',
    class_code: 'X-A',
    class_name: 'Kelas X-A',
    laboratory_id: 'c9c1822e-5be0-4a9a-9de9-f8944cf9b949',
    laboratory_code: 'LAB-A',
    laboratory_name: 'Lab A',
    subject: 'Kimia',
    teacher_name: 'Test Teacher',
    status: 'present',
    source: 'manual',
    session_opened_at: '2026-09-15T02:00:00Z',
    recorded_at: '2026-09-15T02:10:00Z',
  }
  await page.route('**/api/v1/schedules*', async (route) => {
    await route.fulfill({
      status: 200,
      json: {
        items: [
          {
            id: '2e63da03-bcbc-47ec-8f2a-55a39440cf96',
            class_id: row.class_id,
            laboratory_id: row.laboratory_id,
            teacher_user_id: 'a5268097-f1f8-4557-9680-cc5337882249',
            subject: 'Kimia',
            weekday: 1,
            start_time: '09:00:00',
            end_time: '10:00:00',
            timezone_name: 'Asia/Jakarta',
            effective_from: '2026-01-01',
            effective_through: null,
            is_active: true,
            class_name: 'Kelas X-A',
            laboratory_name: 'Lab A',
            teacher_name: 'Test Teacher',
            created_at: row.session_opened_at,
            updated_at: row.session_opened_at,
          },
        ],
        pagination: { total: 1, limit: 100, offset: 0 },
      },
    })
  })
  await page.route('**/api/v1/sessions*', async (route) => {
    await route.fulfill({
      status: 200,
      json: {
        items: [
          {
            id: sessionId,
            practicum_schedule_id: '3db9a1ba-fbd7-4554-8d56-378ef9fe1cb2',
            status: 'active',
            opened_at: row.session_opened_at,
            closed_at: '2026-09-15T03:00:00Z',
            grace_period_minutes: 15,
            student_count: 1,
            subject: 'Kimia',
            class_name: 'Kelas X-A',
            laboratory_name: 'Lab A',
            teacher_name: 'Test Teacher',
            weekday: 1,
            start_time: '09:00:00',
            end_time: '10:00:00',
            timezone_name: 'Asia/Jakarta',
            scheduled_end_at: '2026-09-15T03:00:00Z',
          },
        ],
        pagination: { total: 1, limit: 100, offset: 0 },
      },
    })
  })
  await page.route('**/api/v1/sessions/*/dashboard', async (route) => {
    await route.fulfill({
      status: 200,
      json: {
        session_id: sessionId,
        session_status: 'active',
        generated_at: '2026-09-15T02:20:00Z',
        summary: { total_roster: 1, present: 1, late: 0, not_present: 0 },
        devices: [],
        recent_activity: [],
      },
    })
  })
  await page.route('**/api/v1/devices*', async (route) => {
    await route.fulfill({
      status: 200,
      json: { items: [], pagination: { total: 0, limit: 100, offset: 0 } },
    })
  })
  await page.route('**/api/v1/reports/attendance?*', async (route) => {
    await route.fulfill({
      status: 200,
      json: {
        starts_on: '2026-09-01',
        ends_on: '2026-09-30',
        total_rows: 1,
        present_count: 1,
        late_count: 0,
        absent_count: 0,
        excused_count: 0,
        not_recorded_count: 0,
        generated_at: '2026-09-30T10:00:00Z',
      },
    })
  })
  await page.route('**/api/v1/reports/attendance/records?*', async (route) => {
    const requested = new URL(route.request().url())
    expect(requested.searchParams.get('starts_on')).toBeTruthy()
    expect(requested.searchParams.get('ends_on')).toBeTruthy()
    if (requested.searchParams.has('student_number')) {
      expect(requested.searchParams.get('student_number')).toBe('S-001')
    }
    await route.fulfill({
      status: 200,
      json: { items: [row], pagination: { total: 1, limit: 20, offset: 0 } },
    })
  })
  await page.route('**/api/v1/reports/attendance/export?*', async (route) => {
    const requested = new URL(route.request().url())
    expect(requested.searchParams.get('format')).toBe('csv')
    await route.fulfill({
      status: 200,
      body: '\ufeffWaktu sesi,NIS/NISN,Nama siswa\r\n2026-09-15T02:00:00Z,S-001,Synthetic Student\r\n',
      headers: {
        'content-type': 'text/csv; charset=utf-8',
        'content-disposition': "attachment; filename*=UTF-8''attendance-2026-09-01-2026-09-30.csv",
      },
    })
  })

  await signInAsTeacher(page)
  await page.getByTestId('reports-link').click()
  await expect(page).toHaveURL(/\/app\/reports$/)
  await expect(page.getByRole('heading', { name: 'Laporan kehadiran' })).toBeVisible()
  await page.getByLabel('Filter siswa').fill('S-001')
  await page.getByRole('button', { name: 'Terapkan filter' }).click()
  await expect(page.getByText('Synthetic Student', { exact: true })).toBeVisible()
  await expect(page.locator('.reports__status')).toHaveText('Hadir')

  const downloadPromise = page.waitForEvent('download')
  await page.getByTestId('export-csv').click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toBe('attendance-2026-09-01-2026-09-30.csv')
  const stream = await download.createReadStream()
  expect(stream).not.toBeNull()
  let downloadedText = ''
  for await (const chunk of stream!) downloadedText += chunk.toString()
  expect(downloadedText).toContain('Synthetic Student')
})
