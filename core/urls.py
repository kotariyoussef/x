from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.cockpit, name='cockpit'),
    
    # Student CRUD
    path('students/', views.students_list, name='students_list'),
    path('students/print/', views.print_students_list, name='print_students_list'),
    path('students/create/', views.student_create, name='student_create'),
    path('students/<int:student_id>/', views.student_page, name='student_page'),
    path('students/<int:student_id>/edit/', views.student_edit, name='student_edit'),
    path('students/<int:student_id>/delete/', views.student_delete, name='student_delete'),
    path('students/<int:student_id>/delete-confirm/', views.student_delete_confirm, name='student_delete_confirm'),
    
    # Enrollment management
    path('students/<int:student_id>/enrollment/add/', views.enrollment_add, name='enrollment_add'),
    path('enrollment/<int:enrollment_id>/remove/', views.enrollment_remove, name='enrollment_remove'),
    
    # Courses
    path('courses/', views.courses_list, name='courses_list'),
    path('courses/create/', views.course_group_create, name='course_group_create'),
    path('courses/<int:group_id>/', views.group_detail, name='group_detail'),
    path('courses/<int:group_id>/edit/', views.course_group_edit, name='course_group_edit'),
    path('courses/<int:group_id>/delete-confirm/', views.course_group_delete_confirm, name='course_group_delete_confirm'),

    
    # Levels
    path('levels/', views.levels_list, name='levels_list'),
    path('levels/<int:level_id>/', views.level_detail, name='level_detail'),
    path('levels/create/', views.level_create, name='level_create'),
    path('levels/<int:level_id>/edit/', views.level_edit, name='level_edit'),
    path('levels/<int:level_id>/delete/', views.level_delete, name='level_delete'),
    path('levels/<int:level_id>/delete-confirm/', views.level_delete_confirm, name='level_delete_confirm'),
    
    path('teachers/', views.teachers_list, name='teachers_list'),
     path('teachers/search/', views.teacher_search, name='teacher_search'),
    path('teachers/print/', views.print_teachers_list, name='print_teachers_list'),
    path('rooms/', views.rooms_list, name='rooms_list'),
    
    # Sessions
    path('schedule/', views.sessions_schedule, name='sessions_schedule'),
    path('schedule/monthly/', views.sessions_monthly, name='sessions_monthly'),
    path('schedule/makeup/create/', views.create_makeup_session, name='create_makeup_session'),
    path('attendance/report/', views.attendance_report, name='attendance_report'),
    path('schedule/print/admin/', views.print_admin_schedule, name='print_admin_schedule'),
     path('schedule/print/teacher/<int:teacher_id>/', views.print_teacher_schedule, name='print_teacher_schedule'),
     path('schedule/print/student/<int:student_id>/', views.print_student_schedule, name='print_student_schedule'),
    path('schedule/conflicts/', views.schedule_conflicts, name='schedule_conflicts'),
    path('schedule/check-conflict/', views.check_conflict_ajax, name='check_conflict_ajax'),
    path('sessions/today/', views.sessions_today, name='sessions_today'),
    path('sessions/<int:session_id>/attendance/', views.session_attendance, name='session_attendance'),
    path('sessions/create/', views.session_create, name='session_create'),
    path('sessions/<int:session_id>/edit/', views.session_edit, name='session_edit'),
    path('sessions/<int:session_id>/delete/', views.session_delete, name='session_delete'),
    path('sessions/generate/', views.session_generate_bulk, name='session_generate_bulk'),
    path('sessions/<int:session_id>/quick-update/', views.session_quick_status_update, name='session_quick_status_update'),
    path('sessions/<int:session_id>/detail-ajax/', views.session_detail_ajax, name='session_detail_ajax'),
    path('sessions/create-ajax/', views.session_create_ajax, name='session_create_ajax'),
    path('sessions/<int:session_id>/update-ajax/', views.session_update_ajax, name='session_update_ajax'),
    path('sessions/<int:session_id>/reset-ajax/', views.session_reset_to_default_ajax, name='session_reset_to_default_ajax'),
    path('sessions/exceptions/', views.session_exceptions_list, name='session_exceptions_list'),
    
    # Cashier
    path('cashier/payment/create/', views.payment_create, name='payment_create'),
    path('cashier/payment/<int:payment_id>/receipt/', views.receipt_download, name='receipt_download'),
    path('cashier/student-search/', views.student_search, name='student_search'),
    path('cashier/student-unpaid-search/', views.student_unpaid_search, name='student_unpaid_search'),
    path('cashier/student-detail/', views.student_detail, name='student_detail'),
    
    # Payroll
    path('payroll/teacher/', views.teacher_payroll, name='teacher_payroll'),

    # WhatsApp Integration
    path('whatsapp/', views.whatsapp_dashboard, name='whatsapp_dashboard'),
    
    # WhatsApp Payment Reminders
    path('whatsapp/payment-reminders/', 
         views.whatsapp_payment_reminders, 
         name='whatsapp_payment_reminders'),
    
    # WhatsApp Absence Notifications
    path('whatsapp/absence-notifications/', 
         views.whatsapp_absence_notifications, 
         name='whatsapp_absence_notifications'),
    
    # WhatsApp Bulk Announcements
    path('whatsapp/bulk-announcements/', 
         views.whatsapp_bulk_announcements, 
         name='whatsapp_bulk_announcements'),
    
    # WhatsApp Payment Confirmation
    path('whatsapp/payment-confirmation/<int:payment_id>/', 
         views.whatsapp_payment_confirmation, 
         name='whatsapp_payment_confirmation'),
    
    # WhatsApp Session Reminder
    path('whatsapp/session-reminder/<int:session_id>/', 
         views.whatsapp_session_reminder, 
         name='whatsapp_session_reminder'),
    
    # WhatsApp AJAX Link Generator
    path('whatsapp/generate-link/', 
         views.whatsapp_generate_link_ajax, 
         name='whatsapp_generate_link_ajax'),
    
    # WhatsApp AJAX Automations (Background Sending & Session Control)
    path('whatsapp/send/', 
         views.whatsapp_send_ajax, 
         name='whatsapp_send_ajax'),
    path('whatsapp/logout/', 
         views.whatsapp_logout_ajax, 
         name='whatsapp_logout_ajax'),
    path('whatsapp/restart/',
         views.whatsapp_restart_ajax,
         name='whatsapp_restart_ajax'),
    
    # Dashboard admin API
    path('admin-api/kpis/', views.admin_kpis_api, name='admin_kpis_api'),

    # Admin Statistics page
    path('admin-statistics/', views.admin_statistics, name='admin_statistics'),

    # Attendance Analytics / At-Risk Dashboard
    path('analytics/attendance/', views.attendance_analytics, name='attendance_analytics'),

    # New Analytics & Reporting Dashboard views
    path('analytics/dashboard/', views.analytics_dashboard, name='analytics_dashboard'),
    path('analytics/revenue/', views.analytics_revenue, name='analytics_revenue'),
    path('analytics/attendance-report/', views.analytics_attendance, name='analytics_attendance'),
    path('analytics/operational/', views.analytics_operational, name='analytics_operational'),
    path('analytics/students/', views.analytics_students, name='analytics_students'),
    path('analytics/rooms/', views.analytics_rooms, name='analytics_rooms'),
    path('analytics/teachers/', views.analytics_teachers, name='analytics_teachers'),

    # PDF/CSV Dynamic Export URLs
    path('analytics/export/revenue/pdf/', views.export_revenue_pdf, name='export_revenue_pdf'),
    path('analytics/export/attendance/pdf/', views.export_attendance_pdf, name='export_attendance_pdf'),
    path('analytics/export/payroll/pdf/', views.export_payroll_pdf, name='export_payroll_pdf'),
    path('analytics/export/churn/pdf/', views.export_churn_pdf, name='export_churn_pdf'),
    path('analytics/export/csv/', views.export_csv_view, name='export_csv_view'),

]


