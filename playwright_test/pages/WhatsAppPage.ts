import { Page, Locator, expect } from '@playwright/test';
import { BasePage } from './BasePage';

export class WhatsAppPage extends BasePage {
  readonly statusCard: Locator;
  readonly reminderCards: Locator;
  readonly restartBtn: Locator;
  readonly logoutBtn: Locator;

  constructor(page: Page) {
    super(page);
    this.statusCard = page.locator('.card, .status-card').first();
    this.reminderCards = page.locator('.reminder-item, table tbody tr, .card');
    this.restartBtn = page.locator('button:has-text("Redémarrer"), #btn-restart-wa');
    this.logoutBtn = page.locator('button:has-text("Déconnexion"), #btn-logout-wa');
  }

  async gotoDashboard() {
    await this.page.goto('/whatsapp/', { waitUntil: 'domcontentloaded' });
  }

  async gotoPaymentReminders() {
    await this.page.goto('/whatsapp/payment-reminders/', { waitUntil: 'domcontentloaded' });
  }

  async gotoAbsenceNotifications() {
    await this.page.goto('/whatsapp/absence-notifications/', { waitUntil: 'domcontentloaded' });
  }

  async gotoBulkAnnouncements() {
    await this.page.goto('/whatsapp/bulk-announcements/', { waitUntil: 'domcontentloaded' });
  }
}
