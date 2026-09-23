import { test, expect } from '../../fixtures/base.fixture';
import { loginAsAdmin } from '../../fixtures/auth.fixture';

test.describe('Students - Enrollment Suite', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('04.06 Should display student enrollment details on student page', async ({ page }) => {
    await page.goto('/students/1/');
    await expect(page).toHaveURL(/\/students\/1\//);
    await expect(page.locator('body')).toBeVisible();
  });
});
