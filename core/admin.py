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

from .models import (
    Room, Teacher, CourseGroup, Student, Enrollment, Payment, Attendance, Session,
    CourseGroupSchedule, Level, LevelCategory, WhatsAppSendLog, Holiday,
    TeacherLeave, TeacherAvailability, MakeupSession, Announcement, TeacherPayment,
    SessionChangeHistory, ScheduleLock, StudentLevelHistory
)
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
            path(
                'message-templates/',
                self.admin_view(self._message_templates),
                name='message_templates',
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

    def _message_templates(self, request):
        import os
        import re
        from core.paths import get_messages_dir

        messages_dir = str(get_messages_dir())
        if not os.path.exists(messages_dir):
            os.makedirs(messages_dir, exist_ok=True)

        # Collect all .txt files
        all_files = sorted(
            f for f in os.listdir(messages_dir) if f.endswith('.txt')
        )

        def make_label(name):
            """Turn filename into a readable label."""
            label = name.replace('.txt', '').replace('_', ' ')
            return label.title()

        templates = [
            {'name': f, 'label': make_label(f)}
            for f in all_files
        ]

        current_file = request.GET.get('file') or request.POST.get('filename')
        # Validate: only allow files that actually exist in the messages dir
        if current_file and current_file not in all_files:
            current_file = None

        save_success = False
        save_error = None
        saved_file = None
        content = ''
        detected_vars = []
        current_size = 0

        if request.method == 'POST' and current_file:
            content = request.POST.get('content', '')
            file_path = os.path.join(messages_dir, current_file)
            try:
                with open(file_path, 'w', encoding='utf-8') as fh:
                    fh.write(content)
                save_success = True
                saved_file = current_file
            except OSError as e:
                save_error = str(e)

        if current_file:
            file_path = os.path.join(messages_dir, current_file)
            try:
                with open(file_path, 'r', encoding='utf-8') as fh:
                    content = fh.read()
                current_size = os.path.getsize(file_path)
                detected_vars = sorted(set(re.findall(r'\{(\w+)\}', content)))
            except OSError as e:
                save_error = str(e)

        context = {
            **self.each_context(request),
            'templates': templates,
            'current_file': current_file,
            'content': content,
            'detected_vars': detected_vars,
            'current_size': current_size,
            'save_success': save_success,
            'save_error': save_error,
            'saved_file': saved_file,
        }
        return render(request, 'admin/message_templates.html', context)


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
        fields = ('id', 'name', 'phone', 'parent_contact', 'parent_contact_2', 'parent_name',
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
    list_display = ('name', 'code', 'is_academic', 'level_count')
    list_filter = ('is_academic',)
    search_fields = ('name', 'code')
    ordering = ('name',)
    readonly_fields = ('code',)

    def level_count(self, obj):
        return obj.levels.count()
    level_count.short_description = 'Niveaux'


@admin.register(Level)
class LevelAdmin(ModelAdmin, ImportExportModelAdmin):
    list_display = ('name', 'level_type', 'order', 'category', 'next_level', 'course_group_count', 'student_count')
    list_editable = ('order',)
    list_display_links = ('name',)
    list_filter = ('level_type', 'category')
    search_fields = ('name', 'category__name')
    ordering = ('category__name', 'order', 'name')
    
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
            'fields': ('payment_method', 'payment_percentage', 'hourly_rate', 'session_rate', 'is_active', 'created_at')
        }),
    )
    
    def payment_rate_display(self, obj):
        if obj.payment_method == 'PERCENTAGE':
            return format_html('<strong>{}% (Gains)</strong>', obj.payment_percentage)
        elif obj.payment_method == 'SESSION':
            return format_html('<strong>{} DH/session</strong>', obj.session_rate)
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
    filter_horizontal = ('levels',)
    list_display = ('name', 'subject', 'levels_badge', 'schedules_display', 
                    'teacher', 'price_display', 'student_count', 'status_badge')
    list_filter = ('is_active', 'levels', 'schedules__day', 'teacher', 'schedules__room')
    search_fields = ('name', 'subject', 'levels__name', 'level__name')
    autocomplete_fields = ['teacher']
    inlines = [CourseGroupScheduleInline]
    
    fieldsets = (
        ('Informations générales', {
            'fields': ('name', 'subject', 'levels', 'level', 'monthly_price')
        }),
        ('Assignation', {
            'fields': ('teacher',)
        }),
        ('Statut', {
            'fields': ('is_active',)
        }),
    )

    def levels_badge(self, obj):
        lvls = list(obj.levels.all())
        if lvls:
            badges = "".join(f'<span style="background: #e0e7ff; color: #4338ca; padding: 2px 6px; border-radius: 4px; margin-right: 4px; font-size: 11px; font-weight: 600;">{l.name}</span>' for l in lvls)
            return mark_safe(badges)
        if obj.level:
            return obj.level.name
        return mark_safe('<span style="color: gray;">Sans niveau</span>')
    levels_badge.short_description = 'Niveaux'
    
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


