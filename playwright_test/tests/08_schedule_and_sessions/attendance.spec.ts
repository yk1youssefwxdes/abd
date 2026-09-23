import { test, expect } from '../../fixtures/base.fixture';
import { loginAsAdmin } from '../../fixtures/auth.fixture';

test.describe('Schedule - Attendance Recording Suite', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('08.04 Should view attendance report view', async ({ page }) => {
    await page.goto('/attendance/report/');
    await expect(page).toHaveURL(/\/attendance\/report\//);
    await expect(page.locator('h1, .page-title')).toBeVisible();
  });
});
