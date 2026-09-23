import { Page, Locator, expect } from '@playwright/test';
import { BasePage } from './BasePage';

export class LevelsPage extends BasePage {
  readonly nameInput: Locator;
  readonly categorySelect: Locator;
  readonly orderInput: Locator;
  readonly submitBtn: Locator;
  readonly levelRows: Locator;

  constructor(page: Page) {
    super(page);
    this.nameInput = page.locator('input[name="name"], #id_name');
    this.categorySelect = page.locator('select[name="category"], #id_category');
    this.orderInput = page.locator('input[name="order"], #id_order');
    this.submitBtn = page.locator('button[type="submit"], input[type="submit"]');
    this.levelRows = page.locator('table tbody tr, .level-item');
  }

  async gotoList() {
    await this.page.goto('/levels/', { waitUntil: 'domcontentloaded' });
  }

  async gotoCreate() {
    await this.page.goto('/levels/create/', { waitUntil: 'domcontentloaded' });
  }

  async gotoCategoriesList() {
    await this.page.goto('/level-categories/', { waitUntil: 'domcontentloaded' });
  }

  async fillLevelForm(data: { name: string; order?: string }) {
    await this.nameInput.fill(data.name);
    if (data.order && (await this.orderInput.isVisible())) {
      await this.orderInput.fill(data.order);
    }
  }

  async submit() {
    await this.submitBtn.first().click();
  }
}
