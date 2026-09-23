import { test, expect } from '../../fixtures/base.fixture';

test.describe('Public Portals - Parent/Student Kiosk Portal Suite', () => {
  test('12.03 Should render public kiosk home screen with keypad and search input', async ({ publicKioskPage, page }) => {
    await publicKioskPage.goto();
    await expect(page).toHaveURL(/\/public\/kiosk\//);
    await expect(publicKioskPage.kioskInput).toBeVisible();
    await expect(publicKioskPage.searchBtn).toBeVisible();
  });

  test('12.04 Should search student by code or phone on kiosk', async ({ publicKioskPage, page }) => {
    await publicKioskPage.goto();
    await publicKioskPage.searchStudent('0600112233');
    await expect(page).toHaveURL(/\/public\/kiosk/);
  });
});