class StudentLevelHistoryInline(TabularInline):
    model = StudentLevelHistory
    extra = 0
    readonly_fields = ('changed_at', 'from_level', 'to_level', 'changed_by', 'reason')
    can_delete = False


@admin.register(StudentLevelHistory)
class StudentLevelHistoryAdmin(ModelAdmin):
    list_display = ('student', 'from_level', 'to_level', 'changed_at', 'changed_by', 'reason')
    list_filter = ('changed_at', 'from_level', 'to_level')
    search_fields = ('student__name', 'reason', 'notes')
    readonly_fields = ('changed_at',)
    ordering = ('-changed_at',)


@admin.register(Student)
class StudentAdmin(ModelAdmin, ImportExportModelAdmin):
    resource_class = StudentResource
    import_form_class = ImportForm
    export_form_class = ExportForm
    list_display = ('name', 'parent_contact', 'groups_display', 'monthly_fees_display', 
                    'payment_status_badge', 'active_badge')
    list_filter = ('is_active', PaymentStatusFilter, 'enrollment__course_group', 'level')
    search_fields = ('name', 'phone', 'parent_contact', 'parent_contact_2', 'parent_name', 'main_school')
    inlines = [EnrollmentInline, PaymentInline, StudentLevelHistoryInline]
    list_select_related = ('level',)

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context=extra_context)
        try:
            cl = response.context_data.get('cl')
            if cl and hasattr(cl, 'result_list') and cl.result_list:
                from core.utils import populate_student_payment_and_fee_info
                populate_student_payment_and_fee_info(cl.result_list)
        except Exception:
            pass
        return response
    
    fieldsets = (
        ('Informations élève', {
            'fields': ('name', 'phone', 'date_of_birth', 'level', 'main_school')
        }),
        ('Contact parent', {
            'fields': ('parent_name', 'parent_contact', 'parent_contact_2', 'address')
        }),
        ('Autres', {
            'fields': ('is_active', 'notes')
        }),
    )
    
    actions = ['generate_payment_reminders']
    
    def groups_display(self, obj):
        groups = getattr(obj, 'computed_active_enrollments', None)
        if groups is None:
            groups = list(obj.enrollment_set.filter(is_active=True).select_related('course_group'))
        if groups:
            group_list = '<br>'.join([f"• {e.course_group.name}" for e in groups[:3]])
            if len(groups) > 3:
                group_list += f'<br>... +{len(groups) - 3} autres'
            return mark_safe(group_list)
        return mark_safe('<span style="color: gray;">Aucun groupe</span>')
    groups_display.short_description = 'Groupes'
    
    def monthly_fees_display(self, obj):
        if hasattr(obj, 'computed_total_monthly_fees'):
            total = obj.computed_total_monthly_fees
        else:
            total = obj.total_monthly_fees()
        return format_html('<strong style="font-size: 14px;">{} DH</strong>', total)
    monthly_fees_display.short_description = 'Frais mensuels'
    
    def payment_status_badge(self, obj):
        if hasattr(obj, 'computed_payment_status'):
            status = (obj.computed_payment_status or '').strip().upper()
        else:
            status = (obj.payment_status() or '').strip().upper()
        if status in ('OK','PAID','UP_TO_DATE','À_JOUR','AJOUR'):
            return mark_safe('<span style="background: #28a745; color: white; padding: 4px 10px; border-radius: 4px; font-weight: bold;">✓ PAYÉ</span>')
        if status in ('PARTIAL','PARTIEL','PARTIALLY_PAID'):
            return mark_safe('<span style="background: #ffc107; color: black; padding: 4px 10px; border-radius: 4px; font-weight: bold;">⚡ PARTIEL</span>')
        if status in ('EXEMPT','EXEMPTÉ','EXEMPTE'):
            return mark_safe('<span style="background: #6c757d; color: white; padding: 4px 10px; border-radius: 4px; font-weight: bold;">— EXEMPTÉ</span>')
        if status in ('NO_ENROLLMENT', 'AUCUN GROUPE'):
            return mark_safe('<span style="background: #6c757d; color: white; padding: 4px 10px; border-radius: 4px;">AUCUN GROUPE</span>')
        return mark_safe('<span style="background: #dc3545; color: white; padding: 4px 10px; border-radius: 4px; font-weight: bold;">✗ IMPAYÉ</span>')
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
    list_select_related = ('student',)
    
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
    list_select_related = ('student', 'course_group')
    
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
    list_select_related = ('group__teacher', 'room')

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
    list_select_related = ('student',)

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


