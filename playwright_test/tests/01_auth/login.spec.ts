import { test, expect } from '../../fixtures/base.fixture';
import { TEST_USERS } from '../../fixtures/test-data';

test.describe('Authentication - Login Suite', () => {
  test('01.01 Should display login page with username and password inputs', async ({ loginPage }) => {
    await loginPage.goto();
    await expect(loginPage.usernameInput).toBeVisible();
    await expect(loginPage.passwordInput).toBeVisible();
    await expect(loginPage.submitButton).toBeVisible();
  });

  test('01.02 Should fail login with invalid username', async ({ loginPage }) => {
    await loginPage.goto();
    await loginPage.login('non_existent_user', 'WrongPassword123!');
    await loginPage.expectLoginError();
  });

  test('01.03 Should fail login with invalid password for valid user', async ({ loginPage }) => {
    await loginPage.goto();
    await loginPage.login(TEST_USERS.testAdmin.username, 'WrongPassword999!');
    await loginPage.expectLoginError();
  });

  test('01.04 Should fail login with empty fields', async ({ loginPage }) => {
    await loginPage.goto();
    await loginPage.submitButton.click();
    // HTML5 validation or server-side error
    await expect(loginPage.page).toHaveURL(/\/admin\/login\//);
  });

  test('01.05 Should successfully login as superuser and redirect to dashboard', async ({ loginPage }) => {
    await loginPage.goto();
    await loginPage.login(TEST_USERS.testAdmin.username, TEST_USERS.testAdmin.password);
    await loginPage.expectSuccessfulLoginRedirect();
    // Verify dashboard or cockpit is accessible
    await expect(loginPage.page).not.toHaveURL(/\/admin\/login\//);
  });
});
