import { test, expect } from '../../fixtures/base.fixture';
import { loginAsAdmin } from '../../fixtures/auth.fixture';

test.describe('Django Admin (Unfold) Suite', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('13.02 Should access Django Admin dashboard', async ({ page }) => {
    await page.goto('/admin/');
    await expect(page).toHaveURL(/\/admin\//);
    await expect(page.locator('body')).toBeVisible();
  });

  test('13.03 Should navigate to Django Admin Student model changelist', async ({ page }) => {
    await page.goto('/admin/core/student/');
    await expect(page).toHaveURL(/\/admin\/core\/student\//);
    await expect(page.locator('#changelist, .change-list, table').first()).toBeVisible();
  });

  test('13.04 Should navigate to Django Admin Teacher model changelist', async ({ page }) => {
    await page.goto('/admin/core/teacher/');
    await expect(page).toHaveURL(/\/admin\/core\/teacher\//);
    await expect(page.locator('#changelist, .change-list, table').first()).toBeVisible();
  });
});
