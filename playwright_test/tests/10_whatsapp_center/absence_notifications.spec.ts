import { test, expect } from '../../fixtures/base.fixture';
import { loginAsAdmin } from '../../fixtures/auth.fixture';

test.describe('WhatsApp Center - Absence Notifications Suite', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('10.03 Should load absence notifications interface', async ({ whatsappPage, page }) => {
    await whatsappPage.gotoAbsenceNotifications();
    await expect(page).toHaveURL(/\/whatsapp\/absence-notifications\//);
    await expect(page.locator('h1, .page-title')).toBeVisible();
  });
});
