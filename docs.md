# School ERP Documentation

## Overview

`school_erp` is a Django-based school management system designed to manage students, teachers, courses, schedules, payments, attendance, payroll, analytics, and WhatsApp messaging automation. It includes both a web application and a local server controller for desktop deployment.

The project is structured around a single Django app named `core` and a custom admin interface built on `django-unfold`.

---

## Administrator User Guide

This section is written for school administrators and managers who use the system daily. It explains the main workflows without any development details.

### Accessing the System

- Open the application on your browser at `http://127.0.0.1:8000/`.
- Log in using your admin username and password.
- If the system is deployed with a license, make sure the license is valid before use.

### Main Dashboard

- The dashboard is the first screen after login.
- It shows key summary metrics for students, teachers, payments, sessions, and attendance.
- Use the top or sidebar navigation to go to the specific area you need.

### Student Management

- Go to `Students` to view the list of all enrolled students.
- Use `Create` to add a new student record.
- On a student record, you can:
  - edit personal information,
  - view current course enrollments,
  - check payment status,
  - print or download student details.
- Use `Enrollment` controls to add or remove a student from a course group.

### Teacher Management

- Go to `Teachers` to manage all teachers.
- Add or edit teacher details such as contact information, hourly rate, payment method, and active status.
- Use teacher availability and leave sections to define when a teacher is available or unavailable.
- Check the teacher detail page to see assigned groups and teaching schedule.

### Course and Schedule Management

- Use `Courses` to create and maintain course groups.
- Each course group includes a subject, assigned teacher, monthly price, and optional WhatsApp group link.
- Use the `Schedule` area to define weekly meeting times and room assignments.
- The system checks for room and teacher conflicts and alerts you when schedules overlap.

### Payments and Cashier

- Go to `Cashier` to record payments for students.
- Enter the student, amount, payment method, and month covered.
- The system generates a receipt PDF automatically.
- If the student has a parent contact, you can send payment confirmation using WhatsApp.
- Use the payment search feature to find unpaid students and follow up with reminders.

### Attendance Tracking

- Track attendance by session or by student.
- Use the attendance report to view student presence and absences.
- The system stores attendance records for each session and course group.

### WhatsApp Automation

- The `WhatsApp` area manages automated messaging.
- Send payment reminders to parents who have unpaid balances.
- Send absence notifications for students who miss classes.
- Send bulk announcements for school news or events.
- Use session reminders to notify parents or teachers about upcoming classes.

### Analytics and Reports

- Open `Analytics` for revenue, attendance, student retention, teacher load, and room usage reports.
- Export reports to PDF or CSV when needed.
- Use analytics to monitor:
  - total revenue,
  - payment collection rates,
  - attendance trends,
  - student churn,
  - classroom occupancy,
  - teacher payroll and substitutions.

### Public Portals

- The system supports a teacher attendance portal and a parent kiosk portal.
- These portals are designed for quick access without requiring administrator login.

### Daily Workflow Suggestions

- Start your day by checking the dashboard and analytics for payment and attendance alerts.
- Review new student signups and update course enrollments.
- Record payments as they arrive and generate receipts.
- Send WhatsApp reminders for unpaid fees and absence notices.
- Verify the schedule and correct any session conflicts before the next class.

### Useful Tips

- Always use the `Print` or `Export` buttons when you need offline records.
- Search for students by name, matricule, or phone number to find records quickly.
- When editing schedules, save changes and confirm that no conflicts are reported.
- Use the `Is Active` toggle to temporarily hide students, teachers, or groups without deleting them.
- Regularly check the WhatsApp service status if automatic messages are not sending.

---

## Key Features

- Student management: records, enrollments, payment status, and attendance.
- Teacher management: payment methods, availability, leaves, and payroll.
- Course scheduling: course groups, weekly schedules, room assignment, conflict detection.
- Session management: scheduled sessions, manual overrides, substitute teachers, makeup sessions.
- Payments & receipts: monthly payments, receipt generation, unpaid student tracking.
- Attendance tracking: student attendance records, absence analytics.
- Analytics & reporting: dashboards for revenue, attendance, teacher load, room occupancy, and churn.
- WhatsApp automation: payment reminders, absence notifications, bulk announcements, session reminders.
- Licensing: device-bound license validation to prevent unauthorized execution.

---

## Project Structure

- `manage.py`: Django entrypoint with license validation.
- `run_server.py`: local desktop server controller wrapper.
- `requirements.txt`: Python dependencies.
- `school_erp/`: Django project module.
  - `settings.py`: Django settings and custom admin UI configuration.
  - `urls.py`: URL routing to Django admin and `core` app.
