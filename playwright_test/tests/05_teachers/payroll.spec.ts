import { test, expect } from '../../fixtures/base.fixture';
import { loginAsAdmin } from '../../fixtures/auth.fixture';

test.describe('Teachers - Payroll Suite', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('05.07 Should display teacher payroll calculation page', async ({ page }) => {
    await page.goto('/payroll/teacher/');
    await expect(page).toHaveURL(/\/payroll\/teacher\//);
    await expect(page.locator('h1, .page-title')).toBeVisible();
    await expect(page.locator('form, table, .payroll-summary').first()).toBeVisible();
  });
});
