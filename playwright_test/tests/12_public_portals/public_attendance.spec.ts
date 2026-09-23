import { test, expect } from '../../fixtures/base.fixture';

test.describe('Public Portals - Teacher Attendance Portal Suite', () => {
  test('12.01 Should render public teacher login screen without requiring admin auth', async ({ publicAttendancePage, page }) => {
    await publicAttendancePage.goto();
    await expect(page).toHaveURL(/\/public\/attendance\//);
    await expect(publicAttendancePage.teacherSelect).toBeVisible();
    await expect(publicAttendancePage.credentialInput).toBeVisible();
    await expect(publicAttendancePage.submitBtn).toBeVisible();
  });

  test('12.02 Should reject invalid teacher credentials', async ({ publicAttendancePage, page }) => {
    await publicAttendancePage.goto();
    // Select first teacher
    const options = await publicAttendancePage.teacherSelect.locator('option').all();
    for (const opt of options) {
      const val = await opt.getAttribute('value');
      if (val) {
        await publicAttendancePage.teacherSelect.selectOption(val);
        break;
      }
    }
    await publicAttendancePage.credentialInput.fill('0000000000');
    await publicAttendancePage.submitBtn.click();
    // Error feedback should be shown or stay on page
    await expect(page).toHaveURL(/\/public\/attendance\//);
  });
});
