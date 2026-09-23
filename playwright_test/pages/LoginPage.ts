import { Page, Locator, expect } from '@playwright/test';
import { BasePage } from './BasePage';

export class LoginPage extends BasePage {
  readonly usernameInput: Locator;
  readonly passwordInput: Locator;
  readonly submitButton: Locator;
  readonly errorMessage: Locator;

  constructor(page: Page) {
    super(page);
    this.usernameInput = page.locator('input[name="username"], #id_username');
    this.passwordInput = page.locator('input[name="password"], #id_password');
    this.submitButton = page.locator('input[type="submit"], button[type="submit"]');
    this.errorMessage = page.locator('.errornote, .alert-danger, .error, [role="alert"], .text-red-600, .bg-red-50');
  }

  async goto() {
    await this.page.goto('/admin/login/', { waitUntil: 'domcontentloaded' });
  }

  async login(username: string, password: string) {
    await this.usernameInput.fill(username);
    await this.passwordInput.fill(password);
    await this.submitButton.click();
    await this.page.waitForLoadState('domcontentloaded');
  }

  async expectLoginError() {
    // Either stays on login URL or shows error message
    await expect(this.page).toHaveURL(/\/admin\/login\//);
  }

  async expectSuccessfulLoginRedirect() {
    // Should redirect away from /admin/login/
    await expect(this.page).not.toHaveURL(/\/admin\/login\//);
  }
}
