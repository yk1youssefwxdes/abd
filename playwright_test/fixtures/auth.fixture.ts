import { Page } from '@playwright/test';
import { LoginPage } from '../pages/LoginPage';
import { TEST_USERS } from './test-data';

export async function loginAsAdmin(page: Page) {
  const loginPage = new LoginPage(page);
  await loginPage.goto();
  await loginPage.login(TEST_USERS.testAdmin.username, TEST_USERS.testAdmin.password);
  // If fallback needed
  if (await loginPage.errorMessage.isVisible()) {
    await loginPage.login(TEST_USERS.admin.username, TEST_USERS.admin.fallbackPassword);
  }
  await loginPage.expectSuccessfulLoginRedirect();
}

export async function loginAsUser(page: Page, username: string, password: string = 'Password123!') {
  const loginPage = new LoginPage(page);
  await loginPage.goto();
  await loginPage.login(username, password);
  await page.waitForLoadState('domcontentloaded');
}
