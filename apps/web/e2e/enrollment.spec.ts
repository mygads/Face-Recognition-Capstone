import { expect, test, type Page } from '@playwright/test'

const classId = 'class-enrollment-1'
const roster = [
  {
    id: 'student-enrollment-1',
    student_number: 'S-101',
    full_name: 'Synthetic Student One',
  },
  {
    id: 'student-enrollment-2',
    student_number: 'S-102',
    full_name: 'Synthetic Student Two',
  },
  {
    id: 'student-enrollment-3',
    student_number: 'S-103',
    full_name: 'Synthetic Student Three',
  },
]

async function loginAsLaborant(page: Page): Promise<void> {
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
        id: 'laborant-1',
        email: 'laborant@example.test',
        full_name: 'Laboran Praktikum',
        roles: ['LABORANT'],
      },
    }),
  )
  await page.goto('/auth/login')
  await page.getByLabel('Email sekolah').fill('laborant@example.test')
  await page.getByLabel('Kata sandi').fill('synthetic-password')
  await page.getByRole('button', { name: 'Masuk' }).click()
  await expect(page).toHaveURL(/\/app\/dashboard$/)
}

test('laborant captures a student, confirms identity, and advances to the next student', async ({
  page,
}) => {
  await page.addInitScript(() => {
    const canvas = document.createElement('canvas')
    canvas.width = 640
    canvas.height = 480
    const context = canvas.getContext('2d')
    if (context) {
      context.fillStyle = '#48627c'
      context.fillRect(0, 0, canvas.width, canvas.height)
    }
    const stream = canvas.captureStream(12)
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: async () => stream },
    })
  })

  const templateStatus: Record<string, 'not_enrolled' | 'enrolled' | 'needs_reenrollment'> = {
    [roster[0].id]: 'not_enrolled',
    [roster[1].id]: 'needs_reenrollment',
    [roster[2].id]: 'enrolled',
  }

  await page.route('**/api/v1/classes?**', (route) =>
    route.fulfill({
      status: 200,
      json: {
        items: [
          {
            id: classId,
            code: 'X-A',
            name: 'Kelas X A',
            grade: 10,
            academic_year: '2026-2027',
            homeroom_teacher_id: null,
            is_active: true,
            created_at: '2026-10-01T00:00:00Z',
            updated_at: '2026-10-01T00:00:00Z',
          },
        ],
        pagination: { total: 1, limit: 100, offset: 0 },
      },
    }),
  )
  await page.route('**/api/v1/enrollments/class-status?**', (route) =>
    route.fulfill({
      status: 200,
      json: roster.map((student) => ({ ...student, template_status: templateStatus[student.id] })),
    }),
  )
  await page.route('**/api/v1/enrollments/captures', async (route) => {
    const request = route.request()
    expect(request.method()).toBe('POST')
    expect(request.headers()['content-type']).toContain('multipart/form-data')
    const payload = request.postDataBuffer()?.toString('latin1') ?? ''
    expect(payload.match(/name="captures"/g)).toHaveLength(4)
    templateStatus[roster[0].id] = 'enrolled'
    await route.fulfill({
      status: 201,
      json: {
        student_id: roster[0].id,
        template_status: 'enrolled',
        accepted_frames: 4,
        rejected_frames: 0,
        confirmation_required: true,
      },
    })
  })

  await loginAsLaborant(page)
  await page.getByTestId('enrollment-link').click()
  await expect(page.getByRole('heading', { name: 'Pilih kelas dan siswa' })).toBeVisible()
  await expect(
    page.getByTestId(`enrollment-student-${roster[0].id}`).getByText('Belum terdaftar'),
  ).toBeVisible()
  await expect(
    page.getByTestId(`enrollment-student-${roster[1].id}`).getByText('Perlu daftar ulang'),
  ).toBeVisible()
  await expect(
    page.getByTestId(`enrollment-student-${roster[2].id}`).getByText('Terdaftar'),
  ).toBeVisible()

  await page.getByTestId('start-enrollment-capture').click()
  await expect(page.getByTestId('enrollment-camera')).toBeVisible()
  await expect(page.getByText(/capture dimulai dalam 3 detik/i)).toBeVisible()
  await expect(page.getByText('Pengambilan 1 dari 4.')).toBeVisible({ timeout: 5000 })
  await expect(page.getByText(/4 dari 4 capture siap/i)).toBeVisible({ timeout: 10_000 })
  await expect(page.getByText(/embedding|similarity|threshold/i)).toHaveCount(0)

  const confirmButton = page.getByTestId('confirm-enrollment-identity')
  await expect(confirmButton).toBeDisabled()
  await page.getByLabel(/Saya memastikan siswa di kamera adalah Synthetic Student One/).check()
  await confirmButton.click()

  await expect(page.getByTestId(`enrollment-student-${roster[1].id}`)).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  await expect(page.getByRole('status')).toContainText('Synthetic Student Two dipilih')
})
