import { test, expect } from '@playwright/test';

test.describe('Internationalization (i18n) and RTL', () => {

  test('should default to English and LTR', async ({ page }) => {
    // Navigate to root (which should redirect to /login or /en/login depending on auth, but let's mock login or just check login page)
    await page.goto('/en/login');

    // Check HTML dir attribute
    await expect(page.locator('html')).toHaveAttribute('dir', 'ltr');

    // Check if English text is present
    await expect(page.getByText('AlertFlow')).toBeVisible();
    await expect(page.getByText('Sign in to access the dashboard')).toBeVisible();
  });

  test('should switch to Persian and apply RTL', async ({ page }) => {
    // Start on the login page in English
    await page.goto('/en/login');

    // Manually navigate to /fa/login to simulate language switch since login might not have the language switcher
    await page.goto('/fa/login');

    // Check HTML dir attribute
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');

    // Check if Persian text is present
    await expect(page.getByText('هسته هوش مصنوعی سنتینل')).toBeVisible();
    await expect(page.getByText('برای دسترسی به داشبورد وارد شوید')).toBeVisible();
  });

  test('Language switcher should toggle locale in dashboard', async ({ page, context }) => {
    // We need to set a mock token to access the dashboard
    await context.addInitScript(() => {
      localStorage.setItem('alertflow_token', 'mock_token');
    });

    await page.goto('/en');

    // It should load English dashboard
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();

    // Click the language switcher (which says 'FA' when currently in 'en')
    await page.getByRole('button', { name: 'FA' }).click();

    // Verify URL changed to /fa
    await expect(page).toHaveURL(/\/fa/);

    // Verify RTL is applied
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');

    // Verify Persian translation
    await expect(page.getByRole('heading', { name: 'داشبورد' })).toBeVisible();

    // Switch back to English
    await page.getByRole('button', { name: 'EN' }).click();

    // Verify URL changed back to /en
    await expect(page).toHaveURL(/\/en/);
    await expect(page.locator('html')).toHaveAttribute('dir', 'ltr');
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
  });

});
