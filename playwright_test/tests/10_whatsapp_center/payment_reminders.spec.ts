import { test, expect } from '../../fixtures/base.fixture';
import { loginAsAdmin } from '../../fixtures/auth.fixture';

test.describe('WhatsApp Center - Payment Reminders Suite', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('10.02 Should load payment reminders list', async ({ whatsappPage, page }) => {
    await whatsappPage.gotoPaymentReminders();
    await expect(page).toHaveURL(/\/whatsapp\/payment-reminders\//);
    await expect(page.locator('h1, .page-title')).toBeVisible();
  });
});
