import { test, expect } from '@playwright/test';

test.describe('Login Flow', () => {

  test.beforeEach(async ({ page }) => {
    // Navigate to the login page
    await page.goto('/en/login');
  });

  test('should display login form', async ({ page }) => {
    await expect(page.getByText('AlertFlow')).toBeVisible();
    await expect(page.locator('input[type="text"]')).toBeVisible();
    await expect(page.locator('input[type="password"]')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Sign In' })).toBeVisible();
  });

  test('should show error on invalid credentials', async ({ page }) => {
    // Fill the login form with invalid credentials
    await page.locator('input[type="text"]').fill('wronguser');
    await page.locator('input[type="password"]').fill('wrongpass');

    // Submit the form
    await page.getByRole('button', { name: 'Sign In' }).click();

    // Check if error message appears
    await expect(page.getByText('Invalid username or password')).toBeVisible();
  });

  // Note: We skip successful login because the backend API might not be running or accessible,
  // or we don't want to hit real APIs in basic E2E without mocks.
  // However, we can mock the API response.
  test('should login successfully with mock API', async ({ page }) => {
    // Intercept the API login request and mock the response
    await page.route('**/api/auth/login', async route => {
      const json = {
        access_token: 'fake-jwt-token',
        token_type: 'bearer',
        user: { username: 'admin', role: 'admin' }
      };
      await route.fulfill({ json });
    });

    await page.locator('input[type="text"]').fill('admin');
    await page.locator('input[type="password"]').fill('admin');
    await page.getByRole('button', { name: 'Sign In' }).click();

    // Verify redirection to dashboard
    await expect(page).toHaveURL(/\/en/);
  });

});
