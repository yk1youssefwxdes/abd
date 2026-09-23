import { test, expect } from '../../fixtures/base.fixture';
import { loginAsAdmin } from '../../fixtures/auth.fixture';

test.describe('Authentication - Logout Suite', () => {
  test('01.09 Should successfully logout and prevent subsequent protected access', async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto('/');
    await expect(page).not.toHaveURL(/\/admin\/login\//);

    // Invalidate authenticated session
    await page.context().clearCookies();

    // After logout / session invalidation, accessing protected route must redirect to login
    await page.goto('/students/');
    await expect(page).toHaveURL(/\/admin\/login\//);
  });
});
