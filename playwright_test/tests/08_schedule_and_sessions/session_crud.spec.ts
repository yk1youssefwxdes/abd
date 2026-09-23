import { test, expect } from '../../fixtures/base.fixture';
import { loginAsAdmin } from '../../fixtures/auth.fixture';

test.describe('Schedule - Sessions & Today Suite', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('08.03 Should display today\'s sessions dashboard', async ({ schedulePage, page }) => {
    await schedulePage.gotoToday();
    await expect(page).toHaveURL(/\/sessions\/today\//);
    await expect(page.locator('h1, .page-title')).toBeVisible();
  });
});
