from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.urls import path
from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils import timezone
from import_export import resources, fields
from import_export.admin import ImportExportModelAdmin
from import_export.widgets import ForeignKeyWidget

from unfold.admin import ModelAdmin, TabularInline
from unfold.contrib.import_export.forms import ExportForm, ImportForm
from unfold.sites import UnfoldAdminSite

from .models import Room, Teacher, CourseGroup, Student, Enrollment, Payment, Attendance, Session, CourseGroupSchedule, Level, LevelCategory, WhatsAppSendLog, Holiday, TeacherLeave, TeacherAvailability, MakeupSession, Announcement
from django.core.exceptions import ValidationError

from django.conf import settings

# ===========================================================================
# CUSTOM ADMIN SITE — must be defined and swapped BEFORE @admin.register()
# ===========================================================================

class TonarozAdminSite(UnfoldAdminSite):
    """Custom AdminSite that injects the analytics dashboard pages into
    the /admin/ URL namespace so they live inside Django Admin's chrome."""

    index_title = "Tableau de Bord"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.site_header = getattr(settings, 'SCHOOL_NAME', "Afnane center")
        self.site_title = f"Admin {getattr(settings, 'SCHOOL_NAME', 'Afnane center')}"

    def get_urls(self):
        analytics_urls = [
            path(
                'analytics/dashboard/',
                self.admin_view(self._analytics_dashboard),
                name='analytics_dashboard',
            ),
            path(
                'analytics/revenue/',
                self.admin_view(self._analytics_revenue),
                name='analytics_revenue',
            ),
            path(
                'analytics/attendance/',
                self.admin_view(self._analytics_attendance),
                name='analytics_attendance',
            ),
            path(
                'analytics/students/',
                self.admin_view(self._analytics_students),
                name='analytics_students',
            ),
            path(
                'analytics/operational/',
                self.admin_view(self._analytics_operational),
                name='analytics_operational',
            ),
            path(
                'analytics/rooms/',
                self.admin_view(self._analytics_rooms),
                name='analytics_rooms',
            ),
            path(
                'analytics/teachers/',
                self.admin_view(self._analytics_teachers),
                name='analytics_teachers',
            ),
        ]
        return analytics_urls + super().get_urls()

    def _analytics_dashboard(self, request):
        from core.analytics import director_dashboard
        context = {**self.each_context(request), **director_dashboard()}
        return render(request, 'admin/analytics_dashboard.html', context)

    def _analytics_revenue(self, request):
        from core.analytics import RevenueAnalytics
        months = int(request.GET.get('months', 3))
        context = {
            **self.each_context(request),
            'monthly_series': RevenueAnalytics.monthly_series(months),
            'ytd': RevenueAnalytics.ytd_summary(),
            'by_group': RevenueAnalytics.revenue_by_course_group(),
            'methods': RevenueAnalytics.payment_method_breakdown(),
            'current_month': RevenueAnalytics.current_month_summary(),
            'months': months,
        }
        return render(request, 'admin/analytics_revenue.html', context)

    def _analytics_attendance(self, request):
        from core.analytics import AttendanceAnalytics
        from datetime import datetime, date
        today = date.today()
        start_str = request.GET.get('start_date', today.replace(day=1).isoformat())
        end_str   = request.GET.get('end_date',   today.isoformat())
        try:
            start = datetime.strptime(start_str, '%Y-%m-%d').date()
        except ValueError:
            start = today.replace(day=1)
        try:
            end = datetime.strptime(end_str, '%Y-%m-%d').date()
        except ValueError:
            end = today
        context = {
            **self.each_context(request),
            'students': AttendanceAnalytics.student_absence_summary(start, end),
            'weekly':   AttendanceAnalytics.weekly_trend(),
            'groups':   AttendanceAnalytics.group_attendance_matrix(start.replace(day=1)),
            'heatmap':  AttendanceAnalytics.daily_absence_heatmap(start.replace(day=1)),
            'start_date': start_str,
            'end_date':   end_str,
        }
        return render(request, 'admin/analytics_attendance.html', context)

    def _analytics_students(self, request):
        from core.analytics import StudentAnalytics
        context = {
            **self.each_context(request),
            'enrollment_trend': StudentAnalytics.enrollment_trend(),
            'churn':            StudentAnalytics.churn_signals(),
            'level_dist':       StudentAnalytics.level_distribution(),
            'enroll_stats':     StudentAnalytics.enrollment_stats(),
            'multi_group':      StudentAnalytics.multi_group_students(),
        }
        return render(request, 'admin/analytics_students.html', context)

    def _analytics_operational(self, request):
        from core.analytics import OperationalAnalytics
        context = {
            **self.each_context(request),
            'completion':    OperationalAnalytics.session_completion_rate(months=6),
            'cancellations': OperationalAnalytics.cancellation_reasons_by_group(),
            'uncompleted':   OperationalAnalytics.uncompleted_sessions(),
            'health':        OperationalAnalytics.scheduling_health(),
        }
        return render(request, 'admin/analytics_operational.html', context)

    def _analytics_rooms(self, request):
        from core.analytics import RoomAnalytics
        context = {
            **self.each_context(request),
            'occupancy':   RoomAnalytics.occupancy_summary(),
            'peak_hours':  RoomAnalytics.peak_hour_matrix(),
            'class_sizes': RoomAnalytics.class_size_distribution(),
            'class_usage': RoomAnalytics.class_usage_list(),
        }
        return render(request, 'admin/analytics_rooms.html', context)

    def _analytics_teachers(self, request):
        from core.analytics import TeacherAnalytics
        from datetime import date
        today = date.today()
        month_start = today.replace(day=1)
        
        start_str = request.GET.get('start_date', month_start.isoformat())
        end_str = request.GET.get('end_date', today.isoformat())
        
        from datetime import datetime
        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
        except ValueError:
            start_date = month_start
        try:
            end_date = datetime.strptime(end_str, '%Y-%m-%d').date()
        except ValueError:
            end_date = today
            
        context = {
            **self.each_context(request),
            'payroll': TeacherAnalytics.payroll_summary(start_date, end_date),
            'load': TeacherAnalytics.weekly_load(),
            'subs': TeacherAnalytics.substitution_rate(),
            'start_date': start_str,
            'end_date': end_str,
        }
        return render(request, 'admin/analytics_teachers.html', context)


