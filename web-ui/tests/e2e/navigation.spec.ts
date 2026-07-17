import { test, expect } from '@playwright/test';

test.describe('Sidebar Navigation', () => {

  test.beforeEach(async ({ page, context }) => {
    // Mock login state so we can access dashboard pages
    await context.addInitScript(() => {
      localStorage.setItem('alertflow_token', 'mock_token');
    });

    // Start at English dashboard
    await page.goto('/en');
  });

  test('should navigate to Settings and preserve locale', async ({ page }) => {
    // Click Settings link in the sidebar
    await page.getByRole('link', { name: 'Settings' }).click();

    // Verify URL
    await expect(page).toHaveURL(/\/en\/settings/);

    // Verify Settings page loaded
    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible();
  });

  test('should navigate to System Logs and preserve locale', async ({ page }) => {
    // Click Logs link
    await page.getByRole('link', { name: 'System Logs' }).click();

    // Verify URL
    await expect(page).toHaveURL(/\/en\/logs/);

    // Verify Logs page loaded
    await expect(page.getByRole('heading', { name: 'System Logs' })).toBeVisible();
  });

  test('sidebar navigation in Persian', async ({ page }) => {
    // Switch to Persian
    await page.getByRole('button', { name: 'FA' }).click();

    // Click 'تنظیمات' (Settings)
    await page.getByRole('link', { name: 'تنظیمات' }).click();

    // Verify URL is /fa/settings
    await expect(page).toHaveURL(/\/fa\/settings/);

    // Verify Persian settings page loaded
    await expect(page.getByRole('heading', { name: 'تنظیمات' })).toBeVisible();
  });

});
