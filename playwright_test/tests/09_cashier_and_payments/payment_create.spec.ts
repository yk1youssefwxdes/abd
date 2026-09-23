import { test, expect } from '../../fixtures/base.fixture';
import { loginAsAdmin } from '../../fixtures/auth.fixture';

test.describe('Cashier - Payment Recording Suite', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('09.01 Should display cashier payment creation form with fields', async ({ cashierPage, page }) => {
    await cashierPage.goto();
    await expect(page).toHaveURL(/\/cashier\/payment\/create\//);
    await expect(cashierPage.studentSearchInput).toBeVisible();
    await expect(cashierPage.amountInput).toBeVisible();
    await expect(cashierPage.paymentMethodSelect).toBeVisible();
  });

  test('09.02 Should search and select student in cashier form', async ({ cashierPage, page }) => {
    await cashierPage.goto();
    await cashierPage.selectStudent('Amine');
    // After selection, hidden input should have a student ID
    const studentId = await cashierPage.studentHiddenInput.inputValue();
    expect(studentId).toBeTruthy();
  });
});
