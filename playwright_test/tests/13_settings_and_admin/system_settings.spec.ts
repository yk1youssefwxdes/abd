import { test, expect } from '../../fixtures/base.fixture';
import { loginAsAdmin } from '../../fixtures/auth.fixture';

test.describe('System Settings Suite', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('13.01 Should render system settings view with configuration fields', async ({ systemSettingsPage, page }) => {
    await systemSettingsPage.goto();
    await expect(page).toHaveURL(/\/settings\//);
    await expect(page.locator('h1, .page-title')).toBeVisible();
    await expect(page.locator('form, input').first()).toBeVisible();
  });
});