# Swap admin.site BEFORE any @admin.register() call
_tonaroz_site = TonarozAdminSite(name='admin')
admin.site = _tonaroz_site
admin.sites.site = _tonaroz_site


# ==================== RESOURCES (Import/Export) ====================

class RoomResource(resources.ModelResource):
    class Meta:
        model = Room
        fields = ('id', 'name', 'capacity', 'is_active')
        export_order = fields


class TeacherResource(resources.ModelResource):
    class Meta:
        model = Teacher
        fields = ('id', 'name', 'phone', 'email', 'hourly_rate', 'payment_method', 'payment_percentage', 'is_active')


class CourseGroupResource(resources.ModelResource):
    teacher = fields.Field(
        column_name='teacher',
        attribute='teacher',
        widget=ForeignKeyWidget(Teacher, 'name')
    )
    
    class Meta:
        model = CourseGroup
        fields = ('id', 'name', 'subject', 'level', 'monthly_price', 'teacher')


class StudentResource(resources.ModelResource):
    total_fees = fields.Field()
    payment_status = fields.Field()
    
    class Meta:
        model = Student
        fields = ('id', 'name', 'phone', 'parent_contact', 'parent_name', 
                  'address', 'is_active', 'total_fees', 'payment_status', 'main_school')
    
    def dehydrate_total_fees(self, student):
        return str(student.total_monthly_fees())
    
    def dehydrate_payment_status(self, student):
        return student.payment_status()


class PaymentResource(resources.ModelResource):
    student = fields.Field(
        column_name='student',
        attribute='student',
        widget=ForeignKeyWidget(Student, 'name')
    )
    
    class Meta:
        model = Payment
        fields = ('id', 'receipt_number', 'student', 'amount', 'payment_date',
                  'month_covered', 'status', 'payment_method', 'notes')


# ==================== INLINE ADMINS ====================

class EnrollmentInline(TabularInline):
    model = Enrollment
    extra = 1
    fields = ('course_group', 'enrolled_date', 'is_active')
    readonly_fields = ('enrolled_date',)
    autocomplete_fields = ['course_group']


class PaymentInline(TabularInline):
    model = Payment
    extra = 0
    fields = ('receipt_number', 'amount', 'payment_date', 'month_covered', 'status', 'payment_method')
    readonly_fields = ('receipt_number',)
    can_delete = False
    
    def has_add_permission(self, request, obj=None):
        return False