- `core/`: main Django app.
  - `models.py`: domain entities and business rules.
  - `views.py`: web views and AJAX endpoints.
  - `forms.py`: forms and validation logic.
  - `urls.py`: app-specific URL routes.
  - `admin.py`: custom admin site, admin registration, import/export resources.
  - `analytics.py`: analytics and reporting logic.
  - `utils.py`: helper functions for finance, schedules, WhatsApp templates, PDF exports.
  - `license.py`: license validation logic.
  - `tests.py`: test coverage for core behaviors.
- `templates/`: HTML templates for the app and admin.
- `static/` and `staticfiles/`: CSS, JS, and static assets.
- `messages/`: WhatsApp message templates.
- `whatsapp_service/`: Node.js background service for WhatsApp automation.
- `tools/`: support scripts for license creation, encryption, fingerprint generation, and project obfuscation.

---

## Dependencies

The project depends on these main packages:

- Python / Django:
  - `Django==5.2.15`
  - `django-extensions`
  - `django-filter`
  - `django-htmx`
  - `django-import-export`
  - `django-unfold`
- Utilities:
  - `reportlab`
  - `openpyxl`
  - `pillow`
  - `tzdata`
- Development / tools:
  - `ipython`
  - `django-extensions`

The WhatsApp service depends on Node.js packages:

- `express`
- `qrcode`
- `whatsapp-web.js`
- `bytenode`

---

## Setup and Installation

### Python/backend setup

1. Create and activate a Python virtual environment.
2. Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3. Apply migrations:

```bash
python manage.py migrate
```

4. Create a superuser if needed:

```bash
python manage.py createsuperuser
```

5. Collect static files if deploying to production:

```bash
python manage.py collectstatic --noinput
```

### WhatsApp service setup

From the `whatsapp_service/` directory:

```bash
cd whatsapp_service
npm install
npm start
```

- Use `npm run dev` during development if `nodemon` is available.
- The service is used by the Django app for WhatsApp automation endpoints.

---

## Running the Application

### Web application

Use Django's built-in server:

```bash
python manage.py runserver
```

Access the application in the browser at `http://127.0.0.1:8000/`.

### Local desktop server controller

`run_server.py` launches a Tkinter-based controller that can start the Django local server and open the browser.

```bash
python run_server.py
```

This script will:
- auto-relaunch using a local `venv` if one exists
- validate the license before launching

---

## Licensing

The project implements license validation in:

- `manage.py`
- `school_erp/settings.py`
- `core/apps.py`
- `run_server.py`

License data is loaded from `license.enc` and validated against a fingerprint generated by `core/hardware.py`. The license must include:

- `LICENSED_FINGERPRINT`
- `START_DATE`
- `END_DATE`

If the device fingerprint or license date is invalid, the application exits.

### License creation tools

There are supporting scripts under `tools/` for license generation and encryption:

- `tools/create_license.py`: vendor-side license creator
- `tools/encrypt_license.py`: encrypt license payload
- `tools/fingerprint_generator.py`: generate device fingerprint

---

## Core Application Modules

### `core/models.py`

Primary domain entities:

- `Room`: class room definition and capacity.
- `Teacher`: instructor with payment settings.
- `TeacherAvailability`: weekly available/unavailable time windows.
- `TeacherLeave`: leave periods for teachers.
- `LevelCategory`: academic program categories.
- `Level`: academic levels.
- `CourseGroup`: course group with subject, price, teacher, and WhatsApp link.
- `CourseGroupSchedule`: weekly schedule entries with room and conflict validation.
- `Student`: student record, contact data, and generated `matricule`.
- `Enrollment`: student enrollment in course groups with schedule conflict validation.
- `Payment`: student payment record, receipt number generation, prorated payment details.
- `Attendance`: student attendance tracking per date and course group.
- `Session`: scheduled meeting instance, substitute teacher support, exception classification.
- `Holiday`: school holidays and affected groups.
- `TeacherAvailability`: teacher weekly availability and unavailable slots.
- `WhatsAppSendLog`: logs for WhatsApp messages sent by automation.
- `MakeupSession`: makeup session management for canceled sessions.
- `Announcement`: general announcements and event notices.

### `core/views.py`

Contains the web-facing endpoints for:

- student CRUD and enrollment handling
- course group and level management
- teacher management, availability, leaves
- schedule and session planning
- attendance and reporting
- payment creation and receipt download
- payroll export
- WhatsApp dashboard and automation endpoints
- public portals for teacher attendance and kiosk access
- analytics endpoints and export views

