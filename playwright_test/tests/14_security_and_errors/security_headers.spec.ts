import { test, expect } from '../../fixtures/base.fixture';
import { loginAsAdmin } from '../../fixtures/auth.fixture';

test.describe('Security & Form Hardening Suite', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('14.01 Every form in the app should contain CSRF token', async ({ page }) => {
    const pagesWithForms = [
      '/students/create/',
      '/teachers/create/',
      '/courses/create/',
      '/levels/create/',
      '/cashier/payment/create/',
      '/settings/',
    ];

    for (const p of pagesWithForms) {
      await page.goto(p);
      const csrfInputs = page.locator('input[name="csrfmiddlewaretoken"]');
      const count = await csrfInputs.count();
      expect(count).toBeGreaterThanOrEqual(1);
    }
  });
});
