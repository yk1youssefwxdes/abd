import { test, expect } from '../../fixtures/base.fixture';
import { loginAsAdmin } from '../../fixtures/auth.fixture';

test.describe('WhatsApp Center - Dashboard Suite', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('10.01 Should display WhatsApp integration dashboard', async ({ whatsappPage, page }) => {
    await whatsappPage.gotoDashboard();
    await expect(page).toHaveURL(/\/whatsapp\//);
    await expect(page.locator('h1, .page-title')).toBeVisible();
  });
});
