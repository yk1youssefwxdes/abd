import { Page, Locator, expect } from '@playwright/test';
import { BasePage } from './BasePage';

export class SystemSettingsPage extends BasePage {
  readonly schoolNameInput: Locator;
  readonly schoolAddressInput: Locator;
  readonly schoolPhoneInput: Locator;
  readonly schoolEmailInput: Locator;
  readonly submitBtn: Locator;

  constructor(page: Page) {
    super(page);
    this.schoolNameInput = page.locator('input[name="school_name"], #id_school_name');
    this.schoolAddressInput = page.locator('input[name="school_address"], textarea[name="school_address"], #id_school_address');
    this.schoolPhoneInput = page.locator('input[name="school_phone"], #id_school_phone');
    this.schoolEmailInput = page.locator('input[name="school_email"], #id_school_email');
    this.submitBtn = page.locator('button[type="submit"], input[type="submit"]');
  }

  async goto() {
    await this.page.goto('/settings/', { waitUntil: 'domcontentloaded' });
  }

  async fillSettings(data: { name?: string; phone?: string; email?: string }) {
    if (data.name && (await this.schoolNameInput.isVisible())) {
      await this.schoolNameInput.fill(data.name);
    }
    if (data.phone && (await this.schoolPhoneInput.isVisible())) {
      await this.schoolPhoneInput.fill(data.phone);
    }
    if (data.email && (await this.schoolEmailInput.isVisible())) {
      await this.schoolEmailInput.fill(data.email);
    }
  }

  async submit() {
    await this.submitBtn.first().click();
  }
}
