import { test, expect, Page } from '@playwright/test';
import { DEMO_DATA } from './demo-data';
import {
  demoPause,
  sectionPause,
  waitForPageReady,
  smoothMove,
  slowClick,
  typeNaturally,
  smoothScroll,
  showDemoBanner,
  hideDemoBanner,
  highlightElement,
  setupDemoMonitoring,
  PACING,
} from './helpers/demo-actions';
import { DemoNavigation } from './helpers/demo-navigation';

test.describe('School ERP — Full Master Product Demonstration Video', () => {
  test('Complete Product Demonstration Flow', async ({ page }) => {
    // 0. Setup Environment & Error Monitoring
    const monitor = setupDemoMonitoring(page);
    const nav = new DemoNavigation(page);

    console.log('\n==================================================');
    console.log('🎬 STARTING SCHOOL ERP MASTER PRODUCT DEMONSTRATION');
    console.log('==================================================\n');

    // ─────────────────────────────────────────────────────────────
    // [01] AUTHENTICATION & LOGIN
    // ─────────────────────────────────────────────────────────────
    console.log('[01/13] Section: Authentication & Brand Login');
    await page.goto('/admin/login/');
    await waitForPageReady(page);
    await showDemoBanner(
      page,
      '01',
      DEMO_DATA.sections[0].title,
      DEMO_DATA.sections[0].subtitle
    );
    await demoPause(page, PACING.READING);

    // Enter Credentials Naturally
    const usernameInput = page.locator('input[name="username"], #id_username');
    const passwordInput = page.locator('input[name="password"], #id_password');
    const submitBtn = page.locator('input[type="submit"], button[type="submit"]');

    await slowClick(page, usernameInput, 'Focus Username Field');
    await typeNaturally(usernameInput, DEMO_DATA.adminUser.username);
    await demoPause(page, PACING.MICRO);

    await slowClick(page, passwordInput, 'Focus Password Field');
    await typeNaturally(passwordInput, DEMO_DATA.adminUser.password);
    await demoPause(page, PACING.MICRO);

    await slowClick(page, submitBtn, 'Submit Login Form');
    await waitForPageReady(page);
    await expect(page).not.toHaveURL(/\/admin\/login\//);
    console.log('  ✓ Successfully Authenticated into Dashboard');
    await sectionPause(page);

    // ─────────────────────────────────────────────────────────────
    // [02] EXECUTIVE DASHBOARD & COCKPIT
    // ─────────────────────────────────────────────────────────────
    console.log('[02/13] Section: Executive Dashboard & Cockpit');
    await showDemoBanner(
      page,
      '02',
      DEMO_DATA.sections[1].title,
      DEMO_DATA.sections[1].subtitle
    );
    await demoPause(page, PACING.STANDARD);

    // Highlight KPI Cards
    const kpiCards = page.locator('.kpi-card');
    if ((await kpiCards.count()) > 0) {
      await smoothMove(page, kpiCards.first());
      await highlightElement(page, kpiCards.first());
      await demoPause(page, PACING.MICRO);

      if ((await kpiCards.count()) > 1) {
        await smoothMove(page, kpiCards.nth(1));
        await highlightElement(page, kpiCards.nth(1));
        await demoPause(page, PACING.MICRO);
      }
    }

    // Showcase Quick Access Panels
    const quickAccess = page.locator('.qa-panel, .qa-actions').first();
    if (await quickAccess.isVisible()) {
      await smoothMove(page, quickAccess);
      await demoPause(page, PACING.MICRO);
    }

    // Smooth Scroll Down to Reveal Red List (Unpaid Students Alert)
    await smoothScroll(page, 450, 700);
    const redList = page.locator('.red-list-section, .table').first();
    if (await redList.isVisible()) {
      await smoothMove(page, redList);
      await highlightElement(page, redList);
      await demoPause(page, PACING.READING);
    }

    // Scroll Back to Top for Clean Transition
    await smoothScroll(page, 0, 500);
    await sectionPause(page);

    // ─────────────────────────────────────────────────────────────
    // [03] STUDENTS MANAGEMENT & PROFILES
    // ─────────────────────────────────────────────────────────────
    console.log('[03/13] Section: Student Information System & Enrollment');
    await nav.toStudents();
    await showDemoBanner(
      page,
      '03',
      DEMO_DATA.sections[2].title,
      DEMO_DATA.sections[2].subtitle
    );
    await demoPause(page, PACING.STANDARD);

    // Dynamic Live Search Demonstration
    const studentSearch = page.locator('#search, input[name="q"], input[type="search"]').first();
    if (await studentSearch.isVisible()) {
      await slowClick(page, studentSearch, 'Search Bar');
      await typeNaturally(studentSearch, 'Amine');
      await page.keyboard.press('Enter');
      await waitForPageReady(page);
      await demoPause(page, PACING.STANDARD);

      // Clear search to show full list
      await studentSearch.fill('');
      await page.keyboard.press('Enter');
      await waitForPageReady(page);
      await demoPause(page, PACING.MICRO);
    }

    // Open Student Detail Profile
    const firstStudentLink = page.locator('table tbody tr td a[href*="/students/"]').first();
    if (await firstStudentLink.isVisible()) {
      await slowClick(page, firstStudentLink, 'Open Student Profile');
      await waitForPageReady(page);
      await demoPause(page, PACING.READING);

      // Smoothly inspect student enrollment and payment history
      await smoothScroll(page, 350, 600);
      await demoPause(page, PACING.STANDARD);
      await smoothScroll(page, 0, 400);
    }

    // Demonstrate New Student Registration Form (Safe Deterministic Mode)
    await page.goto('/students/create/');
    await waitForPageReady(page);
    await demoPause(page, PACING.STANDARD);

    const studentNameInput = page.locator('input[name="name"], #id_name');
    const studentLevelSelect = page.locator('select[name="level"], #id_level');
    const studentPhoneInput = page.locator('input[name="phone"], #id_phone');
    const parentContactInput = page.locator('input[name="parent_contact"], #id_parent_contact');

    if (await studentNameInput.isVisible()) {
      await slowClick(page, studentNameInput, 'Student Name');
      await typeNaturally(studentNameInput, DEMO_DATA.demoStudent.newStudent.name);

      if (await studentLevelSelect.isVisible()) {
        const options = await studentLevelSelect.locator('option').all();
        for (const opt of options) {
          const val = await opt.getAttribute('value');
          if (val) {
            await studentLevelSelect.selectOption(val);
            break;
          }
        }
      }

      if (await studentPhoneInput.isVisible()) {
        await slowClick(page, studentPhoneInput, 'Student Phone');
        await typeNaturally(studentPhoneInput, DEMO_DATA.demoStudent.newStudent.phone);
      }

      if (await parentContactInput.isVisible()) {
        await slowClick(page, parentContactInput, 'Parent Contact');
        await typeNaturally(parentContactInput, DEMO_DATA.demoStudent.newStudent.parentContact);
      }

      await demoPause(page, PACING.READING);
    }

    await sectionPause(page);

    // ─────────────────────────────────────────────────────────────
    // [04] FACULTY & TEACHERS MANAGEMENT
    // ─────────────────────────────────────────────────────────────
    console.log('[04/13] Section: Faculty & Teacher Management');
    await nav.toTeachers();
    await showDemoBanner(
      page,
      '04',
      DEMO_DATA.sections[3].title,
      DEMO_DATA.sections[3].subtitle
    );
    await demoPause(page, PACING.STANDARD);

    // Inspect Teacher Profile
    const firstTeacherLink = page.locator('table tbody tr td a[href*="/teachers/"]').first();
    if (await firstTeacherLink.isVisible()) {
      await slowClick(page, firstTeacherLink, 'Open Teacher Profile');
      await waitForPageReady(page);
      await demoPause(page, PACING.READING);

      // Inspect Teacher Availability Matrix if available
      const availabilityBtn = page.locator('a[href*="/availability/"], button:has-text("Disponibilités")').first();
      if (await availabilityBtn.isVisible()) {
        await slowClick(page, availabilityBtn, 'Teacher Availability Matrix');
        await waitForPageReady(page);
        await demoPause(page, PACING.STANDARD);
      }
    }

    // Show Teacher Payroll Calculation View
    await page.goto('/payroll/teacher/');
    await waitForPageReady(page);
    await demoPause(page, PACING.READING);
    await smoothScroll(page, 300, 500);
    await demoPause(page, PACING.STANDARD);
    await smoothScroll(page, 0, 400);

    await sectionPause(page);

    // ─────────────────────────────────────────────────────────────
    // [05] ACADEMIC COURSES & LEVELS
    // ─────────────────────────────────────────────────────────────
    console.log('[05/13] Section: Academic Courses & Levels');
    await nav.toCourseGroups();
    await showDemoBanner(
      page,
      '05',
      DEMO_DATA.sections[4].title,
      DEMO_DATA.sections[4].subtitle
    );
    await demoPause(page, PACING.STANDARD);

    // Browse Course Groups Table
    const courseRows = page.locator('table tbody tr, .course-card');
    if ((await courseRows.count()) > 0) {
      await smoothMove(page, courseRows.first());
      await highlightElement(page, courseRows.first());
      await demoPause(page, PACING.STANDARD);
    }

    // Navigate to Academic Levels
    await nav.toLevels();
    await demoPause(page, PACING.READING);

    await sectionPause(page);

    // ─────────────────────────────────────────────────────────────
    // [06] ROOMS & FACILITIES
    // ─────────────────────────────────────────────────────────────
    console.log('[06/13] Section: Room & Facility Management');
    await nav.toRooms();
    await showDemoBanner(
      page,
      '06',
      DEMO_DATA.sections[5].title,
      DEMO_DATA.sections[5].subtitle
    );
    await demoPause(page, PACING.STANDARD);

    const roomRows = page.locator('table tbody tr, .room-card');
    if ((await roomRows.count()) > 0) {
      await smoothMove(page, roomRows.first());
      await highlightElement(page, roomRows.first());
      await demoPause(page, PACING.READING);
    }

    await sectionPause(page);

    // ─────────────────────────────────────────────────────────────
    // [07] MASTER SCHEDULE & INTERACTIVE TIMETABLE
    // ─────────────────────────────────────────────────────────────
    console.log('[07/13] Section: Master Schedule & Interactive Timetable');
    await nav.toWeeklySchedule();
    await showDemoBanner(
      page,
      '07',
      DEMO_DATA.sections[6].title,
      DEMO_DATA.sections[6].subtitle
    );
    await demoPause(page, PACING.STANDARD);

    // Highlight Weekly Timetable & Session Cards
    const sessionBlock = page.locator('.session-card, .session-item, [data-session-id]').first();
    if (await sessionBlock.isVisible()) {
      await smoothMove(page, sessionBlock);
      await highlightElement(page, sessionBlock);
      await demoPause(page, PACING.MICRO);

      // Click Session Block to reveal Session Details Modal / Drawer
      await sessionBlock.click();
      await demoPause(page, PACING.READING);

      // Close modal if open
      const closeModalBtn = page.locator('#sessionDetailModal .btn-close, #sessionDetailModal button:has-text("Fermer")').first();
      if (await closeModalBtn.isVisible()) {
        await closeModalBtn.click();
        await demoPause(page, PACING.MICRO);
      }
    }

    // Showcase Monthly Calendar View Briefly
    await page.goto('/schedule/monthly/');
    await waitForPageReady(page);
    await demoPause(page, PACING.READING);

    await sectionPause(page);

    // ─────────────────────────────────────────────────────────────
    // [08] LIVE SESSIONS & ATTENDANCE RECORDING
    // ─────────────────────────────────────────────────────────────
    console.log('[08/13] Section: Live Sessions & Attendance Pointage');
    await nav.toSessionsToday();
    await showDemoBanner(
      page,
      '08',
      DEMO_DATA.sections[7].title,
      DEMO_DATA.sections[7].subtitle
    );
    await demoPause(page, PACING.STANDARD);

    // Open Attendance Sheet for a Session
    const attendanceLink = page.locator('a[href*="/attendance/"]').first();
    if (await attendanceLink.isVisible()) {
      await slowClick(page, attendanceLink, 'Open Session Attendance Sheet');
      await waitForPageReady(page);
      await demoPause(page, PACING.STANDARD);

      // Demonstrate Quick Attendance Action ("Tous présents")
      const selectAllBtn = page.locator('#selectAll');
      if (await selectAllBtn.isVisible()) {
        await slowClick(page, selectAllBtn, 'Mark All Present');
        await demoPause(page, PACING.STANDARD);
      }

      // Toggle Individual Student Presence for demonstration
      const firstAttRow = page.locator('.att-row').first();
      if (await firstAttRow.isVisible()) {
        await smoothMove(page, firstAttRow);
        await firstAttRow.click();
        await demoPause(page, PACING.MICRO);
        await firstAttRow.click();
        await demoPause(page, PACING.MICRO);
      }

      // Save Attendance Sheet
      const saveAttBtn = page.locator('#save-attendance-btn, button[type="submit"]:has-text("Enregistrer")').first();
      if (await saveAttBtn.isVisible()) {
        await slowClick(page, saveAttBtn, 'Save Attendance');
        await waitForPageReady(page);
        await demoPause(page, PACING.READING);
      }
    }

    await sectionPause(page);

    // ─────────────────────────────────────────────────────────────
    // [09] CASHIER, BILLING & RECEIPT GENERATION
    // ─────────────────────────────────────────────────────────────
    console.log('[09/13] Section: Cashier, Billing & Receipt Generation');
    await nav.toCashier();
    await showDemoBanner(
      page,
      '09',
      DEMO_DATA.sections[8].title,
      DEMO_DATA.sections[8].subtitle
    );
    await demoPause(page, PACING.STANDARD);

    // Live Student Search in Cashier Register
    const cashierSearchInput = page.locator('#student-search-input');

    if (await cashierSearchInput.isVisible()) {
      await slowClick(page, cashierSearchInput, 'Student Search Box');
      await typeNaturally(cashierSearchInput, 'Amine');

      // Wait for AJAX autocomplete to populate (network-dependent)
      const dropdownItem = page.locator('#student-dropdown-list li').first();
      try {
        await dropdownItem.waitFor({ state: 'visible', timeout: 8000 });
        await slowClick(page, dropdownItem, 'Select Student from Autocomplete');
        await demoPause(page, PACING.STANDARD);
      } catch {
        // Dropdown did not appear — clear field and proceed without selecting
        console.warn('  ⚠️ Student autocomplete dropdown did not appear — skipping selection');
        await cashierSearchInput.fill('');
      }
    }

    // Set Payment Amount & Method
    const amountInput = page.locator('#amount');
    const methodSelect = page.locator('#payment_method');
    const waReceiptCheckbox = page.locator('#sendWhatsApp');

    if (await amountInput.isVisible()) {
      await amountInput.fill('');
      await typeNaturally(amountInput, DEMO_DATA.demoPayment.amount);
      await demoPause(page, PACING.MICRO);
    }

    if (await methodSelect.isVisible()) {
      await methodSelect.selectOption(DEMO_DATA.demoPayment.method);
      await demoPause(page, PACING.MICRO);
    }

    // Check WhatsApp notification toggle
    if (await waReceiptCheckbox.isVisible()) {
      await highlightElement(page, waReceiptCheckbox);
      await demoPause(page, PACING.MICRO);
    }

    // Submit Payment Form -> Redirects to Confirmation & Receipt view
    const submitPaymentBtn = page.locator('#payment-form button[type="submit"]');
    if (await submitPaymentBtn.isVisible()) {
      await slowClick(page, submitPaymentBtn, 'Confirm & Record Payment');
      await waitForPageReady(page);
      await demoPause(page, PACING.READING);

      // Showcase the Confirmation Screen with Receipt Details
      const receiptCard = page.locator('.card:has-text("Détails du paiement"), .page-title:has-text("Paiement enregistré")').first();
      if (await receiptCard.isVisible()) {
        await smoothMove(page, receiptCard);
        await highlightElement(page, receiptCard);
        await demoPause(page, PACING.READING);
      }
    }

    await sectionPause(page);

    // ─────────────────────────────────────────────────────────────
    // [10] EXECUTIVE ANALYTICS & REPORTS
    // ─────────────────────────────────────────────────────────────
    console.log('[10/13] Section: Executive Analytics & Performance Reports');
    await nav.toAnalytics();
    await showDemoBanner(
      page,
      '10',
      DEMO_DATA.sections[9].title,
      DEMO_DATA.sections[9].subtitle
    );
    await demoPause(page, PACING.STANDARD);

    // Showcase Cockpit Directeur KPIs & Visuals
    const analyticsWidgets = page.locator('.cp-kpi-card, .stat-card, .metric-card, canvas');
    if ((await analyticsWidgets.count()) > 0) {
      await smoothMove(page, analyticsWidgets.first());
      await highlightElement(page, analyticsWidgets.first());
      await demoPause(page, PACING.MICRO);
    }

    await smoothScroll(page, 400, 700);
    await demoPause(page, PACING.READING);
    await smoothScroll(page, 0, 500);

    // Demonstrate Revenue Analytics Sub-dashboard
    await page.goto('/analytics/revenue/');
    await waitForPageReady(page);
    await demoPause(page, PACING.READING);

    // Demonstrate Attendance & Absence Analytics
    await page.goto('/analytics/attendance-report/');
    await waitForPageReady(page);
    await demoPause(page, PACING.READING);

    await sectionPause(page);

    // ─────────────────────────────────────────────────────────────
    // [11] WHATSAPP COMMUNICATIONS CENTER
    // ─────────────────────────────────────────────────────────────
    console.log('[11/13] Section: WhatsApp Communications Center');
    await nav.toWhatsApp();
    await showDemoBanner(
      page,
      '11',
      DEMO_DATA.sections[10].title,
      DEMO_DATA.sections[10].subtitle
    );
    await demoPause(page, PACING.STANDARD);

    // Showcase WhatsApp Status Panel & Module Cards
    const waStatusCard = page.locator('.whatsapp-status-card, .card').first();
    if (await waStatusCard.isVisible()) {
      await smoothMove(page, waStatusCard);
      await highlightElement(page, waStatusCard);
      await demoPause(page, PACING.MICRO);
    }

    // Open Payment Reminders Module (Safe Preview Mode)
    await page.goto('/whatsapp/payment-reminders/');
    await waitForPageReady(page);
    await demoPause(page, PACING.READING);
    await smoothScroll(page, 300, 500);
    await demoPause(page, PACING.STANDARD);
    await smoothScroll(page, 0, 400);

    // Open Bulk Announcements Composer
    await page.goto('/whatsapp/bulk-announcements/');
    await waitForPageReady(page);
    await demoPause(page, PACING.READING);

    await sectionPause(page);

    // ─────────────────────────────────────────────────────────────
    // [12] SYSTEM SETTINGS & CONFIGURATION
    // ─────────────────────────────────────────────────────────────
    console.log('[12/13] Section: System Settings & School Configuration');
    await nav.toSettings();
    await showDemoBanner(
      page,
      '12',
      DEMO_DATA.sections[11].title,
      DEMO_DATA.sections[11].subtitle
    );
    await demoPause(page, PACING.STANDARD);

    // Switch between Configuration Tabs
    const tabFinance = page.locator('#tab-finance-btn');
    if (await tabFinance.isVisible()) {
      await slowClick(page, tabFinance, 'Settings Tab: Reçus & Paiements');
      await demoPause(page, PACING.STANDARD);
    }

    const tabWhatsApp = page.locator('#tab-whatsapp-btn');
    if (await tabWhatsApp.isVisible()) {
      await slowClick(page, tabWhatsApp, 'Settings Tab: Alertes WhatsApp');
      await demoPause(page, PACING.STANDARD);
    }

    const tabSchool = page.locator('#tab-school-btn');
    if (await tabSchool.isVisible()) {
      await slowClick(page, tabSchool, 'Settings Tab: Identité du Centre');
      await demoPause(page, PACING.STANDARD);
    }

    await sectionPause(page);

    // ─────────────────────────────────────────────────────────────
    // [13] SECURE SESSION SIGN-OFF & LOGOUT
    // ─────────────────────────────────────────────────────────────
    console.log('[13/13] Section: Secure Sign-off & Logout');
    await showDemoBanner(
      page,
      '13',
      DEMO_DATA.sections[12].title,
      DEMO_DATA.sections[12].subtitle
    );
    await demoPause(page, PACING.STANDARD);

    // Clean Logout & Session Invalidation
    await page.context().clearCookies();
    await page.goto('/admin/login/');
    await waitForPageReady(page);
    await expect(page).toHaveURL(/\/admin\/login\//);

    await hideDemoBanner(page);
    await demoPause(page, PACING.READING);

    // Final Report Verification
    const errors = monitor.getErrors();
    if (errors.length > 0) {
      console.warn(`⚠️ Warning: ${errors.length} non-fatal runtime notices recorded:`);
      errors.forEach((e) => console.warn(`   ${e}`));
    } else {
      console.log('✅ ZERO Critical JavaScript or Network Errors Recorded.');
    }

    console.log('\n==================================================');
    console.log('🎉 SCHOOL ERP PRODUCT DEMO COMPLETED SUCCESSFULLY');
    console.log('==================================================\n');
  });
});