# ==================== CUSTOM FILTERS ====================

class PaymentStatusFilter(admin.SimpleListFilter):
    title = 'Statut de paiement'
    parameter_name = 'payment_status'
    
    def lookups(self, request, model_admin):
        return (
            ('ok', '✅ À jour'),
            ('partial', '🟠 Partiel'),
            ('unpaid', '🔴 Impayé'),
        )
    
    def queryset(self, request, queryset):
        if self.value():
            def normalize(s):
                return (s or '').strip().upper()
            wanted = self.value()
            filtered_ids = []
            for student in queryset:
                status = normalize(student.payment_status())
                if wanted == 'ok' and status in ('OK','PAID','UP_TO_DATE','À_JOUR','AJOUR'):
                    filtered_ids.append(student.id)
                elif wanted == 'partial' and status in ('PARTIAL','PARTIEL','PARTIALLY_PAID'):
                    filtered_ids.append(student.id)
                elif wanted == 'unpaid' and status in ('UNPAID','IMPAID','OVERDUE','DUE',''):
                    filtered_ids.append(student.id)
            return queryset.filter(id__in=filtered_ids)
        return queryset


class CurrentMonthPaymentFilter(admin.SimpleListFilter):
    title = 'Paiement du mois'
    parameter_name = 'current_month'
    
    def lookups(self, request, model_admin):
        return (
            ('yes', 'Payé ce mois'),
            ('no', 'Non payé ce mois'),
        )
    
    def queryset(self, request, queryset):
        current_month = timezone.now().date().replace(day=1)
        if self.value() == 'yes':
            return queryset.filter(month_covered=current_month, status='PAID')
        elif self.value() == 'no':
            paid_students = Payment.objects.filter(
                month_covered=current_month,
                status='PAID'
            ).values_list('student_id', flat=True)
            return queryset.exclude(student_id__in=paid_students)
        return queryset


# ==================== MAIN ADMIN CLASSES ====================

@admin.register(Room)
class RoomAdmin(ModelAdmin, ImportExportModelAdmin):
    resource_class = RoomResource
    import_form_class = ImportForm
    export_form_class = ExportForm
    list_display = ('name', 'capacity', 'active_status', 'course_count')
    list_filter = ('is_active',)
    search_fields = ('name',)
    
    def active_status(self, obj):
        if obj.is_active:
            return mark_safe('<span style="color: green;">✓ Active</span>')
        return mark_safe('<span style="color: red;">✗ Inactive</span>')
    active_status.short_description = 'Statut'
    
    def course_count(self, obj):
        count = CourseGroup.objects.filter(schedules__room=obj, is_active=True).distinct().count()
        return format_html('<strong>{}</strong> cours', count)
    course_count.short_description = 'Cours actifs'


@admin.register(LevelCategory)
class LevelCategoryAdmin(ModelAdmin):
    list_display = ('name', 'code', 'level_count')
    search_fields = ('name', 'code')
    ordering = ('name',)
    readonly_fields = ('code',)

    def level_count(self, obj):
        return obj.levels.count()
    level_count.short_description = 'Niveaux'


@admin.register(Level)
class LevelAdmin(ModelAdmin, ImportExportModelAdmin):
    list_display = ('name', 'category', 'course_group_count', 'student_count')
    search_fields = ('name',)
    ordering = ('category__name', 'name')
    
    def course_group_count(self, obj):
        return obj.course_groups.count()
    course_group_count.short_description = 'Groupes de cours'
    
    def student_count(self, obj):
        return obj.students.count()
    student_count.short_description = 'Élèves'