### `core/forms.py`

Defines forms and validation logic for:

- `StudentForm`
- `EnrollmentForm`
- `CourseGroupForm`
- `LevelForm`
- `SessionForm`
- `CourseGroupScheduleFormSet`

Validation includes schedule conflict detection for student enrollments and teacher availability.

### `core/utils.py`

Helper utilities for:

- date and month calculations
- student monthly fee calculation and prorated fee logic
- revenue and unpaid student helpers
- PDF receipt generation
- WhatsApp template formatting
- schedule generation and session conflict detection

### `core/analytics.py`

Analytics classes for:

- revenue and collection reports
- attendance trends and heatmaps
- student churn and enrollment metrics
- teacher payroll, load, and substitution analytics
- room occupancy and capacity efficiency
- operational session completion and cancellation health

### `core/admin.py`

Custom admin enhancements:

- `TonarozAdminSite`, a custom Unfold-based admin site
- analytics pages integrated into `/admin/analytics/...`
- import/export resources for Room, Teacher, CourseGroup, Student, Payment
- inline admin classes for enrollments and payments
- custom filters and admin routing

---

## URL Routing

### Main routing

- `admin/` → Django admin
- `` (root) → `core.urls`

### `core` app routes

Important user-facing routes include:

- `/students/`, `/teachers/`, `/courses/`, `/levels/`
- `/schedule/` and `/sessions/`
- `/cashier/payment/create/`
- `/whatsapp/` automation routes
- `/analytics/` dashboards
- `/public/attendance/` teacher portal
- `/public/kiosk/` kiosk portal

---

## WhatsApp Integration

The app supports WhatsApp automation through the `whatsapp_service` background process and templates in `messages/`. It includes:

- payment reminder messages
- absence notification messages
- bulk announcement messages
- payment confirmations
- session reminders
- automated send / restart / logout AJAX endpoints

The background service is a separate Node.js app located in `whatsapp_service/`.

---

## Development and Testing

### Running tests

Run Django tests:

```bash
python manage.py test
```

### Important scripts and helpers

- `tools/setup_levels.py`: helper to bootstrap academic levels.
- `tools/setup_sites.py`: helper to configure Django sites.
- `tools/generate_sessions.py`: session generation utilities.

### Notes

- The project uses Django `Site` framework and `django-unfold` for admin styling.
- Many model save operations call `full_clean()` to enforce validation at runtime.
- The application relies on the `license.enc` file and the `LICENSE_EXTRA_SECRET` environment variable if present.

---

## Deployment Notes

- For production, set `DEBUG = False` in `school_erp/settings.py`.
- Update `ALLOWED_HOSTS` in `school_erp/settings.py`.
- Ensure `SECRET_KEY` is protected.
- Configure web server and WSGI entrypoint via `school_erp/wsgi.py`.
- If using `waitress`, it is available in `requirements.txt`.

---

## Troubleshooting

### License errors

- `license.enc` missing or invalid: the application will fail to start.
- If the license is expired, the app exits with a trial expiration message.
- Use `tools/fingerprint_generator.py` and `tools/create_license.py` to generate valid licenses.

### WhatsApp service

- Ensure the Node.js service is running separately.
- Make sure the service can reach the browser session or WhatsApp Web session it depends on.

### Static assets

- Run `python manage.py collectstatic --noinput` in production.
- Verify `STATIC_ROOT` is configured if deploying outside the built-in server.

---

## Notes for Maintainers

- `school_erp/settings.py` defines custom UI values such as `SCHOOL_NAME`, `SCHOOL_ADDRESS`, and `UNFOLD` sidebar content.
- `core.apps.CoreConfig.ready()` validates the license once at Django startup.
- `CourseGroup` and `CourseGroupSchedule` save signals keep session data in sync.
- Pricing logic includes prorated fees for mid-month enrollments.
- Admin analytics live under `/admin/analytics/...` and are implemented in `core/admin.py` plus `core/analytics.py`.

---

## Contact for Support

If you need help or want to extend the system:

- Review the `core` app first for business rules.
- Use `tests.py` as examples of expected behavior.
- Keep the license and WhatsApp automation logic separate from the core Django flow.

---

## Summary

`school_erp` is a complete school ERP system combining:

- operational school management
- financial and attendance tracking
- teacher payroll oversight
- analytics dashboards
- WhatsApp automation
- license-protected deployment

This `docs.md` is intended to help developers understand installation, usage, and the codebase structure.
