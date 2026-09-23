import { test, expect } from '../../fixtures/base.fixture';
import { loginAsAdmin } from '../../fixtures/auth.fixture';

test.describe('WhatsApp Center - Bulk Announcements Suite', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('10.04 Should load bulk announcements compose screen', async ({ whatsappPage, page }) => {
    await whatsappPage.gotoBulkAnnouncements();
    await expect(page).toHaveURL(/\/whatsapp\/bulk-announcements\//);
    await expect(page.locator('h1, .page-title')).toBeVisible();
    await expect(page.locator('form, textarea, select').first()).toBeVisible();
  });
});
