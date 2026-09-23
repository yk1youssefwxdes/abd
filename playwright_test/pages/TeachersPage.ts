import { Page, Locator, expect } from '@playwright/test';
import { BasePage } from './BasePage';

export class TeachersPage extends BasePage {
  readonly nameInput: Locator;
  readonly phoneInput: Locator;
  readonly emailInput: Locator;
  readonly paymentMethodSelect: Locator;
  readonly hourlyRateInput: Locator;
  readonly percentageInput: Locator;
  readonly sessionRateInput: Locator;
  readonly submitBtn: Locator;
  readonly teacherRows: Locator;
  readonly searchInput: Locator;

  constructor(page: Page) {
    super(page);
    this.nameInput = page.locator('input[name="name"], #id_name');
    this.phoneInput = page.locator('input[name="phone"], #id_phone');
    this.emailInput = page.locator('input[name="email"], #id_email');
    this.paymentMethodSelect = page.locator('select[name="payment_method"], #id_payment_method');
    this.hourlyRateInput = page.locator('input[name="hourly_rate"], #id_hourly_rate');
    this.percentageInput = page.locator('input[name="payment_percentage"], #id_payment_percentage');
    this.sessionRateInput = page.locator('input[name="session_rate"], #id_session_rate');
    this.submitBtn = page.locator('button[type="submit"], input[type="submit"]');
    this.teacherRows = page.locator('table tbody tr, .teacher-card');
    this.searchInput = page.locator('#teacher-search, input[name="q"], input[type="search"]').first();
  }

  async gotoList() {
    await this.page.goto('/teachers/', { waitUntil: 'domcontentloaded' });
  }

  async gotoCreate() {
    await this.page.goto('/teachers/create/', { waitUntil: 'domcontentloaded' });
  }

  async fillTeacherForm(data: {
    name: string;
    phone: string;
    email?: string;
    paymentMethod?: string;
    rate?: string;
  }) {
    await this.nameInput.fill(data.name);
    await this.phoneInput.fill(data.phone);
    if (data.email) await this.emailInput.fill(data.email);
    if (data.paymentMethod) {
      await this.paymentMethodSelect.selectOption(data.paymentMethod);
    }
  }

  async submit() {
    await this.submitBtn.first().click();
  }
}
