import { expect, test, type Page } from '@playwright/test'
import { stubNoActiveBrowserSession } from './session-fixture'

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

async function stubFallbackFirst(page: Page): Promise<void> {
  // Fallback generik DULU agar request yang belum di-stub tidak jatuh ke API dev lokal (401 -> logout).
  await page.route('**/api/v1/**', (route) =>
    route.fulfill({
      status: 200,
      json: { items: [], pagination: { total: 0, limit: 100, offset: 0 } },
    }),
  )
}

async function stubLocalAgentPreview(
  page: Page,
  options: { failFirstStream?: boolean } = {},
): Promise<void> {
  let sessionNumber = 0
  let streamRequestNumber = 0
  const origin = 'http://127.0.0.1:4173'
  const headers = {
    'access-control-allow-origin': origin,
    'access-control-allow-methods': 'GET, POST, DELETE, OPTIONS',
    'access-control-allow-headers': 'Authorization, Content-Type, X-Presensi-Preview-Token',
    'access-control-allow-private-network': 'true',
  }
  const pixel = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO2lA3sAAAAASUVORK5CYII=',
    'base64',
  )
  await page.route('http://127.0.0.1:8765/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (request.method() === 'OPTIONS') {
      return route.fulfill({ status: 204, headers })
    }
    if (url.pathname === '/v1/session' && request.method() === 'POST') {
      return route.fulfill({
        status: 201,
        headers,
        json: { preview_token: `synthetic-agent-token-${++sessionNumber}` },
      })
    }
    if (url.pathname === '/v1/session' && request.method() === 'DELETE') {
      return route.fulfill({ status: 200, headers, json: { closed: true } })
    }
    if (url.pathname === '/v1/status') {
      return route.fulfill({
        status: 200,
        headers,
        json: {
          camera_open: true,
          camera_observation: {
            state: 'ready',
            message: 'Satu wajah siap diperiksa.',
            frame_width: 640,
            frame_height: 480,
            face_count: 1,
            faces: [
              {
                x: 0.25,
                y: 0.12,
                width: 0.5,
                height: 0.7,
                acceptable: true,
                landmarks: [
                  [0.4, 0.35],
                  [0.6, 0.35],
                  [0.5, 0.48],
                  [0.42, 0.6],
                  [0.58, 0.6],
                ],
              },
            ],
          },
        },
      })
    }
    if (url.pathname === '/v1/frame.jpg' || url.pathname === '/v1/stream') {
      if (options.failFirstStream && url.pathname === '/v1/stream' && streamRequestNumber++ === 0) {
        return route.fulfill({ status: 401, headers, json: { error: 'unauthorized' } })
      }
      return route.fulfill({
        status: 200,
        headers: { ...headers, 'content-type': 'image/png' },
        body: pixel,
      })
    }
    return route.fulfill({ status: 404, headers, json: { error: 'not_found' } })
  })
}

async function loginAsLaborant(page: Page): Promise<void> {
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
        permissions: ['roster_read', 'laboratory_read', 'device_operate', 'enrollment_manage'],
      },
    }),
  )
  await page.goto('/auth/login')
  await page.getByLabel('Email sekolah').fill('laborant@example.test')
  await page.getByLabel('Kata sandi').fill('synthetic-password')
  await page.getByRole('button', { name: 'Masuk' }).click()
  await expect(page).toHaveURL(/\/app\/dashboard$/)
}

async function stubEnrollmentRoster(page: Page): Promise<void> {
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
      json: roster.map((student, index) => ({
        ...student,
        template_status: index === 2 ? 'enrolled' : 'not_enrolled',
      })),
    }),
  )
}

test('enrollment reconnects AI_EDGE stream after an expired preview token', async ({ page }) => {
  await stubFallbackFirst(page)
  await stubLocalAgentPreview(page, { failFirstStream: true })
  await stubEnrollmentRoster(page)
  await loginAsLaborant(page)
  await page.getByTestId('enrollment-link').click()

  const stream = page.getByTestId('enrollment-lab-stream')
  await expect(stream).toBeVisible()
  await expect(stream).toHaveAttribute('src', /synthetic-agent-token-2/, { timeout: 8000 })
  await expect(stream).toHaveAttribute('crossorigin', 'anonymous')
  await expect
    .poll(() => stream.evaluate((image) => (image as HTMLImageElement).naturalWidth))
    .toBeGreaterThan(0)
  const corsFrame = await page.evaluate(async () => {
    const response = await fetch('http://127.0.0.1:8765/v1/frame.jpg', {
      headers: { 'X-Presensi-Preview-Token': 'synthetic-agent-token-2' },
    })
    return {
      ok: response.ok,
      type: response.type,
      frameBytes: (await response.blob()).size,
    }
  })
  expect(corsFrame).toEqual({ ok: true, type: 'cors', frameBytes: expect.any(Number) })
  expect(corsFrame.frameBytes).toBeGreaterThan(0)
})

