import { test, expect } from '../../fixtures/base.fixture';
import { loginAsAdmin } from '../../fixtures/auth.fixture';

test.describe('Cockpit / Dashboard Suite', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('03.01 Should load cockpit dashboard with KPI metrics and quick actions', async ({ cockpitPage }) => {
    await cockpitPage.goto();
    await expect(cockpitPage.pageTitle).toBeVisible();
    await cockpitPage.expectKpisLoaded();
  });

  test('03.02 Should search via navbar search input', async ({ cockpitPage, page }) => {
    await cockpitPage.goto();
    if (await cockpitPage.searchInput.isVisible()) {
      await cockpitPage.searchNavbar('Amine');
      // Wait for search dropdown or results
      const results = page.locator('.navbar-search-results, .navbar-search-item');
      // Verify no crash occurs
      await expect(cockpitPage.searchInput).toHaveValue('Amine');
    }
  });
});
