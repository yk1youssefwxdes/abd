import { test, expect } from '../../fixtures/base.fixture';
import { loginAsAdmin } from '../../fixtures/auth.fixture';

test.describe('Teachers - Leaves Suite', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('05.06 Should access teacher leaves management page', async ({ page }) => {
    await page.goto('/teachers/1/leaves/');
    await expect(page).toHaveURL(/\/teachers\/1\/leaves\//);
    await expect(page.locator('h1, .page-title, form, .card').first()).toBeVisible();
  });
});