test('laborant captures a student, confirms identity, and advances to the next student', async ({
  page,
}) => {
  await stubFallbackFirst(page)
  await stubLocalAgentPreview(page)
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
        enrollment_batch_id: 'batch-enrollment-1',
        template_status: 'enrolled',
        accepted_frames: 4,
        rejected_frames: 0,
        template_count: 4,
        duplicate_warnings: [
          {
            student_id: roster[2].id,
            student_number: roster[2].student_number,
            full_name: roster[2].full_name,
            similarity: 0.91,
          },
        ],
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

  await expect(page.getByTestId('enrollment-lab-stream')).toBeVisible()
  const toggle = page.locator('.enrollment-view__source-toggle')
  const labCamera = page.locator('.enrollment-view__camera-frame')
  const readCameraBox = () =>
    labCamera.evaluate((element) => {
      const box = element.getBoundingClientRect()
      return {
        x: box.x + window.scrollX,
        y: box.y + window.scrollY,
        width: box.width,
        height: box.height,
      }
    })
  const labBox = await readCameraBox()
  await expect(toggle).toHaveCSS('grid-column-end', '-1')
  await page.getByTestId('enrollment-source-device').check()
  const deviceBox = await readCameraBox()
  expect(deviceBox.x).toBeCloseTo(labBox.x, 0)
  expect(deviceBox.y).toBeCloseTo(labBox.y, 0)
  expect(deviceBox.width).toBeCloseTo(labBox.width, 0)
  expect(deviceBox.height).toBeCloseTo(labBox.height, 0)
  await page.getByTestId('enrollment-source-lab').check()
  await expect(page.getByTestId('enrollment-face-guidance')).toContainText('Wajah siap ditangkap')
  // Fixture agent only has five diagnostic points and a 1px image; it is not
  // a dense local mesh and should not render a misleading face skeleton.
  await expect(page.locator('.face-overlay__skeleton')).toHaveCount(0)
  await expect(page.getByTestId('start-enrollment-capture')).toBeDisabled()
  await page.getByTestId('enrollment-identity-confirmation').check()
  const observedCapturePoses = page.evaluate(
    () =>
      new Promise<string[]>((resolve) => {
        const observed = new Set<string>()
        const collect = () => {
          const text = document.querySelector(
            '[data-testid="enrollment-capture-pose"]',
          )?.textContent
          if (!text) return
          observed.add(text.trim())
          if (text.includes('Kembali menghadap lurus')) {
            observer.disconnect()
            clearTimeout(timeout)
            resolve([...observed])
          }
        }
        const observer = new MutationObserver(collect)
        observer.observe(document.body, { childList: true, subtree: true, characterData: true })
        const timeout = window.setTimeout(() => {
          observer.disconnect()
          resolve([...observed])
        }, 12_000)
        collect()
      }),
  )
  await page.getByTestId('start-enrollment-capture').click()
  await expect(page.getByText(/capture dimulai dalam 3 detik/i)).toBeVisible()
  const capturePoses = (await observedCapturePoses).join(' ')
  expect(capturePoses).toContain('Lihat lurus ke kamera')
  expect(capturePoses).toContain('Putar sedikit ke kiri')
  expect(capturePoses).toContain('Putar sedikit ke kanan')
  expect(capturePoses).toContain('Kembali menghadap lurus')
  await expect(page.getByText(/4 dari 4 frame diterima, 0 tidak digunakan/i)).toBeVisible({
    timeout: 10_000,
  })
  await expect(
    page.getByText(/Ada kemungkinan wajah mirip dengan Synthetic Student Three/),
  ).toBeVisible()
  await expect(page.getByText('0.91')).toHaveCount(0)
  await expect(page.getByText(/embedding|similarity|threshold/i)).toHaveCount(0)

  await expect(page.getByTestId('confirm-enrollment-identity')).toHaveCount(0)
  await expect(page.getByTestId('continue-enrollment')).toBeVisible()
  await page.getByTestId('continue-enrollment').click()

  await expect(page.getByTestId(`enrollment-student-${roster[1].id}`)).toHaveClass(
    /st-list__item--active/,
  )
  await expect(page.locator('p.st-alert--success')).toContainText('Synthetic Student Two dipilih')
})

test('laborant can revoke an active template before re-enrollment', async ({ page }) => {
  await stubFallbackFirst(page)
  const enrolledId = roster[2].id
  let status: 'enrolled' | 'needs_reenrollment' = 'enrolled'
  let revoked = false
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
      json: roster.map((student) => ({
        ...student,
        template_status: student.id === enrolledId ? status : 'not_enrolled',
      })),
    }),
  )
  await page.route('**/api/v1/face-templates?**', (route) =>
    route.fulfill({
      status: 200,
      json: {
        items: revoked
          ? []
          : [
              {
                id: 'template-active-1',
                student_id: enrolledId,
                enrollment_batch_id: 'batch-enrollment-1',
                model_name: 'opencv-zoo-sface',
                model_version: 'model-v1',
                quality_metadata: {},
                created_at: '2026-10-01T00:00:00Z',
                revoked_at: null,
              },
            ],
        pagination: { total: revoked ? 0 : 1, limit: 100, offset: 0 },
      },
    }),
  )
  await page.route('**/api/v1/face-templates/template-active-1/revoke', async (route) => {
    status = 'needs_reenrollment'
    revoked = true
    await route.fulfill({
      status: 200,
      json: {
        student_id: enrolledId,
        enrollment_batch_id: 'batch-enrollment-1',
        revoked_templates: 4,
        revoked_at: '2026-10-01T00:00:00Z',
      },
    })
  })

  await loginAsLaborant(page)
  await page.getByTestId('enrollment-link').click()
  const enrolledStudent = page.getByTestId(`enrollment-student-${enrolledId}`)
  await enrolledStudent.getByRole('button', { name: 'Ambil Ulang' }).click()
  const revokeButton = page.getByTestId('revoke-enrollment-template')
  await expect(revokeButton).toBeEnabled()
  await revokeButton.click()
  await page.getByTestId('revoke-reason-input').fill('Kualitas tangkapan lama kurang baik')
  await page.getByTestId('confirm-revoke-template').click()
  await expect(enrolledStudent).toContainText('Perlu daftar ulang')
  await expect(page.locator('p.st-alert--success')).toContainText(
    'semua acuan wajah aktif sudah dicabut',
  )
  await expect(page.getByTestId('start-enrollment-capture')).toHaveText('Daftar ulang siswa')
})
