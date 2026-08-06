# User Manual
## Blade Rocking & Creep Test Management System

This manual explains how to use the system day-to-day. For technical/architecture detail, see [TECHNICAL_DESIGN.md](TECHNICAL_DESIGN.md).

---

## Table of Contents

1. [Overview](#1-overview)
2. [Getting Started](#2-getting-started)
3. [Core Concepts](#3-core-concepts)
4. [OH Operator Guide](#4-oh-operator-guide)
5. [Assembly Operator Guide](#5-assembly-operator-guide)
6. [QA Viewer Guide](#6-qa-viewer-guide)
7. [Super Admin Guide](#7-super-admin-guide)
8. [Features Available to Everyone](#8-features-available-to-everyone)
9. [Hardware Devices](#9-hardware-devices)
10. [Troubleshooting & FAQ](#10-troubleshooting--faq)

---

## 1. Overview

The system tracks turbine blades through a complete overhaul cycle: incoming inspection and measurement at the **OH Station** (701 Hanger), then set-making and balancing at the **Assembly Station** (720 Hanger) for LPTR blades, and finally return and sign-off back at OH. Every blade's history — every measurement, every status change, every operator who touched it — is recorded automatically and can never be silently overwritten.

Blades are entered and tracked **90 at a time** in a **Work Order**. A Work Order is always one blade type only — either **LPTR** (which travels through Assembly) or **HPTR** (which stays at the OH station the whole time).

---

## 2. Getting Started

### Logging In

Open the application in your browser and sign in with the **Email/Username** and **Password** given to you by your Super Admin. There is no self-service sign-up or "forgot password" link — if you're locked out or need an account, ask a Super Admin.

After login you land on your role's home page:

| Role | Home page |
|------|-----------|
| Super Admin | Operations Dashboard |
| QA Viewer | QA Dashboard (read-only) |
| OH Operator | Work Order Overview (Batch Tracking) |
| Assembly Operator | Work Order Overview (Batch Tracking) |

### The Sidebar

The left sidebar (hover to expand) shows only the pages your role can use:

| Link | Who sees it | Goes to |
|------|-------------|---------|
| Dashboard | Super Admin, QA Viewer | Operations / QA dashboard |
| Batch Overview | Super Admin, OH Operator, Assembly Operator | Work Order Overview |
| Blade Entry | Super Admin, OH Operator | Create/resume a Work Order |
| OH Queue | Super Admin, OH Operator | Blade list at the OH station |
| Rocking & Creep | Super Admin, OH Operator | Enter rocking/creep values |
| HPTR Slot Allocation | Super Admin, OH Operator | Slot + balancing for HPTR |
| Assembly Queue | Super Admin, Assembly Operator | Blade list at Assembly |
| LPTR Slot Allocation | Super Admin, Assembly Operator | Slot + balancing for LPTR |
| Reports | Everyone | Generate/download reports |
| Notifications | Super Admin, OH Operator, Assembly Operator | Unread alerts |
| User Management | Super Admin only | Create/edit/lock users |
| Settings | Everyone | Profile, password, preferences |

A notification bell runs in the background the whole time you're logged in — status changes, rejections, and finished reports pop up as toasts even if you're on an unrelated page.

---

## 3. Core Concepts

- **Work Order** — a batch of exactly 90 blades of one type (LPTR or HPTR), identified by a Work Order Number, Shop Order Number, and Part Number.
- **Blade** — one physical turbine blade, identified within its Work Order by a Serial Number (01–90).
- **Blade Type**
  - **LPTR** — requires both a Rocking value and a Creep value; travels to the Assembly station for set-making and balancing, then returns to OH for final sign-off.
  - **HPTR** — requires only a Rocking value; never leaves the OH station — slot allocation and balancing both happen there.
- **Status** — every blade moves through a fixed sequence of states (created → inspected → measured → sent/slotted → balanced → verified → completed), enforced by the system so steps can't be skipped or done out of order. Any blade can be rejected at most stages; only a Super Admin can reopen a rejected blade.
- **Static Moment** — calculated automatically from weight (`weight (g) × 1.57 × 20`); you never enter it directly.

### Simplified blade journey

```
LPTR:  Created → Entered at OH → Measured (weight, rocking, creep) → Sent to Assembly
       → Received & Verified at Assembly → Slot Assigned (HAL) → Balanced
       → Returned to OH → Final Verification → Completed

HPTR:  Created → Entered at OH → Measured (weight, rocking) → Slot Assigned (HAL)
       → Balanced → Final Verification → Completed

Any stage → Rejected → (Super Admin only) → Reopened → back to inspection
```

---

## 4. OH Operator Guide

Your work happens in this order: **create a Work Order → enter 90 blades → record rocking/creep → send LPTR to Assembly (or slot HPTR directly) → accept LPTR batches back from Assembly → final verification.**

### 4.1 Creating a Work Order and Entering Blades

Go to **Blade Entry**.

1. Fill in the header form: **Work Order Number**, **Shop Order Number**, **Part Number** (required), **Engine Number** (optional), **Engine Hours** / **Component Hours** (as `HH:MM:SS`).
2. Pick the blade type using the two large buttons: **LPTR** ("Rocking + Creep") or **HPTR** ("Rocking only"). This cannot be changed later.
3. Either:
   - Click **Start Blade Entry** to create the Work Order with 90 blank rows, or
   - Click **Upload Excel to Start** to create the Work Order and bulk-populate rows from a spreadsheet in one step (a results dialog lists any rows that failed to import, with the reason).

You're now in the **90-row grid**. For each row:

- Type or scan the **Melt Number**. The camera icon opens a modal that OCR-scans a blade marking photo (via the OAK-1 industrial camera if attached, or your browser webcam otherwise) and fills the field for you. The keyboard icon opens an on-screen Cyrillic keyboard for melt numbers stamped in Russian.
- Enter the **Weight**. If a weighing scale is connected, the field auto-fills live from the scale the moment you focus that row (look for the "Scale live" indicator in the header).
- Click the **Lock** icon once melt number and weight are correct. Locking saves the row, disables further edits, and automatically moves you to the next row and opens the camera for its melt number — designed as a hands-free "scan → lock → next" rhythm. Click the lock icon again on a saved row if you need to unlock and correct it.
- Rows autosave a fraction of a second after you stop typing; a spinner, then a green check, confirms the save. A red icon means the save failed — click it to retry, or use the **Retry All** button if several rows failed at once. Don't navigate away while a save is still pending — the browser will warn you.

You can bulk-correct existing rows at any time with **Upload Excel** inside the grid.

**To resume work later:** open **Blade Entry** again — a **Resume Blade Entry** panel lists every Work Order that isn't yet fully entered; search and click one to jump back into its grid.

**To finish:** click **Save / Complete** at the bottom. If any row is missing its melt number/weight, or two rows share a melt number, a dialog lists exactly which rows are wrong (click a row number to jump to it) — fix them and click **Re-check**. Once all 90 rows pass, the Work Order is locked for entry and becomes eligible for measurement.

### 4.2 The OH Queue

Go to **OH Queue** to work with individual blades or whole batches.

- Filter by **search** (serial/melt number) or by **batch** dropdown.
- LPTR batch cards at the top show entry progress and a **Continue Blade Entry** or **Send to Assembly** button (plus **Send to Assembly Anyway** if the batch isn't fully measured).
- The table lets you **View** a blade, **Send** it individually, **Reopen** a rejected blade, or **Delete** a blade that hasn't progressed far yet (with a confirmation prompt).
- **Send Batch to Assembly** sends every ready blade in a selected batch at once — a confirmation dialog tells you exactly how many blades will actually move.

### 4.3 Recording Rocking & Creep Values

Go to **Rocking & Creep** and pick a Work Order (only ones with entry complete and rocking/creep not yet finished are listed).

For each blade, type the **Rocking Value** (and **Creep Value** for LPTR — the field shows "N/A (HPTR)" for HPTR blades, which don't have a creep test). Values autosave shortly after you stop typing, or on Enter/blur.

If a **DTI gauge** is connected, each button-press on the physical gauge fills whichever cell is currently active and automatically advances to the next unfilled cell in that column — you don't need to click into each row yourself. Duplicate/repeated gauge readings are ignored automatically.

An out-of-range HPTR rocking value (outside 0.5–1.8) is flagged with a warning icon so you can double-check it before saving.

Once every blade in the Work Order has its required value(s), click **Complete Rocking & Creep** to close out this stage.

### 4.4 HPTR Slot Allocation & Balancing (stays at OH)

Because HPTR blades never go to Assembly, you handle their set-making and balancing directly on **HPTR Slot Allocation**:

1. **Slot Allocation** tab — enter **Start Slot**, **Total Slots on Rotor**, and **Rotor Unbalance (g)**, then click **Run Allocation** to compute the slot layout.
2. **Set Making** tab — review the W1/W2 weight totals and the balance banner ("Set is balanced" / "Not balanced yet — target X g"). Manually swap two slots if needed, or click **Suggest Swap** for a system-proposed pair and **Apply** it. Click **Save & Assign Slots** once satisfied.
3. **Balancing** tab — review the saved slot table, **Export Excel** if you need a copy, and once physical balancing is done on the machine, confirm with the **"Physical balancing confirmed?" Save** button.

A **Pending Physical Balancing** list on this page lets you jump straight back into any Work Order still waiting on that final confirmation.

### 4.5 Accepting LPTR Batches Back from Assembly

Once Assembly has balanced and sent a batch back, go to **Batch Overview** — a **"Returned from Assembly — Needs Acceptance"** panel appears at the top. Click **Accept** on a batch to bring it back under OH control. Once accepted, a **"Final Report Ready"** panel appears with **Preview** (an expandable table of slot/serial/melt/weight/rocking/creep) and **Download Final Report** buttons.

### 4.6 Final Verification & Completion

Open a blade's detail page (from OH Queue or Batch Overview) once balancing is complete — a **Final Verification** button appears there to move it to the final sign-off state, after which it can be marked **Completed**.

---

## 5. Assembly Operator Guide

Your work happens in this order (LPTR only — HPTR never reaches you): **receive the Work Order → verify each blade → accept/reject/modify → run set-making (HAL) → confirm physical balancing → send back to OH.**

### 5.1 Assembly Queue

**Assembly Queue** is your landing page. Stat tiles show **Incoming**, **In Progress**, and **Completed** blade counts. The **Batches** table lists Work Orders that have reached Assembly, with a **Mark Received** button for any batch OH has sent — click it to formally receive the batch (this copies over OH's final measurements for comparison and notifies OH).

Below that, a tabbed blade list (**Incoming / Verifying / In Progress / Completed**) lets you drill into individual blades, with **View** and (once slotted) an **Update Balancing** shortcut into Slot Allocation.

### 5.2 Verifying Blades

Click **Accept** or open the batch to reach the **verification workspace** for that Work Order. Select a blade from the left-hand list (status dots show pending/verified/rejected, with an overall progress bar). For the selected blade:

- **Identity Scan** — scan or type the **QR Code**, **OCR Blade Number**, and **Melt Number**; each shows a live Match/Mismatch badge against the blade's actual record.
- **Assembly Weight** — auto-fills live from the connected scale; click **Lock** once correct. The page shows OH's reference weight and the delta against the ±0.5 g tolerance.

Click **Submit Verification** to see a pass/fail comparison table and a suggested action, then choose:

- **Accept** — moves the blade to Assembly-Verified.
- **Reject** — requires a typed reason, then **Confirm Rejection**.
- **Modify Data** — correct a field (melt number, part number, weight, etc.) with a required reason; the blade must then be re-verified.

Once every expected blade is verified, click **Start Set-Making** at the top of this page.

**Modify Batch** and **Accept Batch** pages offer the same accept/modify actions at a whole-batch level if you'd rather review all blades in two side-by-side tables before a single **Confirm Accept**.

### 5.3 LPTR Slot Allocation & Balancing

Go to **LPTR Slot Allocation** and select the accepted batch. Work through the tabs in order:

1. **Empty Rotor** — enter the pre-installation unbalance slot and value, then **Save Reading**.
2. **Stage 1 (46 blades)** — click **Run Stage 1 Allocation** to compute a preview slot map (shown as W1/W2 tables side by side). Use the **Slot A / Slot B** swap control to manually correct any pair, then **Save Stage 1**.
3. **Stage 2 (44 blades)** — same pattern for the remaining blades, then **Save Stage 2**.
4. **Balancing** — once both stages are saved, confirm physical balancing with **Save**, then click **Send Back to OH** to hand the batch back.

Summary cards above the tabs show **Pending Physical Balancing** and **Ready to Send Back to OH** batches with one-click buttons so you don't have to search for them. **Export Excel** downloads the saved slot sheet plus the balancing/corrections audit trail at any point.

---

## 6. QA Viewer Guide

You have **read-only** access everywhere. Your home page, **QA Dashboard**, mirrors the Operations Dashboard — KPI tiles, station cards, Active Batches, and Status Distribution — but with no create/edit buttons. It also shows your 5 most recent reports with **Download** links, and a **Generate New Report** button that takes you to the Reports page. Use **Reports** to export blade lists, Work Order reports, or slot sheets in Excel/PDF for audits.

---

## 7. Super Admin Guide

You have every OH Operator and Assembly Operator capability, plus:

### 7.1 Operations Dashboard

Your home page adds **New Blade Entry** and **Assembly Queue** shortcuts, an **Active Work Order** switcher, and the same KPI/status panels QA sees, with a manual **Refresh**.

### 7.2 User Management

Go to **User Management** to see every user (search + role-filter tabs). Click **Create User** to set Full Name, Email, Username, Password, **Role** (Super Admin / OH Operator / Assembly Operator / QA Viewer), and optional Station. Use the row actions to **Edit** a user's name/role/station, **Lock/Unlock** their account, or **Delete** them.

### 7.3 Reopening Rejected Blades

Only you can bring a rejected blade back into the workflow. Find it (OH Queue, Assembly Queue, or Blade Detail) and click **Reopen** — it returns to inspection so it can be re-measured and re-processed from the start.

### 7.4 System Configuration & OCR Dataset (Settings page)

Under **Settings**, you have an extra **System Configuration** section (Workflow Lock, Notify-on-Rejection toggles) and an **OCR Training Dataset** section — toggle "Mismatches only" and click **Download Dataset (.zip)** to export captured melt-number OCR scans, useful for improving OCR accuracy over time.

### 7.5 Audit Trail

Every HTTP request and every domain action (status changes, corrections, rejections) is logged immutably. If you need the full trail for a compliance review, it's available via the audit log endpoint — ask your technical contact if you need this pulled for you, since there's no dedicated audit-log page in the UI yet.

---

## 8. Features Available to Everyone

### 8.1 Notifications

**Notifications** shows your unread alerts only, grouped by date. Clicking one marks it read and, if it references a blade, opens that blade's detail page. **Mark All Read** clears the list. The page also polls automatically every 15 seconds, and a toast/bell popup fires in real time no matter which page you're on.

### 8.2 Blade Detail & Workflow Timeline

Click any blade's serial number to open its **Blade Detail** page: identity, latest measurements (with a rocking-vs-creep chart), OCR data (with mismatch flag if the OCR reading disagreed with the manual entry), current slot allocation, and a condensed timeline panel. Click **Timeline** for the full-page, printable **Workflow Timeline** — every status change with who did it, from which station, and when, plus **Print** / **Export PDF** buttons.

### 8.3 Reports

Go to **Reports**:

- **Batch Report** tab — search/select a Work Order, choose **Excel** or **PDF**, preview it, then **Generate & Download**.
- **My Reports** tab — every report you've requested, with status (auto-refreshing while anything is still generating), **Download** once ready, and **Delete**.

Large reports generate in the background — you'll get a notification when one finishes if you navigate away before it's ready.

### 8.4 Settings & Profile

Under **Settings**: update your display name and see your email/username/role (**Save Profile**); change your password (**Update Password**, with current/new/confirm fields); and toggle which notification types you want to see (status changes, rejections, slot assignments, system alerts).

---

## 9. Hardware Devices

These are physical instruments at each station that feed data straight into the forms you're using — you don't need to operate any separate software for them day-to-day.

| Device | Where it's used | What you'll see |
|--------|------------------|------------------|
| **Weighing scale** (Adam Equipment iScale i-04) | Blade Entry grid, Rocking & Creep, Assembly Verification | A "Scale live"/"Scale offline" indicator; the weight field auto-fills the moment you focus a row. |
| **DTI gauge** (Sylvac BT) | Rocking & Creep page | A "DTI connected"/"offline" indicator; pressing the gauge fills the active cell and auto-advances to the next one. |
| **Camera / OCR** (OAK-1 industrial camera, or your browser webcam as fallback) | Melt Number scanning in Blade Entry; QR/OCR/melt scanning in Assembly Verification | A camera icon opens a scan modal; if an OAK-1 is plugged in, a small toggle in the modal lets you switch between it and your webcam. |
| **QR scanner** (USB barcode gun) | Assembly Verification identity scan | Acts like a keyboard — just click into the QR field and scan; no special mode needed. |

If a device shows "offline," you can always type the value in manually — nothing is blocked by a missing instrument.

---

## 10. Troubleshooting & FAQ

**I can't log in / forgot my password.**
There's no self-service reset. Ask a Super Admin to check your account or reset your password via User Management.

**A page says "Access Denied."**
You're logged in with a role that doesn't have permission for that page. Check the message for which role is required, and ask a Super Admin if you believe your role is wrong.

**A row/blade won't save (red icon).**
Click the red icon to retry, or use **Retry All** in the Blade Entry grid. If it keeps failing, check your network connection — the system will warn you before letting you navigate away with unsaved changes.

**The scale/DTI gauge isn't auto-filling.**
Check the "live"/"connected" indicator on the page. If it shows offline, the bridge script on that workstation may not be running — you can still type values in manually while it's investigated.

**I made a mistake in Assembly verification after accepting.**
Use **Modify Data** during verification (before accepting) whenever possible — it requires a reason and keeps the audit trail clean. If a blade needs to go back to OH after a rejection, only a Super Admin can **Reopen** it.

**Why can't I mix LPTR and HPTR blades in one Work Order?**
The system enforces one blade type per Work Order (90 blades each) because LPTR and HPTR follow different workflows — HPTR never leaves the OH station, while LPTR must go through Assembly.

**Where do I find a printable/signable copy of a blade's inspection record?**
Use **Reports → Batch Report** for a Work Order-level export, or open a blade's **Workflow Timeline** and use **Print**/**Export PDF** for a single-blade history.
