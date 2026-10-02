import { expect, test, type Page } from '@playwright/test'
import { stubNoActiveBrowserSession } from './session-fixture'

type ApiStudent = {
  id: string
  student_number: string
  full_name: string
  is_active: boolean
  created_at: string
  updated_at: string
}

type ApiClass = {
  id: string
  code: string
  name: string
  grade: number
  academic_year: string
  homeroom_teacher_id: string | null
  is_active: boolean
  created_at: string
  updated_at: string
  student_ids: string[]
}

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
        access_token: 'master-data-test-token',
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

async function stubMasterDataApi(page: Page): Promise<void> {
  const students: ApiStudent[] = []
  const classes: ApiClass[] = []
  const laboratories: Record<string, unknown>[] = []
  let nextId = 1
  const now = '2026-10-01T00:00:00Z'

  await page.route('**/api/v1/students**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const studentId = url.pathname.split('/')[4]
    if (request.method() === 'GET' && studentId) {
      const student = students.find((item) => item.id === studentId)
      if (!student)
        return route.fulfill({
          status: 404,
          json: { error: { code: 'not_found', message: 'Not found' } },
        })
      const memberships = classes
        .filter((item) => item.student_ids.includes(student.id))
        .map(({ id, code, name, academic_year }) => ({ id, code, name, academic_year }))
      return route.fulfill({ status: 200, json: { ...student, classes: memberships } })
    }
    if (request.method() === 'GET') {
      const search = (url.searchParams.get('search') ?? '').toLowerCase()
      const activeFilter = url.searchParams.get('is_active')
      const matches = students.filter(
        (item) =>
          (!search || `${item.student_number} ${item.full_name}`.toLowerCase().includes(search)) &&
          (activeFilter === null || String(item.is_active) === activeFilter),
      )
      const offset = Number(url.searchParams.get('offset') ?? 0)
      const limit = Number(url.searchParams.get('limit') ?? 10)
      return route.fulfill({
        status: 200,
        json: {
          items: matches.slice(offset, offset + limit),
          pagination: { total: matches.length, limit, offset },
        },
      })
    }
    if (request.method() === 'POST') {
      const body = request.postDataJSON() as { student_number: string; full_name: string }
      const student = {
        id: `student-${nextId++}`,
        student_number: body.student_number.toUpperCase(),
        full_name: body.full_name,
        is_active: true,
        created_at: now,
        updated_at: now,
      }
      students.push(student)
      return route.fulfill({ status: 201, json: student })
    }
    if (request.method() === 'PATCH') {
      const student = students.find((item) => item.id === studentId)
      if (!student)
        return route.fulfill({
          status: 404,
          json: { error: { code: 'not_found', message: 'Not found' } },
        })
      Object.assign(student, request.postDataJSON(), { updated_at: now })
      return route.fulfill({ status: 200, json: student })
    }
    return route.fallback()
  })

  await page.route('**/api/v1/classes**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const parts = url.pathname.split('/').filter(Boolean)
    const classId = parts[3]
    const classRow = classes.find((item) => item.id === classId)
    if (request.method() === 'GET' && classId && parts[4] === 'students') {
      if (!classRow)
        return route.fulfill({
          status: 404,
          json: { error: { code: 'not_found', message: 'Not found' } },
        })
      return route.fulfill({
        status: 200,
        json: {
          ...classRow,
          students: students
            .filter((item) => classRow.student_ids.includes(item.id))
            .map(({ id, student_number, full_name, is_active }) => ({
              id,
              student_number,
              full_name,
              is_active,
            })),
        },
      })
    }
    if (request.method() === 'GET' && classId) {
      if (!classRow)
        return route.fulfill({
          status: 404,
          json: { error: { code: 'not_found', message: 'Not found' } },
        })
      return route.fulfill({
        status: 200,
        json: {
          ...classRow,
          students: students
            .filter((item) => classRow.student_ids.includes(item.id))
            .map(({ id, student_number, full_name, is_active }) => ({
              id,
              student_number,
              full_name,
              is_active,
            })),
        },
      })
    }
    if (request.method() === 'GET') {
      const search = (url.searchParams.get('search') ?? '').toLowerCase()
      const matches = classes.filter((item) =>
        `${item.code} ${item.name}`.toLowerCase().includes(search),
      )
      return route.fulfill({
        status: 200,
        json: { items: matches, pagination: { total: matches.length, limit: 10, offset: 0 } },
      })
    }
    if (request.method() === 'POST' && classId && parts[4] === 'students') {
      if (!classRow)
        return route.fulfill({
          status: 404,
          json: { error: { code: 'not_found', message: 'Not found' } },
        })
      const { student_id: studentId } = request.postDataJSON() as { student_id: string }
      classRow.student_ids.push(studentId)
      const student = students.find((item) => item.id === studentId)
      return route.fulfill({ status: 201, json: student })
    }
    if (request.method() === 'POST') {
      const body = request.postDataJSON() as Omit<
        ApiClass,
        'id' | 'created_at' | 'updated_at' | 'student_ids' | 'homeroom_teacher_id' | 'is_active'
      >
      const created: ApiClass = {
        ...body,
        id: `class-${nextId++}`,
        homeroom_teacher_id: null,
        is_active: true,
        created_at: now,
        updated_at: now,
        student_ids: [],
      }
      classes.push(created)
      return route.fulfill({ status: 201, json: created })
    }
    if (request.method() === 'PATCH' && classRow) {
      Object.assign(classRow, request.postDataJSON(), { updated_at: now })
      return route.fulfill({ status: 200, json: classRow })
    }
    return route.fallback()
  })

  await page.route('**/api/v1/laboratories**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const laboratoryId = url.pathname.split('/')[4]
    if (request.method() === 'GET') {
      const search = (url.searchParams.get('search') ?? '').toLowerCase()
      const matches = laboratories.filter((item) =>
        `${item.code} ${item.name}`.toLowerCase().includes(search),
      )
      return route.fulfill({
        status: 200,
        json: { items: matches, pagination: { total: matches.length, limit: 10, offset: 0 } },
      })
    }
    if (request.method() === 'POST') {
      const body = request.postDataJSON() as Record<string, unknown>
      const created = {
        ...body,
        id: `lab-${nextId++}`,
        location: body.location ?? null,
        is_active: true,
        created_at: now,
        updated_at: now,
      }
      laboratories.push(created)
      return route.fulfill({ status: 201, json: created })
    }
    if (request.method() === 'PATCH') {
      const laboratory = laboratories.find((item) => item.id === laboratoryId)
      if (!laboratory)
        return route.fulfill({
          status: 404,
          json: { error: { code: 'not_found', message: 'Not found' } },
        })
      Object.assign(laboratory, request.postDataJSON(), { updated_at: now })
      return route.fulfill({ status: 200, json: laboratory })
    }
    if (request.method() === 'GET' && laboratoryId) {
      const laboratory = laboratories.find((item) => item.id === laboratoryId)
      return route.fulfill({
        status: laboratory ? 200 : 404,
        json: laboratory ?? { error: { code: 'not_found', message: 'Not found' } },
      })
    }
    return route.fallback()
  })

  await page.route('**/api/v1/students/import/preview', (route) =>
    route.fulfill({
      status: 200,
      json: {
        total_rows: 1,
        valid_rows: 1,
        invalid_rows: 0,
        can_commit: true,
        rows: [
          {
            row_number: 2,
            student_number: 'S-200',
            full_name: 'Imported Synthetic Student',
            class_code: 'XI-IPA-1',
            valid: true,
            errors: [],
          },
        ],
      },
    }),
  )
  await page.route('**/api/v1/students/import/commit', (route) => {
    students.push({
      id: `student-${nextId++}`,
      student_number: 'S-200',
      full_name: 'Imported Synthetic Student',
      is_active: true,
      created_at: now,
      updated_at: now,
    })
    return route.fulfill({
      status: 201,
      json: { imported_count: 1, class_memberships_created: 1 },
    })
  })
}