@admin.register(ScheduleLock)
class ScheduleLockAdmin(ModelAdmin):
    list_display = ('status_badge', 'start_date', 'end_date', 'academic_year', 'locked_by', 'locked_at')
    list_filter = ('is_locked', 'academic_year', 'start_date', 'end_date')
    search_fields = ('academic_year', 'notes', 'locked_by__username')
    readonly_fields = ('locked_at',)
    ordering = ('-locked_at',)

    def status_badge(self, obj):
        if obj.is_locked:
            return format_html(
                '<span style="background: #dc3545; color: white; padding: 3px 8px; border-radius: 3px;">Verrouillé</span>'
            )
        return format_html(
            '<span style="background: #28a745; color: white; padding: 3px 8px; border-radius: 3px;">Déverrouillé</span>'
        )
    status_badge.short_description = 'Statut'


@admin.register(SessionChangeHistory)
class SessionChangeHistoryAdmin(ModelAdmin):
    list_display = ('timestamp', 'session_display', 'action', 'user_display', 'change_reason')
    list_filter = ('action', 'timestamp')
    search_fields = ('change_reason', 'action', 'session__group__name', 'session__date')
    readonly_fields = ('timestamp', 'session', 'user', 'action', 'previous_values', 'new_values', 'change_reason', 'ip_address')
    ordering = ('-timestamp',)

    def session_display(self, obj):
        if obj.session:
            return f"{obj.session.date} - {obj.session.group.name if obj.session.group else 'Sans groupe'}"
        return 'Séance supprimée'
    session_display.short_description = 'Séance'

    def user_display(self, obj):
        return obj.user.username if obj.user else '—'
    user_display.short_description = 'Utilisateur'


@admin.register(TeacherPayment)
class TeacherPaymentAdmin(ModelAdmin):
    list_display = ('teacher', 'payment_date', 'period_display', 'amount', 'payment_type', 'payment_method')
    list_filter = ('payment_type', 'payment_method', 'payment_date', 'teacher')
    search_fields = ('teacher__name', 'notes')
    ordering = ('-payment_date', '-id')

    def period_display(self, obj):
        return f"{obj.period_month:02d}/{obj.period_year}"
    period_display.short_description = 'Période'

