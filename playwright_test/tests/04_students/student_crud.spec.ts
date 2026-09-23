import { test, expect } from '../../fixtures/base.fixture';
import { loginAsAdmin } from '../../fixtures/auth.fixture';

test.describe('Students - CRUD Operations Suite', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('04.01 Should display students list with search and action buttons', async ({ studentsPage }) => {
    await studentsPage.gotoList();
    await expect(studentsPage.studentRows.first()).toBeVisible();
    await expect(studentsPage.addStudentBtn).toBeVisible();
  });

  test('04.02 Should search students by name or code', async ({ studentsPage, page }) => {
    await studentsPage.gotoList();
    await studentsPage.search('Amine');
    await expect(page.locator('body')).toContainText('Amine');
  });

  test('04.03 Should validate required fields on student creation', async ({ studentsPage, page }) => {
    await studentsPage.gotoCreate();
    await studentsPage.submit();
    await expect(page).toHaveURL(/\/students\/create\//);
  });

  test('04.04 Should successfully create a new student', async ({ studentsPage, page }) => {
    const timestamp = Date.now();
    const studentName = `AutoTest Student ${timestamp}`;

    await studentsPage.gotoCreate();
    await studentsPage.fillStudentForm({
      name: studentName,
      phone: '0699887766',
      parentName: 'Parent AutoTest',
      parentContact: '0611224455',
    });
    await studentsPage.submit();
    await expect(page).not.toHaveURL(/\/students\/create\//);
  });

  test('04.05 Should view student detail page', async ({ page }) => {
    await page.goto('/students/1/');
    await expect(page).toHaveURL(/\/students\/1\//);
    await expect(page.locator('h1, h2, .student-name, .page-title').first()).toBeVisible();
  });
});