test('administrator creates, searches, edits, and links master data', async ({ page }) => {
  await stubMasterDataApi(page)
  await loginAsAdmin(page)
  await page.getByTestId('master-data-link').click()
  await expect(page.getByRole('heading', { name: 'Data master' })).toBeVisible()

  await page.getByRole('button', { name: 'Tambah siswa' }).click()
  await page.getByRole('textbox', { name: 'NIS/NISN' }).fill('S-100')
  await page.getByRole('textbox', { name: 'Nama lengkap' }).fill('Dinda Sintetis')
  await page.getByRole('button', { name: 'Simpan', exact: true }).click()
  await expect(page.getByRole('cell', { name: 'Dinda Sintetis' })).toBeVisible()
  await page.getByRole('searchbox', { name: 'Cari siswa' }).fill('Dinda')
  await page.getByRole('button', { name: 'Cari' }).click()
  await expect(page.getByRole('cell', { name: 'Dinda Sintetis' })).toBeVisible()

  await page.getByTestId('tab-classes').click()
  await page.getByRole('button', { name: 'Tambah kelas' }).click()
  await page.getByRole('textbox', { name: 'Kode kelas' }).fill('XI-IPA-1')
  await page.getByRole('textbox', { name: 'Nama kelas' }).fill('Kelas XI IPA 1')
  await page.getByRole('spinbutton', { name: 'Tingkat' }).fill('11')
  await page.getByRole('textbox', { name: 'Tahun ajaran' }).fill('2026-2027')
  await page.getByRole('button', { name: 'Simpan', exact: true }).click()
  await expect(page.getByRole('cell', { name: 'Kelas XI IPA 1' })).toBeVisible()
  await page.getByRole('button', { name: 'Detail' }).click()
  await page.getByLabel('Pilih siswa untuk ditambahkan').selectOption('student-1')
  await page.getByRole('button', { name: 'Tambah siswa' }).click()
  await expect(page.getByText('Dinda Sintetis', { exact: true })).toBeVisible()

  await page.getByTestId('tab-students').click()
  await page.getByRole('button', { name: 'Ubah' }).click()
  await page.getByRole('textbox', { name: 'Nama lengkap' }).fill('Dinda Update')
  await page.getByRole('button', { name: 'Simpan perubahan' }).click()
  await expect(page.getByRole('cell', { name: 'Dinda Update' })).toBeVisible()
  await page.getByRole('button', { name: 'Ubah' }).click()
  await page.getByLabel('Data aktif').uncheck()
  await page.getByRole('button', { name: 'Simpan perubahan' }).click()
  await expect(page.getByRole('cell', { name: 'Nonaktif' })).toBeVisible()

  await page.getByTestId('tab-laboratories').click()
  await page.getByRole('button', { name: 'Tambah laboratorium' }).click()
  await page.getByRole('textbox', { name: 'Kode laboratorium' }).fill('LAB-BIO')
  await page.getByRole('textbox', { name: 'Nama laboratorium' }).fill('Laboratorium Biologi')
  await page.getByRole('textbox', { name: 'Lokasi (opsional)' }).fill('Gedung B')
  await page.getByRole('button', { name: 'Simpan', exact: true }).click()
  await expect(page.getByRole('cell', { name: 'Laboratorium Biologi' })).toBeVisible()

  await page.getByTestId('tab-students').click()
  await page.getByTestId('open-student-import').click()
  await page.locator('input[type="file"]').setInputFiles({
    name: 'students.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('NIS,Nama,Kelas\nS-200,Imported Synthetic Student,XI-IPA-1'),
  })
  await page.getByRole('button', { name: 'Preview data' }).click()
  await expect(page.getByTestId('import-row-2')).toContainText('Valid')
  await page.getByTestId('commit-student-import').click()
  await expect(page.getByRole('status')).toContainText('1 siswa berhasil diimpor')
  await expect(page.getByRole('cell', { name: 'Imported Synthetic Student' })).toBeVisible()
})
