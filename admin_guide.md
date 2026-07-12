# School ERP User Guide

This guide is for administrators and managers who use the system every day. It explains how to use the School ERP features without requiring any development knowledge.

---

## 1. Getting Started

### Open the application

- Open your web browser.
- Go to: `http://127.0.0.1:8000/`
- Log in using your admin username and password.

### Main screen

- After login, the dashboard shows key summaries for students, payments, attendance, and schedule.
- Use the sidebar or menu to move to different sections.

---

## 2. Students

### View students

- Go to `Students` from the sidebar.
- You can search by student name, matricule, phone, or parent name.
- The list shows active students and their status.

### Add a student

- Click `Create` or `Add Student`.
- Fill in:
  - Student name
  - Phone number
  - Parent name
  - Parent contact
  - Level and school
  - Notes (optional)
- Save the student.

### Edit a student

- Click on a student from the list.
- Update details, contact information, or notes.
- Use the `Is Active` toggle to disable a student without deleting.

### Enroll a student

- Open a student profile.
- Use the enrollment area to add a student to course groups.
- Select the groups and save.
- The system checks schedule conflicts and warns if there is overlap.

### Remove enrollment

- In the student profile, remove the group from the enrollment list.
- Save changes.

---

## 3. Teachers

### View teachers

- Go to `Teachers`.
- Search by teacher name or email.
- See active status and payment method.

### Add a teacher

- Click `Create` or `Add Teacher`.
- Enter name, phone, email, and payment details.
- Select how they are paid:
  - Hourly rate
  - Percentage of classroom revenue
  - Fixed session rate
- Save the teacher.

### Teacher availability and leaves

- On a teacher profile, add availability slots to show when they can teach.
- Add leaves for vacations or absences.
- The system uses this information when scheduling sessions.

### Edit or deactivate

- Update teacher contact details or payment info.
- Set `Is Active` to false to keep the record but prevent assignment.

---

## 4. Courses and Schedules

### Manage course groups

- Go to `Courses`.
- Each course group includes:
  - subject
  - assigned teacher
  - monthly price
  - class level
  - WhatsApp group link (optional)

### Add or edit a course

- Click `Create` or `Add Course`.
- Fill in the course details and save.

### Define the schedule

- For each course group, add weekly schedule entries.
- Set day, start time, end time, and room.
- The system checks for room and teacher conflicts.

### Review schedule conflicts

- If there is a conflict, correct the date, time, or room.
- Save again after adjustment.

---

## 5. Payments

### Record a payment

- Go to `Cashier` or `Payments`.
- Click `Create Payment`.
- Enter:
  - the student,
  - payment amount,
  - payment method,
  - month covered.
- Save the payment.
- The system creates a receipt automatically.

### Download or print receipt

- After saving a payment, download the receipt PDF.
- Use the receipt for the student or parent.

### Send WhatsApp confirmation

- If the student has parent contact information, you can send a WhatsApp payment confirmation from the payment page.

### Find unpaid students

- Use `Search unpaid students` to view students who still owe money for the current month.
- Send reminders or follow up as needed.

---

## 6. Attendance

### Track attendance

- Go to the `Attendance` or `Sessions` section.
- Open a session to mark student presence.
- Mark present or absent for each student.

### Attendance reports

- Use the attendance report page to see attendance summaries.
- Reports help identify absent students and trends.

---

## 7. WhatsApp Messaging

### WhatsApp dashboard

- Go to `WhatsApp`.
- The dashboard shows messaging features and integration status.

### Payment reminders

- Use `Payment Reminders` to notify parents of unpaid fees.
- The system sends messages to the parent contact on file.

### Absence notifications

- Use `Absence Notifications` to inform parents when students miss class.

### Bulk announcements

- Send messages to many parents or students at once.
- Useful for school news, calendar updates, and events.

### Session reminders

- Send reminders for upcoming sessions.
- Use this for teachers or parents when the class is scheduled soon.

---

## 8. Analytics and Reports

### Revenue and payments

- Go to `Analytics` > `Revenue`.
- Review monthly revenue, payment collection, and top groups.

### Attendance trends

- Open `Analytics` > `Attendance`.
- Monitor attendance patterns and weekly summaries.

### Student metrics

- Use `Analytics` > `Students` to view enrollments, churn, and active count.

### Teacher and room analytics

- Teacher analytics shows payroll, workload, and substitutions.
- Room analytics shows occupancy and usage.

### Export reports

- Export dashboards to PDF or CSV for sharing.
- Use export options in analytics pages.

---

## 9. Public Portals

### Teacher attendance portal

- Teachers can access a special attendance portal without logging into the admin system.
- This portal is for marking attendance quickly.

### Parent kiosk portal

- A kiosk portal is available for parents to look up student attendance and schedule information.
- It is designed for quick access and simple interaction.

---

## 10. Daily Workflow Checklist

- Review the dashboard for overdue payments and absences.
- Add new students and enroll them in course groups.
- Record payments and print/send receipts.
- Confirm teacher availability and update leaves.
- Check course schedules for conflicts and resolve them.
- Use WhatsApp reminders for unpaid fees and absences.
- Export reports for management review.

---

## 11. Helpful Tips

- Use search whenever you need a student, teacher, or course quickly.
- Keep records active rather than deleting them when possible.
- Use the `Is Active` toggle to pause a student, teacher, or course.
- Validate the schedule when you make changes to avoid conflicts.
- Regularly review the WhatsApp dashboard to ensure messages are sending.

---

## 12. Support

If you need help:

- Ask your IT or system support team.
- Provide the student or teacher name and the page where you need assistance.
- For WhatsApp issues, verify the background WhatsApp service is running.
