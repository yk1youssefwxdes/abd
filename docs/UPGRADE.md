# School ERP — Software Upgrade & Data Preservation Guide

This document explains how software updates (e.g. from version 1.0.0 to 1.1.0) are performed safely without risking customer data loss.

---

## 1. Upgrade Architecture

Because all mutable customer data is housed in `C:\ProgramData\SchoolERP\`, updating the software simply involves replacing the immutable files in `C:\Program Files\SchoolERP\`:

```
Upgrade Action:
1. Overwrite C:\Program Files\SchoolERP\ with new application code & runtimes.
2. Leave C:\ProgramData\SchoolERP\ completely intact.
3. On first launch, Django applies any new database migrations automatically.
```

---

## 2. Inno Setup Upgrade Behavior

In the Inno Setup installer:
* `[Setup] AppId={{D3A4B889-497B-4E65-B62C-38A2A82939B1}}` ensures Inno Setup detects an existing installation and performs an in-place upgrade.
* `[Files]` installs only into `{app}` (`C:\Program Files\SchoolERP`).
* `[Dirs]` creates `{commonappdata}\SchoolERP` if not already present, but **never overwrites or deletes existing files**.

---

## 3. Database Schema Migration During Upgrade

When a new version introduces database schema changes:
1. The developer generates migrations via `python manage.py makemigrations`.
2. The migration files are packaged inside `core/migrations/`.
3. When the customer launches the updated application, `run_server.py` runs `call_command('migrate', interactive=False)` before starting the server.
4. Existing customer records are preserved, and new columns/tables are added automatically.

---

## 4. Rollback & Disaster Recovery

Before applying a major upgrade, customers can create a snapshot backup:
* Backups are located at `C:\ProgramData\SchoolERP\backups\school_erp_YYYYMMDD_HHMMSS.sqlite3`.
* To restore a backup, simply copy the desired `.sqlite3` backup file over `C:\ProgramData\SchoolERP\database\database.sqlite3` while the server is stopped.
