import { test, expect } from '../../fixtures/base.fixture';
import { loginAsAdmin } from '../../fixtures/auth.fixture';

test.describe('Level Categories Suite', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('06.06 Should display level categories list', async ({ levelsPage, page }) => {
    await levelsPage.gotoCategoriesList();
    await expect(page).toHaveURL(/\/level-categories\//);
    await expect(page.locator('table, .category-card, .list-group').first()).toBeVisible();
  });
});
