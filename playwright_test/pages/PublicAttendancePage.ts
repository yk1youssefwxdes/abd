import { Page, Locator, expect } from '@playwright/test';
import { BasePage } from './BasePage';

export class PublicAttendancePage extends BasePage {
  readonly teacherSelect: Locator;
  readonly credentialInput: Locator;
  readonly submitBtn: Locator;
  readonly errorMessage: Locator;

  constructor(page: Page) {
    super(page);
    this.teacherSelect = page.locator('#teacher, select[name="teacher_id"]');
    this.credentialInput = page.locator('#credential, input[name="credential"]');
    this.submitBtn = page.locator('.btn-submit, button[type="submit"]');
    this.errorMessage = page.locator('.error-message, .alert-danger');
  }

  async goto() {
    await this.page.goto('/public/attendance/', { waitUntil: 'domcontentloaded' });
  }

  async login(teacherId: string, phoneOrEmail: string) {
    await this.teacherSelect.selectOption(teacherId);
    await this.credentialInput.fill(phoneOrEmail);
    await this.submitBtn.click();
  }
}
