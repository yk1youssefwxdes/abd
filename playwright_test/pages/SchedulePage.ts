import { Page, Locator, expect } from '@playwright/test';
import { BasePage } from './BasePage';

export class SchedulePage extends BasePage {
  readonly calendarGrid: Locator;
  readonly sessionBlocks: Locator;
  readonly prevWeekBtn: Locator;
  readonly nextWeekBtn: Locator;
  readonly todayBtn: Locator;
  readonly filterTeacher: Locator;
  readonly filterRoom: Locator;
  readonly attendanceRows: Locator;
  readonly saveAttendanceBtn: Locator;

  constructor(page: Page) {
    super(page);
    this.calendarGrid = page.locator('.schedule-table, .schedule-grid, .calendar-grid, #calendar, .timetable-grid, table.table').first();
    this.sessionBlocks = page.locator('.session-card, .session-item, .event-card, [data-session-id]');
    this.prevWeekBtn = page.locator('a:has-text("Précédent"), button:has-text("Précédent"), [aria-label*="prev"]');
    this.nextWeekBtn = page.locator('a:has-text("Suivant"), button:has-text("Suivant"), [aria-label*="next"]');
    this.todayBtn = page.locator('a:has-text("Aujourd\'hui"), button:has-text("Aujourd\'hui")');
    this.filterTeacher = page.locator('select[name="teacher"], #filter-teacher');
    this.filterRoom = page.locator('select[name="room"], #filter-room');
    this.attendanceRows = page.locator('.attendance-row, table tbody tr');
    this.saveAttendanceBtn = page.locator('button[type="submit"], #save-attendance-btn');
  }

  async gotoWeekly() {
    await this.page.goto('/schedule/', { waitUntil: 'domcontentloaded' });
  }

  async gotoMonthly() {
    await this.page.goto('/schedule/monthly/', { waitUntil: 'domcontentloaded' });
  }

  async gotoToday() {
    await this.page.goto('/sessions/today/', { waitUntil: 'domcontentloaded' });
  }

  async gotoConflicts() {
    await this.page.goto('/schedule/conflicts/', { waitUntil: 'domcontentloaded' });
  }
}
