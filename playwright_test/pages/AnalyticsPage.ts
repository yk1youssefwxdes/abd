import { Page, Locator, expect } from '@playwright/test';
import { BasePage } from './BasePage';

export class AnalyticsPage extends BasePage {
  readonly charts: Locator;
  readonly statWidgets: Locator;
  readonly exportPdfBtn: Locator;
  readonly exportCsvBtn: Locator;

  constructor(page: Page) {
    super(page);
    this.charts = page.locator('canvas, .chartjs-render-monitor, svg.apexcharts-svg');
    this.statWidgets = page.locator('.stat-card, .kpi-card, .metric-card');
    this.exportPdfBtn = page.locator('a[href*="/pdf/"], button:has-text("PDF"), a:has-text("PDF")').first();
    this.exportCsvBtn = page.locator('a[href*="/csv/"], button:has-text("CSV"), a:has-text("CSV")').first();
  }

  async gotoDashboard() {
    await this.page.goto('/analytics/dashboard/', { waitUntil: 'domcontentloaded' });
  }

  async gotoRevenue() {
    await this.page.goto('/analytics/revenue/', { waitUntil: 'domcontentloaded' });
  }

  async gotoAttendance() {
    await this.page.goto('/analytics/attendance-report/', { waitUntil: 'domcontentloaded' });
  }

  async gotoOperational() {
    await this.page.goto('/analytics/operational/', { waitUntil: 'domcontentloaded' });
  }

  async gotoRooms() {
    await this.page.goto('/analytics/rooms/', { waitUntil: 'domcontentloaded' });
  }

  async gotoTeachers() {
    await this.page.goto('/analytics/teachers/', { waitUntil: 'domcontentloaded' });
  }

  async gotoStudents() {
    await this.page.goto('/analytics/students/', { waitUntil: 'domcontentloaded' });
  }
}
