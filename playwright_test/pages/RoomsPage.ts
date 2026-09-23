import { Page, Locator, expect } from '@playwright/test';
import { BasePage } from './BasePage';

export class RoomsPage extends BasePage {
  readonly roomCards: Locator;
  readonly roomRows: Locator;

  constructor(page: Page) {
    super(page);
    this.roomCards = page.locator('.room-card, .card');
    this.roomRows = page.locator('table tbody tr, .room-item');
  }

  async gotoList() {
    await this.page.goto('/rooms/', { waitUntil: 'domcontentloaded' });
  }

  async expectRoomsVisible() {
    const count = await this.roomCards.count();
    expect(count).toBeGreaterThanOrEqual(1);
  }
}
