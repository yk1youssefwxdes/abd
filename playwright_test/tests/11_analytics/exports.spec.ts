import { test, expect } from '../../fixtures/base.fixture';
import { loginAsAdmin } from '../../fixtures/auth.fixture';

test.describe('Analytics & Reports - Exports Suite', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('11.06 Should handle revenue PDF export request without server error', async ({ page }) => {
    const response = await page.request.get('/analytics/export/revenue/pdf/');
    expect([200, 302]).toContain(response.status());
  });

  test('11.07 Should handle attendance PDF export request without server error', async ({ page }) => {
    const response = await page.request.get('/analytics/export/attendance/pdf/');
    expect([200, 302]).toContain(response.status());
  });

  test('11.08 Should handle payroll PDF export request without server error', async ({ page }) => {
    const response = await page.request.get('/analytics/export/payroll/pdf/');
    expect([200, 302]).toContain(response.status());
  });
});
