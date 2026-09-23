import { Page, Locator, expect } from '@playwright/test';
import { BasePage } from './BasePage';

export class PublicKioskPage extends BasePage {
  readonly kioskInput: Locator;
  readonly searchBtn: Locator;
  readonly studentCards: Locator;
  readonly keyButtons: Locator;

  constructor(page: Page) {
    super(page);
    this.kioskInput = page.locator('#searchQueryInput, input[name="search_query"], #kiosk-input, input[name="q"]').first();
    this.searchBtn = page.locator('.keypad-btn-submit, #btn-search-kiosk, button[type="submit"]').first();
    this.studentCards = page.locator('.student-kiosk-card, .card');
    this.keyButtons = page.locator('.keypad-btn, .key-btn');
  }

  async goto() {
    await this.page.goto('/public/kiosk/', { waitUntil: 'domcontentloaded' });
  }

  async searchStudent(codeOrPhone: string) {
    await this.kioskInput.fill(codeOrPhone);
    // submit search form
    const form = this.page.locator('#searchForm, form').first();
    await form.evaluate((f: HTMLFormElement) => f.submit());
    await this.page.waitForLoadState('domcontentloaded');
  }
}
