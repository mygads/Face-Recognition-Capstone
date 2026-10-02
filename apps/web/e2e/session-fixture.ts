import type { Page } from '@playwright/test'

export async function stubNoActiveBrowserSession(page: Page): Promise<void> {
  await page.route('**/api/v1/auth/refresh', (route) =>
    route.fulfill({
      status: 401,
      json: { error: { code: 'unauthorized', message: 'Authentication is required.' } },
    }),
  )
}
