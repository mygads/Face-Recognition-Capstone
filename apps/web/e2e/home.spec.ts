import { expect, test } from '@playwright/test'

test('home page displays the attendance project title', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByRole('heading', { name: 'Presensi Praktikum' })).toBeVisible()
})
