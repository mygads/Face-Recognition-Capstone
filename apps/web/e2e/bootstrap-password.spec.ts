import { expect, test } from '@playwright/test'

const temporaryPassword = 'synthetic-one-time-password'
const newPassword = 'synthetic-long-password-123'

test('bootstrap admin changes its temporary password before entering the app', async ({ page }) => {
  let changeRequest: Record<string, string> | undefined
  await page.route('**/api/v1/auth/login', (route) =>
    route.fulfill({
      status: 200,
      json: {
        access_token: 'bootstrap-only-test-token',
        token_type: 'bearer',
        expires_in_seconds: 900,
        password_change_required: true,
      },
    }),
  )
  await page.route('**/api/v1/auth/change-password', async (route) => {
    changeRequest = route.request().postDataJSON() as Record<string, string>
    await route.fulfill({
      status: 200,
      json: { password_changed: true, sign_in_again: true },
    })
  })

  await page.goto('/auth/login')
  await page.getByLabel('Email sekolah').fill('admin@local.test')
  await page.getByLabel('Kata sandi').fill(temporaryPassword)
  await page.getByRole('button', { name: 'Masuk' }).click()

  await expect(page).toHaveURL(/\/auth\/change-password$/)
  await expect(page.getByRole('heading', { name: 'Buat kata sandi baru' })).toBeVisible()
  await page.getByLabel('Kata sandi sementara').fill(temporaryPassword)
  await page.getByLabel('Kata sandi baru', { exact: true }).fill(newPassword)
  await page.getByLabel('Ulangi kata sandi baru').fill(newPassword)
  await page.getByRole('button', { name: 'Simpan kata sandi baru' }).click()

  await expect(page).toHaveURL(/\/auth\/login\?passwordChanged=1$/)
  await expect(page.getByRole('status')).toContainText('berhasil diperbarui')
  expect(changeRequest).toEqual({
    current_password: temporaryPassword,
    new_password: newPassword,
  })
})

test('profile offers password change to an authenticated user', async ({ page }) => {
  let changeRequest: Record<string, string> | undefined
  await page.route('**/api/v1/sessions**', (route) =>
    route.fulfill({
      status: 200,
      json: { items: [], pagination: { total: 0, limit: 100, offset: 0 } },
    }),
  )
  await page.route('**/api/v1/auth/login', (route) =>
    route.fulfill({
      status: 200,
      json: {
        access_token: 'profile-test-token',
        token_type: 'bearer',
        expires_in_seconds: 900,
        password_change_required: false,
      },
    }),
  )
  await page.route('**/api/v1/auth/me', (route) =>
    route.fulfill({
      status: 200,
      json: {
        id: 'profile-user-id',
        email: 'admin@local.test',
        full_name: 'Local Administrator',
        roles: ['ADMIN'],
        must_change_password: false,
      },
    }),
  )
  await page.route('**/api/v1/auth/change-password', async (route) => {
    changeRequest = route.request().postDataJSON() as Record<string, string>
    await route.fulfill({
      status: 200,
      json: { password_changed: true, sign_in_again: true },
    })
  })

  await page.goto('/auth/login')
  await page.getByLabel('Email sekolah').fill('admin@local.test')
  await page.getByLabel('Kata sandi').fill('synthetic-current-password')
  await page.getByRole('button', { name: 'Masuk' }).click()
  await expect(page).toHaveURL(/\/app\/dashboard$/)
  await page.getByRole('link', { name: 'Profil' }).click()
  await expect(page.getByRole('heading', { name: 'Profil akun' })).toBeVisible()
  await page.getByLabel('Kata sandi saat ini').fill('synthetic-current-password')
  await page.getByLabel('Kata sandi baru', { exact: true }).fill(newPassword)
  await page.getByLabel('Ulangi kata sandi baru').fill(newPassword)
  await page.getByRole('button', { name: 'Simpan kata sandi baru' }).click()

  await expect(page).toHaveURL(/\/auth\/login\?passwordChanged=1$/)
  expect(changeRequest).toEqual({
    current_password: 'synthetic-current-password',
    new_password: newPassword,
  })
})
