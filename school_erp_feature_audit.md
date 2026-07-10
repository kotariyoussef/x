# school_erp System Feature Audit

## 1. Core Domain Entities

- `Room`
  - Classroom name, capacity, active/inactive state
  - Schedule conflict validation

- `Teacher`
  - Contact info, email
  - Payment settings: hourly, percentage, per-session
  - Active/inactive lifecycle

- `TeacherAvailability`
  - Weekly availability slots
  - Available / unavailable time ranges
  - Time ordering validation

- `TeacherLeave`
  - Date ranges with leave type and notes
  - Used by scheduling and availability checks

- `LevelCategory`
  - Academic category grouping
  - Auto-generated code slug

- `Level`
  - Academic level associated to category
  - Used by students and course groups

- `CourseGroup`
  - Class definition with subject, level, monthly price
  - Assigned teacher and WhatsApp group link
  - Active/inactive state

- `CourseGroupSchedule`
  - Weekly schedule for each course group
  - Day, start/end times, room assignment
  - Room and teacher conflict validation

- `Student`
  - Personal and parent contact data
  - Level, main school, notes
  - Auto-generated unique matricule
  - Active/inactive state

- `Enrollment`
  - Student ↔ CourseGroup many-to-many link
  - Active flag and next payment date
  - Schedule overlap prevention
  - Initial payment and prorated enrollment helpers

- `Payment`
  - Monthly payments tied to student
  - Status (PAID/PENDING/CANCELLED)
  - Auto receipt number generation
  - Locked payment records
  - Prorated payment details and student balance logic

- `Attendance`
  - Daily presence records per student/course/day
  - Present/absent status
  - Unique attendance constraint per student/course/date

- `Session`
  - Individual class meeting instance
  - Group, schedule, date/time, room
  - Substitute teacher support
  - Status (PLANNED/DONE/CANCELLED)
  - Manual edit tracking and session exception handling

- `Holiday`
  - School holiday or break dates
  - Affects all groups or selected groups

- `MakeupSession`
  - Makeup session linked to original cancelled session
  - Selected students and notes

- `WhatsAppSendLog`
  - Record of WhatsApp messages sent via automation
  - Message type, status, error detail, timestamp

## 2. Main Web App Features

### Student Management

- List, create, edit, delete students
- Student detail page with enrollments, payments, balances
- Print/export student list PDF
- Enrollment add/remove flows
- AJAX search endpoints for students and unpaid students

### Teacher Management

- List, create, edit, delete teachers
- Teacher detail page with course groups, availability, leaves, session summary
- Print/export teacher list PDF
- AJAX teacher search endpoint

### Course / Level Management

- Course group CRUD
- Course group schedule inline creation and editing
- Course group deletion confirmation with related counts
- Level category CRUD
- Level CRUD and detailed level page

### Scheduling & Sessions

- Weekly schedule dashboard with room/teacher view
- Monthly calendar schedule view
- Session create/edit/delete workflows
- Attendance per session
- Quick AJAX session status update
- Session detail AJAX modal endpoint
- Create/update/reset session AJAX endpoints
- Exceptions list and reset-to-default functionality
- On-demand session generation for date ranges
- Makeup session planning for canceled sessions
- Schedule conflict reporting and AJAX validation

### Cashier / Payments

- Payment creation view
- Receipt PDF generation
- Payment month coverage tracking and next payment date updates
- WhatsApp payment confirmation
- Payment search and filtering flows

### Attendance & Reporting

- Attendance report aggregated by student and course
- Attendance analytics dashboard
- At-risk student detection with WhatsApp follow-up links

### WhatsApp Integration

- WhatsApp service dashboard and connection status
- Payment reminders for unpaid students
- Absence notifications for absent students
- Bulk announcement message builder
- Payment confirmation message generator
- Session reminder message generator
- AJAX endpoints for link generation, send, logout, restart
- Attachments support for bulk announcements

## 3. Analytics & Reporting

### Admin KPI / Dashboard

- KPIs API counts for students, teachers, groups, payments, sessions, rooms
- Admin statistics page with monthly revenue, room usage, growth metrics, YTD revenue

### Analytics Views

- Analytics dashboard hub
- Revenue analytics
- Attendance analytics
- Operational analytics
- Student analytics
- Room analytics
- Teacher analytics

### Export Support

- PDF export for revenue, attendance, payroll, churn
- CSV export for revenue, attendance, payroll

## 4. Admin Interface Enhancements

- Custom admin site `TonarozAdminSite`
- Analytics routes inside admin UI
- Import/export support for Room, Teacher, CourseGroup, Student, Payment
- Inline admin for enrollments and payments under students
- Inline schedule administration for course groups
- Custom student payment status filters
- Readonly WhatsApp send log admin view

## 5. Operational & Validation Controls

- Room, teacher, and session conflict detection
- Teacher availability and leave enforcement
- Enrollment schedule overlap prevention
- Room capacity warnings
- Session exception monitoring and reset
- Automatic session sync on group or schedule changes
- Attendance analytics and at-risk scoring
- Teacher payroll and load reporting in analytics

## 6. Supporting Utility Components

- `core/utils.py` provides:
  - WhatsApp message template generation
  - Schedule PDF rendering
  - Receipt PDF rendering
  - Student fee calculations
  - Session and schedule generation
  - Conflict annotation logic
- `core/filters.py` provides filters for students, teachers, rooms, sessions, course groups
- `core/forms.py` provides model forms and schedule formsets for core entities

## 7. Summary

`school_erp` is a comprehensive school management ERP covering:
- student enrollment and fee management
- teacher management and payroll mode support
- course scheduling and room planning
- attendance tracking and absence analytics
- WhatsApp messaging automation for reminders, confirmations, and announcements
- admin dashboards, reports, and export capabilities
