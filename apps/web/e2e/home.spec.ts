import { expect, test } from '@playwright/test'

test('authenticated shell opens and responds to theme and mobile navigation controls', async ({
  page,
}) => {
  await page.goto('/app/dashboard')

  await expect(page.getByTestId('app-shell')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Ringkasan' })).toBeVisible()
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
