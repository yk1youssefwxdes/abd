import { test, expect } from '../../fixtures/base.fixture';
import { loginAsUser } from '../../fixtures/auth.fixture';
import { TEST_USERS } from '../../fixtures/test-data';

test.describe('Authentication - Permissions & Role Access Suite', () => {
  test('01.06 Protected routes redirect unauthenticated users to login', async ({ page }) => {
    const protectedRoutes = [
      '/',
      '/students/',
      '/teachers/',
      '/rooms/',
      '/courses/',
      '/levels/',
      '/schedule/',
      '/cashier/payment/create/',
      '/whatsapp/',
      '/analytics/dashboard/',
      '/settings/',
    ];

    for (const route of protectedRoutes) {
      await page.goto(route);
      await expect(page).toHaveURL(/\/admin\/login\//);
    }
  });

  test('01.07 Non-staff regular user is redirected to login by AdminOnlyMiddleware', async ({ page }) => {
    // Regular user is_staff=False
    await loginAsUser(page, TEST_USERS.regular.username, TEST_USERS.regular.password);
    // Non-staff should not be able to access main app
    await page.goto('/students/');
    await expect(page).toHaveURL(/\/admin\/login\//);
  });

  test('01.08 Public routes are accessible without login', async ({ page }) => {
    const publicRoutes = [
      '/public/attendance/',
      '/public/kiosk/',
    ];

    for (const route of publicRoutes) {
      await page.goto(route);
      await expect(page).not.toHaveURL(/\/admin\/login\//);
    }
  });
});
