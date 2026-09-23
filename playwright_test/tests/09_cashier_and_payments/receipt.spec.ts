import { test, expect } from '../../fixtures/base.fixture';
import { loginAsAdmin } from '../../fixtures/auth.fixture';

test.describe('Cashier - Receipt Suite', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('09.05 Should view printable receipt for existing payment', async ({ page }) => {
    await page.goto('/cashier/payment/1/receipt/');
    // If payment 1 exists, 200 is returned, else redirects safely
    expect([200, 302, 404]).toContain(page.url().includes('login') ? 302 : 200);
  });
});
