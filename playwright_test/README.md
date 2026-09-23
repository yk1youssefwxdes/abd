# School ERP — Playwright End-to-End Test Suite

This directory contains the automated end-to-end (E2E) testing framework for the Django School ERP application, built with [Playwright](https://playwright.dev/) and TypeScript.

---

## 1. Requirements

- **Node.js** >= 18.x (tested on Node v24.x)
- **Python** 3.10+ with active project virtualenv (`../venv`)
- **Chromium / WebKit / Firefox** (managed via Playwright)

---

## 2. Installation & Setup

From within the `playwright_test/` directory:

```bash
# 1. Install Node dependencies
npm install

# 2. Install Playwright browser binaries
npx playwright install chromium

# 3. Seed deterministic test database (users, rooms, teachers, levels, students)
npm run setup:db
```

---

## 3. Running the Tests

### A. Run all tests (headless by default):
```bash
npm test
```

### B. Run in headed browser mode (watch interactions visually):
```bash
npm run test:headed
```

### C. Run with Playwright interactive UI mode:
```bash
npm run test:ui
```

### D. Run in step-by-step debug mode:
```bash
npm run test:debug
```

### E. Run a specific test suite or test file:
```bash
# Run authentication tests only
npx playwright test tests/01_auth/

# Run student CRUD tests
npx playwright test tests/04_students/student_crud.spec.ts

# Run a specific test by title
npx playwright test -g "01.05 Should successfully login"
```

---

## 4. Environment Variables

You can configure test runs using standard environment variables:

| Variable | Default | Description |
|---|---|---|
| `PLAYWRIGHT_BASE_URL` | `http://127.0.0.1:8000` | Target Django server URL |
| `CI` | `false` | When true, enables retries and disables interactive features |
| `AUTO_LICENSE` | `true` | Bypasses hardware checks for testing environments |

Example:
```bash
PLAYWRIGHT_BASE_URL=http://staging.school-erp.com npx playwright test
```

---

## 5. Test Suite Architecture & Directory Layout

```text
playwright_test/
├── package.json                    # Project dependencies & scripts
├── playwright.config.ts            # Configuration (timeouts, reporters, webServer)
├── tsconfig.json                   # TypeScript configuration
├── README.md                       # Documentation
│
├── fixtures/                       # Reusable test fixtures & constants
│   ├── auth.fixture.ts             # Auth helper functions (loginAsAdmin, loginAsUser)
│   ├── base.fixture.ts             # Extended test fixture providing all POMs & error logging
│   └── test-data.ts                # Deterministic test users and entities
│
├── pages/                          # Page Object Models (POM)
│   ├── BasePage.ts                 # Common layout, alerts, errors & navigation
│   ├── LoginPage.ts                # Login screen interactions
│   ├── CockpitPage.ts              # Dashboard & KPIs
│   ├── StudentsPage.ts             # Student directory, creation, detail, and editing
│   ├── TeachersPage.ts             # Teacher CRUD, availability, leaves & payroll
│   ├── RoomsPage.ts                # Rooms directory & capacity
│   ├── CoursesPage.ts              # Course groups & weekly schedules
│   ├── LevelsPage.ts               # Academic levels & categories
│   ├── SchedulePage.ts             # Visual weekly & monthly calendar
│   ├── CashierPage.ts              # Payment recording & student search
│   ├── WhatsAppPage.ts             # WhatsApp reminders & announcements
│   ├── AnalyticsPage.ts            # Executive analytics & charts
│   ├── PublicAttendancePage.ts     # Standalone teacher attendance portal
│   ├── PublicKioskPage.ts          # Parent/student kiosk portal
│   └── SystemSettingsPage.ts       # School configuration & profile
│
├── tests/                          # Categorized test specifications
│   ├── 01_auth/                    # Login, logout, permissions & protected URLs
│   ├── 02_navigation/              # Navbar, active links, 404 & responsive viewports
│   ├── 03_cockpit/                 # KPI metrics & quick access
│   ├── 04_students/                # Student CRUD & enrollment management
│   ├── 05_teachers/                # Teacher CRUD, availability, leaves & payroll
│   ├── 06_courses_and_levels/      # Course groups, levels & categories
│   ├── 07_rooms/                   # Room equipment & capacity
│   ├── 08_schedule_and_sessions/   # Visual schedule, today, attendance, conflicts
│   ├── 09_cashier_and_payments/    # Cashier payment forms, search & receipts
│   ├── 10_whatsapp_center/         # Reminders, alerts, bulk announcements
│   ├── 11_analytics/               # Dashboards, metrics & export endpoints
│   ├── 12_public_portals/          # Public teacher attendance & parent kiosk
│   ├── 13_settings_and_admin/      # System settings & Django Unfold Admin
│   └── 14_security_and_errors/     # CSRF token enforcement & zero JS page errors
│
└── utils/
    └── test_db_setup.py            # Deterministic test database seeder
```

---

## 6. HTML Test Reports & Failure Debugging

When tests complete or fail, view the comprehensive HTML report:

```bash
npm run test:report
```

The report includes:
- Test step execution timings
- Action traces & screenshots at point of failure
- Video recordings for failed runs
- Network requests & browser console logs
