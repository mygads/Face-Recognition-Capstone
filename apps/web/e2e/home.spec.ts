import { expect, test, type Page } from '@playwright/test'

const fixtureToken = 'e2e-fixture-access-token'
const fixturePassword = 'e2e-fixture-password'

async function stubSuccessfulLogin(page: Page): Promise<{
  loginWasFormEncoded: () => boolean
  bearerHeaderWasPresent: () => boolean
}> {
  let loginWasFormEncoded = false
  let bearerHeaderWasPresent = false

  await page.route('**/api/v1/auth/login', async (route) => {
    const request = route.request()
    const contentType = request.headers()['content-type'] ?? ''
    const body = request.postData() ?? ''
    loginWasFormEncoded =
      contentType.startsWith('application/x-www-form-urlencoded') &&
      body.includes('username=') &&
      body.includes('password=')

    await route.fulfill({
      status: 200,
      json: {
        access_token: fixtureToken,
        token_type: 'bearer',
        expires_in_seconds: 900,
      },
    })
  })

  await page.route('**/api/v1/auth/me', async (route) => {
    const authorization = route.request().headers().authorization ?? ''
    bearerHeaderWasPresent = authorization.startsWith('Bearer ') && authorization.length > 7
    await route.fulfill({
      status: 200,
      json: {
        id: '9c6c68d0-9b70-4c80-a9bd-15c2a55ecb27',
        email: 'teacher@example.test',
        full_name: 'Test Teacher',
        roles: ['TEACHER'],
      },
    })
  })

  return {
    loginWasFormEncoded: () => loginWasFormEncoded,
    bearerHeaderWasPresent: () => bearerHeaderWasPresent,
  }
}

async function submitTestLogin(page: Page): Promise<void> {
  await page.goto('/auth/login')
  await page.getByLabel('Email sekolah').fill('teacher@example.test')
  await page.getByLabel('Kata sandi').fill(fixturePassword)
  await page.getByRole('button', { name: 'Masuk' }).click()
}

test('login success opens the authenticated shell using the generated API contract', async ({
  page,
}) => {
  let sensitiveValueWasLogged = false
  page.on('console', (message) => {
    if ([fixtureToken, fixturePassword].some((value) => message.text().includes(value))) {
      sensitiveValueWasLogged = true
    }
  })
  const requests = await stubSuccessfulLogin(page)

  await submitTestLogin(page)

  await expect(page).toHaveURL(/\/app\/dashboard$/)
  await expect(page.getByTestId('app-shell')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Ringkasan' })).toBeVisible()
  expect(requests.loginWasFormEncoded()).toBe(true)
  expect(requests.bearerHeaderWasPresent()).toBe(true)
  expect(sensitiveValueWasLogged).toBe(false)
})

test('login failure shows a safe message and stays on the login page', async ({ page }) => {
  let sensitiveValueWasLogged = false
  page.on('console', (message) => {
    if (message.text().includes(fixturePassword)) sensitiveValueWasLogged = true
  })
  await page.route('**/api/v1/auth/login', async (route) => {
    await route.fulfill({
      status: 401,
      json: { error: { code: 'unauthorized', message: 'Authentication is required.' } },
    })
  })

  await submitTestLogin(page)

  await expect(page).toHaveURL(/\/auth\/login$/)
  await expect(page.getByRole('alert')).toHaveText('Email atau kata sandi tidak valid.')
  expect(sensitiveValueWasLogged).toBe(false)
})

test('authenticated shell responds to theme and mobile navigation controls', async ({ page }) => {
  await stubSuccessfulLogin(page)
  await submitTestLogin(page)

  await expect(page.getByRole('navigation', { name: 'Navigasi utama' })).toBeVisible()
  const themeToggle = page.getByTestId('theme-toggle')
  const currentTheme = await page.locator('html').getAttribute('data-theme')
  await themeToggle.click()
  await expect(page.locator('html')).toHaveAttribute(
    'data-theme',
    currentTheme === 'dark' ? 'light' : 'dark',
  )

  await page.setViewportSize({ width: 768, height: 900 })
  await page.getByRole('button', { name: 'Buka atau ciutkan navigasi' }).click()
  await expect(page.getByTestId('dashboard-link')).toBeVisible()
  await page.getByRole('button', { name: 'Tutup navigasi' }).click()
  await expect(page.getByRole('button', { name: 'Buka atau ciutkan navigasi' })).toHaveAttribute(
    'aria-expanded',
    'false',
  )
})
