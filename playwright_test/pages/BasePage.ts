import { Page, Locator, expect } from '@playwright/test';

export class BasePage {
  readonly page: Page;
  readonly sidebar: Locator;
  readonly toastMessages: Locator;
  readonly pageTitle: Locator;
  readonly userBadge: Locator;

  // Track console errors
  readonly consoleErrors: string[] = [];
  readonly pageErrors: Error[] = [];

  constructor(page: Page) {
    this.page = page;
    this.sidebar = page.locator('aside, #sidebar, [data-sidebar], nav').first();
    this.toastMessages = page.locator('.toast, [role="alert"], .alert, .messages li');
    this.pageTitle = page.locator('h1, h2.page-title, .header-title').first();
    this.userBadge = page.locator('#user-menu, [data-user-menu], header .user-info, .profile-badge').first();

    // Listen to console and page errors
    this.page.on('console', (msg) => {
      if (msg.type() === 'error') {
        this.consoleErrors.push(msg.text());
      }
    });

    this.page.on('pageerror', (err) => {
      this.pageErrors.push(err);
    });
  }

  async goto(path: string = '/') {
    await this.page.goto(path, { waitUntil: 'domcontentloaded' });
  }

  async expectNoErrorToasts() {
    const errorToasts = this.page.locator('.alert-error, .alert-danger, .toast-error');
    await expect(errorToasts).toHaveCount(0);
  }

  async expectSuccessToast(expectedSubstring?: string) {
    const successToast = this.page.locator('.alert-success, .toast-success, .bg-green-500, .bg-emerald-500').first();
    await expect(successToast).toBeVisible({ timeout: 5000 });
    if (expectedSubstring) {
      await expect(successToast).toContainText(expectedSubstring);
    }
  }

  async navigateViaSidebar(menuText: string) {
    const link = this.page.getByRole('link', { name: new RegExp(menuText, 'i') }).first();
    await link.click();
    await this.page.waitForLoadState('domcontentloaded');
  }

  async toggleTheme() {
    const themeBtn = this.page.locator('#theme-toggle, [data-toggle="theme"], button[aria-label*="theme"]').first();
    if (await themeBtn.isVisible()) {
      await themeBtn.click();
    }
  }

  getConsoleErrors(): string[] {
    // Filter out expected harmless messages if any
    return this.consoleErrors.filter(
      (msg) => !msg.includes('favicon.ico') && !msg.includes('tailwindcss')
    );
  }

  getPageErrors(): Error[] {
    return this.pageErrors;
  }
}
