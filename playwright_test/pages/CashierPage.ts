import { Page, Locator, expect } from '@playwright/test';
import { BasePage } from './BasePage';

export class CashierPage extends BasePage {
  readonly studentSearchInput: Locator;
  readonly studentDropdown: Locator;
  readonly studentDropdownItems: Locator;
  readonly studentHiddenInput: Locator;
  readonly monthCoveredSelect: Locator;
  readonly amountInput: Locator;
  readonly paymentMethodSelect: Locator;
  readonly sendWhatsAppCheckbox: Locator;
  readonly submitBtn: Locator;

  constructor(page: Page) {
    super(page);
    this.studentSearchInput = page.locator('#student-search-input');
    this.studentDropdown = page.locator('#student-dropdown');
    this.studentDropdownItems = page.locator('#student-dropdown-list li');
    this.studentHiddenInput = page.locator('#student-hidden');
    this.monthCoveredSelect = page.locator('#month_covered');
    this.amountInput = page.locator('#amount');
    this.paymentMethodSelect = page.locator('#payment_method');
    this.sendWhatsAppCheckbox = page.locator('#sendWhatsApp');
    this.submitBtn = page.locator('#payment-form button[type="submit"]');
  }

  async goto() {
    await this.page.goto('/cashier/payment/create/', { waitUntil: 'domcontentloaded' });
  }

  async selectStudent(query: string) {
    await this.studentSearchInput.fill(query);
    await expect(this.studentDropdown).toBeVisible({ timeout: 5000 });
    await expect(this.studentDropdownItems.first()).toBeVisible({ timeout: 5000 });
    await this.studentDropdownItems.first().click();
  }

  async fillPayment(data: { amount: string; method?: string }) {
    await this.amountInput.fill(data.amount);
    if (data.method) {
      await this.paymentMethodSelect.selectOption(data.method);
    }
  }

  async submit() {
    await this.submitBtn.click();
  }
}