@admin.register(Teacher)
class TeacherAdmin(ModelAdmin, ImportExportModelAdmin):
    resource_class = TeacherResource
    import_form_class = ImportForm
    export_form_class = ExportForm
    list_display = ('name', 'phone', 'payment_rate_display', 'course_count', 'active_status')
    list_filter = ('is_active', 'payment_method')
    search_fields = ('name', 'phone', 'email')
    readonly_fields = ('created_at',)
    
    class Media:
        js = ('admin/js/teacher_admin.js',)
        
    fieldsets = (
        ('Informations personnelles', {
            'fields': ('name', 'phone', 'email')
        }),
        ('Informations professionnelles', {
            'fields': ('payment_method', 'payment_percentage', 'hourly_rate', 'is_active', 'created_at')
        }),
    )
    
    def payment_rate_display(self, obj):
        if obj.payment_method == 'PERCENTAGE':
            return format_html('<strong>{}% (Gains)</strong>', obj.payment_percentage)
        return format_html('<strong>{} DH/h</strong>', obj.hourly_rate)
    payment_rate_display.short_description = 'Tarif / Mode'
    
    def course_count(self, obj):
        count = obj.course_groups.filter(is_active=True).count()
        if count > 0:
            return format_html('<span style="color: green;">{} groupes</span>', count)
        return mark_safe('<span style="color: gray;">0 groupe</span>')
    course_count.short_description = 'Groupes'
    
    def active_status(self, obj):
        if obj.is_active:
            return mark_safe('<span style="color: green;">✓</span>')
        return mark_safe('<span style="color: red;">✗</span>')
    active_status.short_description = 'Actif'


class CourseGroupScheduleInline(TabularInline):
    model = CourseGroupSchedule
    extra = 1
    autocomplete_fields = ['room']


@admin.register(CourseGroup)
class CourseGroupAdmin(ModelAdmin, ImportExportModelAdmin):
    resource_class = CourseGroupResource
    import_form_class = ImportForm
    export_form_class = ExportForm
    list_display = ('name', 'subject', 'level', 'schedules_display', 
                    'teacher', 'price_display', 'student_count', 'status_badge')
    list_filter = ('is_active', 'schedules__day', 'teacher', 'schedules__room', 'level')
    search_fields = ('name', 'subject', 'level')
    autocomplete_fields = ['teacher']
    inlines = [CourseGroupScheduleInline]
    
    fieldsets = (
        ('Informations générales', {
            'fields': ('name', 'subject', 'level', 'monthly_price')
        }),
        ('Assignation', {
            'fields': ('teacher',)
        }),
        ('Statut', {
            'fields': ('is_active',)
        }),
    )
    
    def schedules_display(self, obj):
        schedules = obj.schedules.all()
        if not schedules.exists():
            return mark_safe('<span style="color: gray;">Aucun horaire</span>')
        html_lines = []
        for sch in schedules:
            html_lines.append(f"<strong>{sch.get_day_display()}</strong>: {sch.start_time.strftime('%H:%M')}-{sch.end_time.strftime('%H:%M')} ({sch.room.name})")
        return mark_safe('<br>'.join(html_lines))
    schedules_display.short_description = 'Horaires'
    
    def price_display(self, obj):
        return format_html('<strong>{} DH</strong>/mois', obj.monthly_price)
    price_display.short_description = 'Prix'
    
    def student_count(self, obj):
        count = obj.students.filter(is_active=True).count()
        schedules = obj.schedules.all()
        if schedules.exists():
            min_capacity = min(sch.room.capacity for sch in schedules)
            if count >= (min_capacity * 0.8):
                color = 'red'
            elif count >= (min_capacity * 0.5):
                color = 'orange'
            else:
                color = 'green'
            return format_html(
                '<span style="color: {};">{} (cap. min: {})</span>',
                color, count, min_capacity
            )
        return format_html('<strong>{}</strong>', count)
    student_count.short_description = 'Élèves'
    
    def status_badge(self, obj):
        if obj.is_active:
            return mark_safe('<span style="background: green; color: white; padding: 3px 8px; border-radius: 3px;">Actif</span>')
        return mark_safe('<span style="background: gray; color: white; padding: 3px 8px; border-radius: 3px;">Inactif</span>')
    status_badge.short_description = 'Statut'


