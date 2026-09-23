import { test, expect } from '../../fixtures/base.fixture';
import { loginAsAdmin } from '../../fixtures/auth.fixture';

test.describe('Levels Suite', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('06.04 Should display levels list', async ({ levelsPage }) => {
    await levelsPage.gotoList();
    await expect(levelsPage.levelRows.first()).toBeVisible();
  });

  test('06.05 Should validate level creation', async ({ levelsPage, page }) => {
    await levelsPage.gotoCreate();
    await levelsPage.submit();
    await expect(page).toHaveURL(/\/levels\/create\//);
  });
});
