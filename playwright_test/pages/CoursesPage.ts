import { Page, Locator, expect } from '@playwright/test';
import { BasePage } from './BasePage';

export class CoursesPage extends BasePage {
  readonly nameInput: Locator;
  readonly levelSelect: Locator;
  readonly teacherSelect: Locator;
  readonly roomSelect: Locator;
  readonly monthlyFeeInput: Locator;
  readonly maxStudentsInput: Locator;
  readonly submitBtn: Locator;
  readonly groupRows: Locator;

  constructor(page: Page) {
    super(page);
    this.nameInput = page.locator('input[name="name"], #id_name');
    this.levelSelect = page.locator('select[name="level"], #id_level');
    this.teacherSelect = page.locator('select[name="teacher"], #id_teacher');
    this.roomSelect = page.locator('select[name="room"], #id_room');
    this.monthlyFeeInput = page.locator('input[name="monthly_fee"], #id_monthly_fee');
    this.maxStudentsInput = page.locator('input[name="max_students"], #id_max_students');
    this.submitBtn = page.locator('button[type="submit"], input[type="submit"]');
    this.groupRows = page.locator('table tbody tr, .course-card');
  }

  async gotoList() {
    await this.page.goto('/courses/', { waitUntil: 'domcontentloaded' });
  }

  async gotoCreate() {
    await this.page.goto('/courses/create/', { waitUntil: 'domcontentloaded' });
  }

  async fillCourseGroupForm(data: {
    name: string;
    monthlyFee: string;
    maxStudents?: string;
  }) {
    await this.nameInput.fill(data.name);
    // select first non-empty option for level, teacher, room if available
    const selects = [this.levelSelect, this.teacherSelect, this.roomSelect];
    for (const sel of selects) {
      if (await sel.isVisible()) {
        const options = await sel.locator('option').all();
        for (const opt of options) {
          const val = await opt.getAttribute('value');
          if (val) {
            await sel.selectOption(val);
            break;
          }
        }
      }
    }
    await this.monthlyFeeInput.fill(data.monthlyFee);
    if (data.maxStudents && (await this.maxStudentsInput.isVisible())) {
      await this.maxStudentsInput.fill(data.maxStudents);
    }
  }

  async submit() {
    await this.submitBtn.first().click();
  }
}