@admin.register(Student)
class StudentAdmin(ModelAdmin, ImportExportModelAdmin):
    resource_class = StudentResource
    import_form_class = ImportForm
    export_form_class = ExportForm
    list_display = ('name', 'parent_contact', 'groups_display', 'monthly_fees_display', 
                    'payment_status_badge', 'active_badge')
    list_filter = ('is_active', PaymentStatusFilter, 'enrollment__course_group', 'level')
    search_fields = ('name', 'phone', 'parent_contact', 'parent_name', 'main_school')
    inlines = [EnrollmentInline, PaymentInline]
    
    fieldsets = (
        ('Informations élève', {
            'fields': ('name', 'phone', 'date_of_birth', 'level', 'main_school')
        }),
        ('Contact parent', {
            'fields': ('parent_name', 'parent_contact', 'address')
        }),
        ('Autres', {
            'fields': ('is_active', 'notes')
        }),
    )
    
    actions = ['generate_payment_reminders']
    
    def groups_display(self, obj):
        groups = obj.enrollment_set.filter(is_active=True)
        if groups.exists():
            group_list = '<br>'.join([f"• {e.course_group.name}" for e in groups[:3]])
            if groups.count() > 3:
                group_list += f'<br>... +{groups.count() - 3} autres'
            return mark_safe(group_list)
        return mark_safe('<span style="color: gray;">Aucun groupe</span>')
    groups_display.short_description = 'Groupes'
    
    def monthly_fees_display(self, obj):
        total = obj.total_monthly_fees()
        return format_html('<strong style="font-size: 14px;">{} DH</strong>', total)
    monthly_fees_display.short_description = 'Frais mensuels'
    
    def payment_status_badge(self, obj):
        status = (obj.payment_status() or '').strip().upper()
        if status in ('OK','PAID','UP_TO_DATE','À_JOUR','AJOUR'):
            return mark_safe('<span style="background: #28a745; color: white; padding: 4px 10px; border-radius: 4px; font-weight: bold;">✓ PAYÉ</span>')
        if status in ('PARTIAL','PARTIEL','PARTIALLY_PAID'):
            return mark_safe('<span style="background: #ff9800; color: white; padding: 4px 10px; border-radius: 4px; font-weight: bold;">⚠ PARTIEL</span>')
        if status in ('UNPAID','IMPAID','OVERDUE','DUE',''):
            return mark_safe('<span style="background: #dc3545; color: white; padding: 4px 10px; border-radius: 4px; font-weight: bold;">✗ IMPAYÉ</span>')
        # fallback: show raw normalized status
        return format_html('<span style="background: gray; color: white; padding: 4px 10px; border-radius: 4px; font-weight: bold;">{}</span>', status)
    payment_status_badge.short_description = 'Statut'

    
    def active_badge(self, obj):
        if obj.is_active:
            return mark_safe('<span style="color: green; font-size: 18px;">✓</span>')
        return mark_safe('<span style="color: red; font-size: 18px;">✗</span>')
    active_badge.short_description = 'Actif'
    
    def generate_payment_reminders(self, request, queryset):
        """Action pour générer des rappels de paiement"""
        unpaid = []
        for student in queryset:
            if student.payment_status() in ['UNPAID', 'PARTIAL']:
                unpaid.append(student.name)
        
        if unpaid:
            messages.warning(
                request,
                f"📱 {len(unpaid)} élèves à relancer : {', '.join(unpaid[:5])}" +
                (f"... et {len(unpaid) - 5} autres" if len(unpaid) > 5 else "")
            )
        else:
            messages.success(request, "✅ Tous les élèves sélectionnés sont à jour !")
    
    generate_payment_reminders.short_description = "📱 Générer rappels de paiement"


