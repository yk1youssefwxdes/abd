import { test, expect } from '../../fixtures/base.fixture';
import { loginAsAdmin } from '../../fixtures/auth.fixture';

test.describe('JavaScript & Network Error Detection Suite', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('14.02 Core pages should render with zero unhandled JavaScript exceptions', async ({ basePage, page }) => {
    const criticalPages = [
      '/',
      '/students/',
      '/teachers/',
      '/rooms/',
      '/courses/',
      '/levels/',
      '/cashier/payment/create/',
      '/whatsapp/',
      '/analytics/dashboard/',
      '/settings/',
    ];

    for (const url of criticalPages) {
      await basePage.goto(url);
      const errors = basePage.getPageErrors();
      expect(errors, `Uncaught page error on ${url}: ${errors.map(e => e.message).join(', ')}`).toHaveLength(0);
    }
  });
});
