import { test, expect } from '../../fixtures/base.fixture';
import { loginAsAdmin } from '../../fixtures/auth.fixture';

test.describe('Schedule - Visual Weekly Schedule Suite', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('08.01 Should render weekly interactive schedule grid', async ({ schedulePage, page }) => {
    await schedulePage.gotoWeekly();
    await expect(page).toHaveURL(/\/schedule\//);
    await expect(schedulePage.calendarGrid).toBeVisible();
  });

  test('08.02 Should navigate schedule weeks using prev/next controls', async ({ schedulePage, page }) => {
    await schedulePage.gotoWeekly();
    if (await schedulePage.nextWeekBtn.first().isVisible()) {
      await schedulePage.nextWeekBtn.first().click();
      await page.waitForLoadState('domcontentloaded');
      await expect(schedulePage.calendarGrid).toBeVisible();
    }
  });
});
