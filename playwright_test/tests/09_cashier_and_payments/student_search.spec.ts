import { test, expect } from '../../fixtures/base.fixture';
import { loginAsAdmin } from '../../fixtures/auth.fixture';

test.describe('Cashier - Student Search AJAX Suite', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('09.03 AJAX student-search returns matching student records', async ({ page }) => {
    const response = await page.request.get('/cashier/student-search/?q=Amine');
    expect(response.status()).toBe(200);
    const json = await response.json();
    expect(json.results.length).toBeGreaterThanOrEqual(1);
    expect(json.results[0].text).toContain('Amine');
  });

  test('09.04 AJAX student-unpaid-search endpoint responds successfully', async ({ page }) => {
    const response = await page.request.get('/cashier/student-unpaid-search/?q=');
    expect(response.status()).toBe(200);
  });
});
