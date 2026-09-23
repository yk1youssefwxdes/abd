import { Page, Locator, expect } from '@playwright/test';
import { BasePage } from './BasePage';

export class CockpitPage extends BasePage {
  readonly kpiCards: Locator;
  readonly quickAccessLinks: Locator;
  readonly searchInput: Locator;

  constructor(page: Page) {
    super(page);
    this.kpiCards = page.locator('.kpi-card');
    this.quickAccessLinks = page.locator('.qa-card');
    this.searchInput = page.locator('.navbar-search-input, input[type="search"]').first();
  }

  async goto() {
    await this.page.goto('/', { waitUntil: 'domcontentloaded' });
  }

  async expectKpisLoaded() {
    await expect(this.kpiCards.first()).toBeVisible({ timeout: 5000 });
    const count = await this.kpiCards.count();
    expect(count).toBeGreaterThanOrEqual(1);
  }

  async searchNavbar(query: string) {
    await this.searchInput.fill(query);
  }
}