@admin.register(Payment)
class PaymentAdmin(ModelAdmin, ImportExportModelAdmin):
    resource_class = PaymentResource
    import_form_class = ImportForm
    export_form_class = ExportForm
    list_display = ('receipt_number', 'student', 'amount_display', 'payment_date', 
                    'month_covered', 'status_badge', 'payment_method', 'locked_status')
    list_filter = ('status', 'payment_method', CurrentMonthPaymentFilter, 'is_locked', 'payment_date')
    search_fields = ('receipt_number', 'student__name', 'notes')
    autocomplete_fields = ['student']
    date_hierarchy = 'payment_date'
    
    fieldsets = (
        ('Paiement', {
            'fields': ('student', 'amount', 'payment_date', 'month_covered')
        }),
        ('Détails', {
            'fields': ('status', 'payment_method', 'notes')
        }),
        ('Système', {
            'fields': ('receipt_number', 'is_locked', 'created_by', 'created_at'),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ('receipt_number', 'created_at')
    
    def amount_display(self, obj):
        return format_html('<strong style="font-size: 15px; color: #28a745;">{} DH</strong>', obj.amount)
    amount_display.short_description = 'Montant'
    
    def status_badge(self, obj):
        colors = {
            'PAID': '#28a745',
            'PENDING': '#ffc107',
            'CANCELLED': '#dc3545'
        }
        return format_html(
            '<span style="background: {}; color: white; padding: 3px 10px; border-radius: 3px;">{}</span>',
            colors.get(obj.status, 'gray'),
            obj.get_status_display()
        )
    status_badge.short_description = 'Statut'
    
    def locked_status(self, obj):
        if obj.is_locked:
            return mark_safe('<span style="color: red; font-size: 16px;">🔒 Verrouillé</span>')
        return mark_safe('<span style="color: green;">🔓 Modifiable</span>')


@admin.register(Attendance)
class AttendanceAdmin(ModelAdmin):
    list_display = ('date', 'student', 'course_group', 'presence_badge', 'notes_preview')
    list_filter = ('is_present', 'date', 'course_group')
    search_fields = ('student__name', 'course_group__name')
    autocomplete_fields = ['student', 'course_group']
    date_hierarchy = 'date'
    
    def presence_badge(self, obj):
        if obj.is_present:
            return mark_safe('<span style="color: green; font-size: 18px; font-weight: bold;">✓ Présent</span>')
        return mark_safe('<span style="color: red; font-size: 18px; font-weight: bold;">✗ Absent</span>')
    presence_badge.short_description = 'Présence'
    
    def notes_preview(self, obj):
        if obj.notes:
            return obj.notes[:50] + ('...' if len(obj.notes) > 50 else '')
        return '-'
    notes_preview.short_description = 'Notes'


@admin.register(Session)
class SessionAdmin(ModelAdmin):
    list_display = ('date', 'group', 'room', 'get_teacher', 'start_time', 'end_time', 'status')
    list_filter = ('status', 'date', 'room', 'group__teacher')
    search_fields = ('group__name', 'group__teacher__name', 'room__name')
    autocomplete_fields = ['group']

    def get_teacher(self, obj):
        return obj.group.teacher.name if obj.group and obj.group.teacher else '-'
    get_teacher.short_description = 'Professeur'

    def save_model(self, request, obj, form, change):
        try:
            obj.is_manually_edited = True
            obj.full_clean()
            super().save_model(request, obj, form, change)
            messages.success(request, f"✅ Session pour {obj.group.name} enregistrée ({obj.date})")
        except ValidationError as e:
            messages.error(request, f"⚠️ Impossible d'enregistrer la session: {e.messages[0] if hasattr(e, 'messages') else e}")
            return


# ==================== WHATSAPP SEND LOG ====================


@admin.register(WhatsAppSendLog)
class WhatsAppSendLogAdmin(ModelAdmin):
    list_display = ('sent_at', 'get_student_name', 'phone', 'message_type', 'status')
    list_filter = ('status', 'message_type', 'sent_at')
    search_fields = ('phone', 'student__name', 'message_preview')
    readonly_fields = ('student', 'phone', 'message_type', 'message_preview', 'status', 'error_message', 'sent_at')
    ordering = ('-sent_at',)
    list_per_page = 50

    def get_student_name(self, obj):
        if obj.student:
            return obj.student.name
        return obj.phone
    get_student_name.short_description = 'Élève / Téléphone'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


# ==================== ADDITIONAL REGISTRATIONS ====================

@admin.register(Holiday)
class HolidayAdmin(ModelAdmin):
    list_display = ('name', 'date', 'affects_all')
    list_filter = ('affects_all', 'date')
    search_fields = ('name', 'notes')
    filter_horizontal = ('affected_groups',)


@admin.register(TeacherLeave)
class TeacherLeaveAdmin(ModelAdmin):
    list_display = ('teacher', 'start_date', 'end_date', 'leave_type')
    list_filter = ('leave_type', 'start_date', 'end_date')
    search_fields = ('teacher__name', 'notes')


@admin.register(TeacherAvailability)
class TeacherAvailabilityAdmin(ModelAdmin):
    list_display = ('teacher', 'day', 'start_time', 'end_time', 'is_available')
    list_filter = ('day', 'is_available')
    search_fields = ('teacher__name',)


@admin.register(MakeupSession)
class MakeupSessionAdmin(ModelAdmin):
    list_display = ('id', 'original_session', 'makeup_session')
    search_fields = ('original_session__group__name', 'notes')
    filter_horizontal = ('students',)


@admin.register(Announcement)
class AnnouncementAdmin(ModelAdmin):
    list_display = ('title', 'category', 'event_date', 'is_active', 'created_at')
    list_filter = ('category', 'is_active', 'created_at', 'event_date')
    search_fields = ('title', 'content')
    filter_horizontal = ('target_levels', 'target_groups')

