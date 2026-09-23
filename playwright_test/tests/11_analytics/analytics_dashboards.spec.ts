import { test, expect } from '../../fixtures/base.fixture';
import { loginAsAdmin } from '../../fixtures/auth.fixture';

test.describe('Analytics & Reports - Dashboards Suite', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('11.01 Should render executive analytics dashboard', async ({ analyticsPage, page }) => {
    await analyticsPage.gotoDashboard();
    await expect(page).toHaveURL(/\/analytics\/dashboard\//);
    await expect(page.locator('h1, .page-title')).toBeVisible();
  });

  test('11.02 Should render revenue analytics dashboard', async ({ analyticsPage, page }) => {
    await analyticsPage.gotoRevenue();
    await expect(page).toHaveURL(/\/analytics\/revenue\//);
    await expect(page.locator('h1, .page-title')).toBeVisible();
  });

  test('11.03 Should render attendance analytics dashboard', async ({ analyticsPage, page }) => {
    await analyticsPage.gotoAttendance();
    await expect(page).toHaveURL(/\/analytics\/attendance/);
    await expect(page.locator('h1, .page-title')).toBeVisible();
  });

  test('11.04 Should render operational health analytics', async ({ analyticsPage, page }) => {
    await analyticsPage.gotoOperational();
    await expect(page).toHaveURL(/\/analytics\/operational\//);
    await expect(page.locator('h1, .page-title')).toBeVisible();
  });

  test('11.05 Should render room utilization analytics', async ({ analyticsPage, page }) => {
    await analyticsPage.gotoRooms();
    await expect(page).toHaveURL(/\/analytics\/rooms\//);
    await expect(page.locator('h1, .page-title')).toBeVisible();
  });
});
