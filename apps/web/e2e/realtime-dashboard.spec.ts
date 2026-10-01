import { expect, test, type Page, type WebSocketRoute } from '@playwright/test'

const timestamp = '2026-10-01T10:00:00Z'

async function loginAsTeacher(page: Page): Promise<void> {
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

function sessionSnapshot(present: number, late: number, isOnline: boolean) {
  return {
    session_id: 'session-1',
    session_status: 'active',
    generated_at: timestamp,
    summary: {
      total_roster: 3,
      present,
      late,
      not_present: 3 - present - late,
    },
    devices: [
      {
        id: 'device-1',
        name: 'Kamera Lab Biologi',
        device_type: 'edge_pc',
        is_online: isOnline,
        last_seen_at: timestamp,
      },
    ],
    recent_activity: [
      {
        id: `event-${present}-${late}`,
        occurred_at: timestamp,
        kind: 'recognition',
        student_name: late > 0 ? 'Siswa Dua' : 'Siswa Satu',
        recognition_outcome: 'matched',
        attendance_status: late > 0 ? 'late' : 'present',
        decision_reason: null,
      },
    ],
  }
}

test('teacher dashboard applies mocked realtime attendance and device updates', async ({
  page,
}) => {
  let sessionListRequests = 0
  let snapshotRequests = 0
  const socketState: { route: WebSocketRoute | null } = { route: null }
  let authenticationFrame: unknown
  let websocketUrl = ''

  await page.route('**/api/v1/sessions**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/v1/sessions' && route.request().method() === 'GET') {
      sessionListRequests += 1
      return route.fulfill({
        status: 200,
        json: {
          items: [
            {
              id: 'session-1',
              practicum_schedule_id: 'schedule-1',
              status: 'active',
              opened_at: timestamp,
              closed_at: null,
              grace_period_minutes: 15,
              student_count: 3,
              subject: 'Praktikum Biologi',
              class_name: 'Kelas X A',
              laboratory_name: 'Lab Biologi',
              teacher_name: 'Guru Praktikum',
              weekday: 3,
              start_time: '09:00:00',
              end_time: '11:00:00',
              timezone_name: 'Asia/Jakarta',
              scheduled_end_at: timestamp,
            },
          ],
          pagination: { total: 1, limit: 100, offset: 0 },
        },
      })
    }
    if (url.pathname.endsWith('/session-1/dashboard')) {
      snapshotRequests += 1
      return route.fulfill({ status: 200, json: sessionSnapshot(1, 0, true) })
    }
    return route.fulfill({ status: 404, json: { error: { code: 'not_found' } } })
  })

  await page.routeWebSocket(
    (url) => {
      websocketUrl = url.toString()
      return url.pathname === '/api/v1/sessions/session-1/updates'
    },
    (websocket) => {
      websocket.onMessage((message) => {
        authenticationFrame = JSON.parse(message.toString())
        socketState.route = websocket
        websocket.send(JSON.stringify({ type: 'snapshot', data: sessionSnapshot(1, 0, true) }))
      })
    },
  )

  await loginAsTeacher(page)

  await expect(page.getByTestId('realtime-status')).toHaveText('Live')
  await expect(page.getByTestId('metric-roster').locator('strong')).toHaveText('3')
  await expect(page.getByTestId('metric-present').locator('strong')).toHaveText('1')
  await expect(page.getByTestId('metric-late').locator('strong')).toHaveText('0')
  await expect(page.getByTestId('metric-not-present').locator('strong')).toHaveText('2')
  await expect(page.getByText('Kamera Lab Biologi')).toBeVisible()
  await expect(page.getByText('Siswa Satu')).toBeVisible()
  expect(authenticationFrame).toEqual({
    type: 'authenticate',
    access_token: 'session-test-token',
  })
  expect(new URL(websocketUrl).search).toBe('')

  socketState.route?.send(JSON.stringify({ type: 'snapshot', data: sessionSnapshot(1, 1, false) }))

  await expect(page.getByTestId('metric-late').locator('strong')).toHaveText('1')
  await expect(page.getByTestId('metric-not-present').locator('strong')).toHaveText('1')
  await expect(page.getByText('Siswa Dua')).toBeVisible()
  await expect(page.getByText('Offline')).toBeVisible()
  expect(sessionListRequests).toBe(1)
  expect(snapshotRequests).toBe(1)
  await expect(page.getByText(/embedding|foto wajah/i)).toHaveCount(0)
})
