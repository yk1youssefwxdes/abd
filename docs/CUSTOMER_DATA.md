# School ERP — Customer Data Architecture & Isolation Specification

This document details the storage locations, lifecycle, and isolation mechanisms for all customer-created and mutable data in **School ERP**.

---

## 1. Directory Separation Principle

To guarantee that non-administrator Windows users can operate the software and to prevent data loss during application upgrades:

* **Application Directory (`C:\Program Files\SchoolERP\` / Workspace Root)**:
  * **Immutable / Read-Only** during normal operation.
  * Contains Python scripts, static templates, bundled runtime binaries, and Node dependencies.
* **Customer Data Directory (`C:\ProgramData\SchoolERP\` / `<project>/data/` in Linux development)**:
  * **Mutable / Read-Write** for all local users.
  * Contains all database files, user uploads, logs, backups, and credentials.

---

## 2. Customer Data Directory Layout

```
C:\ProgramData\SchoolERP\ (or <project>/data/)
├── database\
│   ├── database.sqlite3        <-- Main SQLite database
│   ├── database.sqlite3-wal    <-- SQLite Write-Ahead Log
│   └── database.sqlite3-shm    <-- Shared memory index
├── media\
│   └── student_photos\         <-- User-uploaded files and documents
├── backups\
│   └── school_erp_YYYYMMDD.sqlite3 <-- Automated & manual DB snapshots
├── whatsapp_session\
│   └── session\                <-- WhatsApp Web LocalAuth credentials & cache
├── logs\
│   ├── launcher.log            <-- Desktop launcher log
│   ├── django.log              <-- Django web application log
│   └── whatsapp.log            <-- WhatsApp microservice log
├── config\
│   └── run_server_config.json  <-- Dynamic ports and local API tokens
├── messages\
│   └── *.txt                   <-- Editable WhatsApp notification templates
└── licenses\
    └── license.enc             <-- Encrypted customer device license
```

---

## 3. Central Path Resolution API (`core/paths.py`)

All application code must use the central path functions:

| Function | Returned Path (Windows Production) | Returned Path (Linux Dev) |
| :--- | :--- | :--- |
| `get_data_dir()` | `C:\ProgramData\SchoolERP` | `<project>/data` |
| `get_database_path()` | `C:\ProgramData\SchoolERP\database\database.sqlite3` | `<project>/data/database/database.sqlite3` |
| `get_media_dir()` | `C:\ProgramData\SchoolERP\media` | `<project>/data/media` |
| `get_backups_dir()` | `C:\ProgramData\SchoolERP\backups` | `<project>/data/backups` |
| `get_whatsapp_session_dir()`| `C:\ProgramData\SchoolERP\whatsapp_session` | `<project>/data/whatsapp_session` |
| `get_logs_dir()` | `C:\ProgramData\SchoolERP\logs` | `<project>/data/logs` |
| `get_config_dir()` | `C:\ProgramData\SchoolERP\config` | `<project>/data/config` |
| `get_messages_dir()` | `C:\ProgramData\SchoolERP\messages` | `<project>/data/messages` |
| `get_licenses_dir()` | `C:\ProgramData\SchoolERP\licenses` | `<project>/data/licenses` |

---

## 4. Environment Variable Override

The data directory path can be explicitly overridden by setting:

```bash
export SCHOOL_ERP_DATA_DIR="/custom/path/to/school_erp_data"
```
or in Windows Command Prompt:
```cmd
set SCHOOL_ERP_DATA_DIR=D:\SchoolERPData
```
