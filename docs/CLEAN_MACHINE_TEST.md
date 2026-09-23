# School ERP — Clean Windows Machine Testing Protocol

This test protocol verifies that **School ERP** functions correctly on a completely clean Windows 10 or Windows 11 PC that has **no development tools installed**.

---

## 1. Test Environment Assumptions

* **Operating System**: Windows 10 (64-bit) or Windows 11 (64-bit).
* **Installed Prerequisites**: None (No Python, No Node.js, No npm, No Google Chrome, No Git).
* **User Account Type**: Standard Non-Administrator User (Installer requires admin rights once during installation).

---

## 2. Step-by-Step Test Procedure

| Step # | Action | Expected Result | Pass/Fail |
| :--- | :--- | :--- | :--- |
| **1. Install** | Double-click `SchoolERP_Setup_v1.0.0.exe` and follow wizard. | Installs files into `C:\Program Files\SchoolERP\` and initializes `C:\ProgramData\SchoolERP\`. | [ ] |
| **2. Launch** | Launch School ERP from the Desktop or Start Menu shortcut. | Launcher window opens without error. Status shows "Stopped". | [ ] |
| **3. Start Server** | Click **"Start Server"** in the controller GUI. | Django server starts on port ~8000. WhatsApp starts on port ~3000. Status turns Green ("Running"). | [ ] |
| **4. Browser UI** | Default web browser opens to `http://127.0.0.1:8000/`. | School ERP login / cockpit page displays cleanly with CSS/images. | [ ] |
| **5. Database Init** | Perform initial login or view student list. | Database operations succeed without "no such table" errors. | [ ] |
| **6. WhatsApp Service** | Open WhatsApp dashboard (`/whatsapp/`). | Status shows "QR_RECEIVED" or "READY". QR code renders if not authenticated. | [ ] |
| **7. Persistence** | Authenticate WhatsApp (or create student record). | Data is saved to `C:\ProgramData\SchoolERP\`. | [ ] |
| **8. Stop Server** | Click **"Stop Server"** in the controller GUI. | Waitress stops. Node and Chromium terminate cleanly. Status turns Red ("Stopped"). | [ ] |
| **9. Reopen Test** | Click **"Start Server"** again. | Services start immediately without "browser is already running" or port lock errors. | [ ] |
| **10. Upgrade Test** | Run newer installer version over existing installation. | App is upgraded, previous student data and WhatsApp session remain 100% intact. | [ ] |
| **11. Non-Admin Test** | Run School ERP under a restricted standard Windows user account. | Works with zero permission errors (read-only app, writable `ProgramData`). | [ ] |
