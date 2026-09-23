import { test, expect } from '../../fixtures/base.fixture';
import { loginAsAdmin } from '../../fixtures/auth.fixture';

test.describe('Schedule - Conflict Detection Suite', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('08.05 Should load schedule conflicts dashboard', async ({ schedulePage, page }) => {
    await schedulePage.gotoConflicts();
    await expect(page).toHaveURL(/\/schedule\/conflicts\//);
    await expect(page.locator('h1, .page-title')).toBeVisible();
  });
});
