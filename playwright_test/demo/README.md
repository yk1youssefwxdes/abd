# School ERP — Master Product Demonstration Video Automation

This directory contains a dedicated, presentation-quality Playwright automation suite designed to record a smooth, human-paced **product demonstration video** of the School ERP application.

Unlike standard test suites, this demo is optimized for **clarity, visual storytelling, natural mouse kinematics, and cinematic pacing** suitable for prospective clients, school administrators, and stakeholders.

---

## 📁 Directory Structure

```text
playwright_test/demo/
├── demo.config.ts              # Playwright configuration tuned for video recording (1440x900)
├── demo-data.ts                # Deterministic fictional demo dataset & section titles
├── school_erp_demo.spec.ts     # Master presentation script covering all 13 core modules
├── helpers/
│   ├── demo-actions.ts         # Natural pacing, smooth mouse curves, HUD overlays & glow highlights
│   └── demo-navigation.ts      # Top navigation & dropdown interactions
├── recordings/                 # Output folder for generated .webm demo videos
└── README.md                   # Complete documentation & usage guide
```

---

## 🎬 Demonstrated Workflows & Storyline

The demonstration presents a cohesive story of school management across 13 structured chapters:

| Section | Module | Key Features Demonstrated |
|---|---|---|
| **01** | **Authentication** | Branded login page, credentials entry, seamless transition |
| **02** | **Cockpit Dashboard** | Monthly revenue stats, active student/teacher KPIs, unpaid alerts & Red List |
| **03** | **Students Management** | Live search, student detail profile, enrollments, new student enrollment form |
| **04** | **Teachers & Faculty** | Teacher directory, faculty profile, availability matrix, teacher payroll |
| **05** | **Courses & Levels** | Academic course groups, monthly pricing, academic levels hierarchy |
| **06** | **Rooms & Facilities** | Facilities directory, capacity, equipment badges (Projector, AC, Lab) |
| **07** | **Master Schedule** | Interactive weekly timetable grid, session modal preview, monthly view |
| **08** | **Attendance Recording** | Today's sessions list, live pointage, "Tous présents" bulk action, save feedback |
| **09** | **Cashier & Billing** | Student autocomplete search, tuition calculation, payment modes, official receipt |
| **10** | **Executive Analytics** | Cockpit Directeur KPIs, revenue trends, attendance analytics, PDF exports |
| **11** | **WhatsApp Center** | Hub status, payment reminders with templates, absence alerts, announcements |
| **12** | **System Settings** | School identity (name, contact), financial rules, WhatsApp automations |
| **13** | **Secure Sign-off** | Clean logout returning to the branded login screen |

---

## 🚀 Quick Start & Usage

### 1. Ensure Django Backend & Test Database are Ready

From the repository root:

```bash
# Seed deterministic test data
./venv/bin/python playwright_test/utils/test_db_setup.py

# (Optional) Start server manually if not using Playwright's webServer
./venv/bin/python manage.py runserver 127.0.0.1:8000
```

### 2. Run the Demo Video Recording

From `playwright_test/`:

```bash
# A. Record video in headless mode (standard presentation speed)
npm run demo

# B. Watch the demo visually in real-time in a headed browser
npm run demo:headed

# C. Fast execution mode (double speed for quick validation)
npm run demo:fast
```

---

## ⚙️ Configuration & Environment Variables

You can customize the demo behavior using environment variables:

| Variable | Default | Description |
|---|---|---|
| `PLAYWRIGHT_BASE_URL` | `http://127.0.0.1:8000` | Target URL of the School ERP server |
| `DEMO_USERNAME` | `admin` | Demo administrator account username |
| `DEMO_PASSWORD` | `1234` | Demo administrator account password |
| `DEMO_SPEED` | `1.0` | Pacing factor (`1.0` = natural ~3-5 min video, `0.5` = 2x faster, `1.5` = slower) |

Example:
```bash
DEMO_SPEED=1.2 npm run demo:headed
```

---

## 📹 Video Output & Artifacts

- **Video Format**: High-definition `.webm` video at **1440 × 900** resolution (16:10 standard desktop presentation).
- **Location**: Generated videos are automatically saved to:
  ```text
  playwright_test/demo/recordings/<test-name>/video.webm
  ```
- **Visual Features Included in Recording**:
  - Floating glassmorphism **HUD Chapter Banner** displaying current module and subtitle.
  - Animated **spotlight glow** highlighting clicked buttons, search inputs, and KPI cards.
  - Smooth Bézier **human-like mouse movements** instead of instant cursor teleportation.

---

## 🛡️ Error Handling & Idempotency

- The demo monitors the browser for uncaught JavaScript exceptions, console errors, and HTTP 500 status codes.
- All student, course, and payment actions are idempotent and deterministic, allowing the demo to be re-run indefinitely without data duplication.
