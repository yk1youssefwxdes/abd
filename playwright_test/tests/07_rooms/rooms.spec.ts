import { test, expect } from '../../fixtures/base.fixture';
import { loginAsAdmin } from '../../fixtures/auth.fixture';

test.describe('Rooms Suite', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('07.01 Should display rooms list with equipment and capacities', async ({ roomsPage, page }) => {
    await roomsPage.gotoList();
    await expect(page).toHaveURL(/\/rooms\//);
    await roomsPage.expectRoomsVisible();
  });
});
