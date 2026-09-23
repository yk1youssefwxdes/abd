import { test, expect } from '../../fixtures/base.fixture';
import { loginAsAdmin } from '../../fixtures/auth.fixture';

test.describe('Teachers - Availability & Workload Suite', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('05.05 Should view teacher workload dashboard', async ({ page }) => {
    await page.goto('/teachers/workload/');
    await expect(page).toHaveURL(/\/teachers\/workload\//);
    await expect(page.locator('h1, .page-title')).toBeVisible();
  });
});
