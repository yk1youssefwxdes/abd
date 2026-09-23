import { test, expect } from '../../fixtures/base.fixture';
import { loginAsAdmin } from '../../fixtures/auth.fixture';

test.describe('Schedule - Monthly Schedule View Suite', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('08.06 Should render monthly schedule grid', async ({ schedulePage, page }) => {
    await schedulePage.gotoMonthly();
    await expect(page).toHaveURL(/\/schedule\/monthly\//);
    await expect(page.locator('h1, .page-title')).toBeVisible();
    await expect(page.locator('.calendar, .month-grid, table, .calendar-view').first()).toBeVisible();
  });
});
