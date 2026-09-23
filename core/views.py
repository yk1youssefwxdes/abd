from io import BytesIO
from core.utils import format_date_fr
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse, HttpResponseBadRequest
from django.views.decorators.http import require_GET
from django.utils import timezone
from datetime import datetime
from django.db.models import Q, Count, Sum
from decimal import Decimal
from datetime import timedelta, date

from .models import Student, Payment, Enrollment, Room, Teacher, WhatsAppSendLog, Level, LevelCategory
from .utils import WhatsAppMessageTemplates, WhatsAppUtils, WhatsAppServiceAPI, _build_room_schedule, _build_teacher_schedule, _calculate_week_stats, get_dashboard_stats, generate_receipt_pdf, calculate_student_monthly_total, generate_sessions_from_coursegroups, _annotate_conflicts, load_message_template, SafeDict
from .forms import SessionForm, StudentForm, EnrollmentForm
from django.core.paginator import Paginator
from .models import CourseGroup, Session, Attendance
from django.views.decorators.http import require_http_methods
from django.db import transaction
from decimal import Decimal as D
from collections import defaultdict
from .filters import StudentFilter, CourseGroupFilter, TeacherFilter, RoomFilter, SessionFilter
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.conf import settings
import base64
import json
import mimetypes
import os
import uuid


def payment_create(request):
    """
    Enhanced cashier view with WhatsApp confirmation option
    """
    if request.method == 'GET':
        from dateutil.relativedelta import relativedelta
        # Generate last 3 months, current month, and next 2 months
        today = timezone.now().date()
        months_choices = []
        for i in range(-3, 3):
            m = today + relativedelta(months=i)
            first_day = m.replace(day=1)
            months_choices.append({
                'value': first_day.strftime('%Y-%m-%d'),
                'label': first_day.strftime('%B %Y')
            })
        
        # Let's format labels in French
        from .utils import month_name_fr
        for m in months_choices:
            dt_obj = datetime.strptime(m['value'], '%Y-%m-%d').date()
            m['label'] = f"{month_name_fr(dt_obj.month)} {dt_obj.year}"
            
        current_month_str = today.replace(day=1).strftime('%Y-%m-%d')
        
        return render(request, 'core/payment_create.html', {
            'default_student_id': request.GET.get('student_id'),
            'months_choices': months_choices,
            'current_month_str': current_month_str,
        })

    # POST -> create payment

    if request.method == 'POST':
        student_id = request.POST.get('student_id')
        amount = request.POST.get('amount')
        payment_method = request.POST.get('payment_method', 'CASH')
        month_covered = request.POST.get('month_covered')
        send_whatsapp = request.POST.get('send_whatsapp') == 'on'

        if not student_id or not amount:
            return HttpResponseBadRequest('Missing student or amount')

        student = get_object_or_404(Student, pk=student_id)

        try:
            amount_dec = Decimal(amount)
        except Exception:
            return HttpResponseBadRequest('Montant invalide')

        # default month_covered to first day of current month
        if not month_covered:
            now = timezone.now().date()
            month_covered = now.replace(day=1)
        else:
            try:
                month_covered = datetime.strptime(month_covered, '%Y-%m-%d').date()
            except Exception:
                month_covered = timezone.now().date().replace(day=1)

        payment = Payment.objects.create(
            student=student,
            amount=amount_dec,
            payment_date=timezone.now().date(),
            month_covered=month_covered,
            status='PAID',
            payment_method=payment_method,
            created_by=request.user.get_username() if hasattr(request, 'user') and request.user.is_authenticated else ''
        )

        # Update next_payment_date for active enrollments
        from .utils import get_next_month
        next_pay_date = get_next_month(payment.month_covered)
        for enrollment in student.enrollment_set.filter(is_active=True):
            enrollment.next_payment_date = next_pay_date
            enrollment.save()

        # Generate receipt PDF
        pdf_buffer = generate_receipt_pdf(payment)
        
        # If WhatsApp confirmation requested, redirect to WhatsApp confirmation page
        if send_whatsapp and (student.parent_contact or student.parent_contact_2):
            # Save receipt temporarily (or provide download link)
            response = HttpResponse(pdf_buffer.read(), content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="receipt_{payment.receipt_number}.pdf"'
            
            # Store payment ID in session for WhatsApp confirmation redirect
            request.session['last_payment_id'] = payment.id
            
            messages.success(request, 'Paiement enregistré avec succès!')
            return redirect('core:whatsapp_payment_confirmation', payment_id=payment.id)

        response = HttpResponse(pdf_buffer.read(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="receipt_{payment.receipt_number}.pdf"'
        return response


def receipt_download(request, payment_id):
    """
    Download PDF receipt for a given payment ID
    """
    payment = get_object_or_404(Payment, pk=payment_id)
    pdf_buffer = generate_receipt_pdf(payment)
    response = HttpResponse(pdf_buffer.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="receipt_{payment.receipt_number}.pdf"'
    return response


@require_GET
def student_search(request):
    """AJAX endpoint for Select2 student search. Query param `q`."""
    q = request.GET.get('q', '').strip()
    results = []
    if q:
        students = Student.objects.filter(Q(name__icontains=q) | Q(matricule__icontains=q))[:20]
    else:
        students = Student.objects.all()[:20]

    for s in students:
        results.append({
            'id': s.id,
            'text': f"[{s.matricule or 'N/A'}] {s.name} ({s.parent_name or s.parent_contact})"
        })

    return JsonResponse({'results': results})


@require_GET
def teacher_search(request):
    """AJAX endpoint for Select2/quick teacher search. Query param `q`."""
    q = request.GET.get('q', '').strip()
    results = []
    if q:
        teachers = Teacher.objects.filter(name__icontains=q)[:50]
    else:
        teachers = Teacher.objects.filter(is_active=True)[:50]

    for t in teachers:
        results.append({
            'id': t.id,
            'text': f"{t.name} ({t.email or t.id})"
        })

    return JsonResponse({'results': results})


@require_GET
def student_unpaid_search(request):
    """AJAX endpoint for Select2 student search filtered to unpaid students. Query param `q`."""
    from django.utils import timezone
    
    q = request.GET.get('q', '').strip()
    
    # Get current month

    month_str = request.GET.get("month")

    if month_str:
        try:
            current_month = datetime.strptime(month_str, "%Y-%m-%d").date()
        except ValueError:
            current_month = timezone.now().date().replace(day=1)
    else:
        current_month = timezone.now().date().replace(day=1)
    
    # Get all students or filter by name/matricule
    if q:
        students = Student.objects.filter(
            Q(name__icontains=q) | Q(matricule__icontains=q),
            is_active=True
        )[:50]
    else:
        students = Student.objects.filter(is_active=True)[:50]
    
    # Filter to unpaid students only
    unpaid_students = []
    for s in students:
        required = calculate_student_monthly_total(s)
        paid = Payment.objects.filter(
            student=s,
            month_covered=current_month,
            status='PAID'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        
        if paid < required:  # Student has unpaid amount
            unpaid_students.append({
                'id': s.id,
                'text': f"[{s.matricule or 'N/A'}] {s.name} ({s.parent_name or s.parent_contact}) - Due: {required - paid} DH",
                'due_amount': str(required - paid)
            })
    
    return JsonResponse({'results': unpaid_students})


@require_GET
def student_detail(request):
    """Return student details including calculated amount due and enrollments."""
    student_id = request.GET.get('id')
    if not student_id:
        return HttpResponseBadRequest('Missing id')

    student = get_object_or_404(Student, pk=student_id)

    # Get month parameter from request, default to current month
    month_param = request.GET.get('month')
    if month_param:
        try:
            current_month = datetime.strptime(month_param, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            current_month = timezone.now().date().replace(day=1)
    else:
        current_month = timezone.now().date().replace(day=1)
    
    from .utils import calculate_student_expected_fees_for_month, count_scheduled_sessions_in_month, count_remaining_sessions_in_month
    
    required = calculate_student_expected_fees_for_month(student, current_month)
    enrollments = student.enrollment_set.filter(is_active=True).select_related('course_group')
    groups = []
    
    paid = Payment.objects.filter(
        student=student,
        month_covered=current_month,
        status='PAID'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    
    required = max(required - paid, Decimal('0'))
    
    for e in enrollments:
        is_prorated = False
        total_sess = 0
        rem_sess = 0
        sess_price = Decimal('0.00')
        prorated_price = e.course_group.monthly_price
        
        if e.enrolled_date.year == current_month.year and e.enrolled_date.month == current_month.month:
            if e.enrolled_date.day > 1:
                is_prorated = True
                total_sess = count_scheduled_sessions_in_month(e.course_group, current_month.year, current_month.month)
                rem_sess = count_remaining_sessions_in_month(e.course_group, e.enrolled_date)
                if total_sess > 0:
                    sess_price = (e.course_group.monthly_price / Decimal(total_sess)).quantize(Decimal('0.01'))
                    prorated_price = (Decimal(rem_sess) * sess_price).quantize(Decimal('0.01'))
                    import math
                    prorated_price = Decimal(str(math.ceil(prorated_price / Decimal('10')))) * Decimal('10')
        
        groups.append({
            'name': e.course_group.name,
            'price': str(e.course_group.monthly_price),
            'is_prorated': is_prorated,
            'total_sessions': total_sess,
            'remaining_sessions': rem_sess,
            'session_price': str(sess_price),
            'prorated_price': str(prorated_price)
        })

    data = {
        'id': student.id,
        'name': student.name,
        'matricule': student.matricule,
        'parent_contact': student.parent_contact,
        'parent_contact_2': student.parent_contact_2,
        'required': str(int(required)),
        'groups': groups
    }

    return JsonResponse(data)


def cockpit(request):
    """Simple, actionable daily dashboard for school staff"""
    from .utils import auto_generate_future_sessions
    auto_generate_future_sessions()
    
    today = timezone.now().date()
    today_sessions = Session.objects.filter(
        date=today
    ).select_related('group', 'group__teacher', 'room').order_by('start_time')
    
    today_total = today_sessions.count()
    today_done = today_sessions.filter(status='DONE').count()
    
    stats = get_dashboard_stats()
    
    recent_payments = Payment.objects.select_related('student').order_by('-payment_date', '-created_at')[:5]

    context = {
        'stats': stats,
        'today': today,
        'today_sessions': today_sessions,
        'today_total': today_total,
        'today_done': today_done,
        'recent_payments': recent_payments,
    }

    return render(request, 'core/dashboard.html', context)


def students_list(request):
    """List all students with filtering and pagination"""
    
    # Base queryset with optimizations
    students_qs = Student.objects.filter(
        is_active=True
    ).prefetch_related(
        'enrollment_set__course_group',
        'payments'
    ).select_related()
    
    # Apply filters
    student_filter = StudentFilter(request.GET, queryset=students_qs)
    filtered_qs = student_filter.qs.order_by('name')
    
    # Pagination
    page = request.GET.get('page', 1)
    per_page = request.GET.get('per_page', '25')
    
    try:
        per_page = int(per_page)
        if per_page not in [10, 25, 50, 100]:
            per_page = 25
    except (ValueError, TypeError):
        per_page = 25
    
    paginator = Paginator(filtered_qs, per_page)
    students = paginator.get_page(page)
    
    # Bulk-populate payment/monthly fee stats in memory for the current page of students
    from .utils import populate_student_payment_and_fee_info
    populate_student_payment_and_fee_info(students.object_list)
    
    # Build querystring for pagination (exclude 'page' parameter)
    qs_dict = request.GET.copy()
    qs_dict.pop('page', None)
    querystring = qs_dict.urlencode()
    
    # Check if any filters are active
    filters_active = any([
        request.GET.get('q'),
        request.GET.get('payment_status'),
        request.GET.get('course_group'),
        request.GET.get('is_active') and request.GET.get('is_active') != '',
    ])
    
    from .models import Level
    all_levels = Level.objects.all().select_related('category').order_by('category__name', 'order', 'name')

    context = {
        'students': students,
        'filter': student_filter,
        'per_page': per_page,
        'querystring': querystring,
        'filters_active': filters_active,
        'total_students': students_qs.count(),
        'filtered_count': filtered_qs.count(),
        'all_levels': all_levels,
    }
    
    return render(request, 'core/students_list.html', context)



def student_page(request, student_id):
    """Student detail page with profile, enrollments, payments, attendance, and stats"""
    from django.db.models import Count, Q
    from .utils import get_student_payment_status
    
    student = get_object_or_404(Student, pk=student_id)

    # Enrollments
    enrollments = student.enrollment_set.filter(is_active=True).select_related('course_group')
    total_enrolled = enrollments.count()
    
    # Payment info (current month)
    current_month = timezone.now().date().replace(day=1)
    payment_status = get_student_payment_status(student, current_month)
    
    # Payment history
    payments_qs = Payment.objects.filter(student=student).order_by('-payment_date', '-created_at')
    paginator = Paginator(payments_qs, 10)
    page_number = request.GET.get('page')
    payments = paginator.get_page(page_number)
    
    # Attendance stats (last 30 days)
    from datetime import timedelta
    from_date = timezone.now().date() - timedelta(days=30)
    attendance_qs = Attendance.objects.filter(student=student, date__gte=from_date).select_related('course_group').order_by('-date')
    total_classes = attendance_qs.count()
    attended_classes = attendance_qs.filter(is_present=True).count()
    attendance_rate = (attended_classes / total_classes * 100) if total_classes > 0 else 0

    # Per-group attendance breakdown
    group_attendance = []
    for enrollment in enrollments:
        grp = enrollment.course_group
        grp_qs = attendance_qs.filter(course_group=grp)
        grp_total = grp_qs.count()
        grp_present = grp_qs.filter(is_present=True).count()
        grp_absent = grp_total - grp_present
        grp_rate = round(grp_present / grp_total * 100, 1) if grp_total > 0 else None
        group_attendance.append({
            'group': grp,
            'total': grp_total,
            'present': grp_present,
            'absent': grp_absent,
            'rate': grp_rate,
        })

    # Recent attendance records (last 30 days, all groups, newest first)
    recent_attendance = list(attendance_qs[:60])  # cap at 60 rows
    
    # Monthly payment history (last 6 months)
    from dateutil.relativedelta import relativedelta
    from .utils import calculate_student_expected_fees_for_month
    six_months_ago = timezone.now().date() - relativedelta(months=6)
    payment_months = []
    for i in range(6):
        month_date = timezone.now().date() - relativedelta(months=i)
        month_date = month_date.replace(day=1)
        paid = Payment.objects.filter(
            student=student,
            month_covered=month_date,
            status='PAID'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        required = calculate_student_expected_fees_for_month(student, month_date)
        remaining = max(required - paid, Decimal('0'))
        payment_months.insert(0, {
            'month': month_date.strftime('%b %Y'),
            'paid': paid,
            'required': required,
            'remaining': remaining,
            'status': 'OK' if paid >= required else 'PARTIAL' if paid > 0 else 'UNPAID'
        })


    level_history = student.level_history.select_related('from_level', 'to_level', 'changed_by').all()
    all_levels = Level.objects.all().select_related('category')
    next_level = student.level.next_level if student.level else None

    context = {
        'student': student,
        'enrollments': enrollments,
        'total_enrolled': total_enrolled,
        'payments': payments,
        'payment_status': payment_status,
        'attendance_rate': round(attendance_rate, 1),
        'attended_classes': attended_classes,
        'absent_classes': total_classes - attended_classes,
        'total_classes': total_classes,
        'payment_months': payment_months,
        'group_attendance': group_attendance,
        'recent_attendance': recent_attendance,
        'level_history': level_history,
        'all_levels': all_levels,
        'next_level': next_level,
    }

    return render(request, 'core/student_detail.html', context)


@require_http_methods(['GET', 'POST'])
def student_promote_level(request, student_id):
    """Promote student to next level with historical tracking."""
    from .models import Level
    from .utils import promote_student_level

    student = get_object_or_404(Student, pk=student_id)
    if request.method == 'POST':
        target_level_id = request.POST.get('target_level_id')
        target_level = Level.objects.filter(pk=target_level_id).first() if target_level_id else None
        reason = request.POST.get('reason') or "Progression annuelle / Réussite du niveau"
        notes = request.POST.get('notes', '')

        success, new_level, msg = promote_student_level(student, to_level=target_level, reason=reason, user=request.user, notes=notes)
        if success:
            messages.success(request, msg)
        else:
            messages.error(request, msg)

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': success, 'message': msg, 'new_level': new_level.name if new_level else None})
        return redirect('core:student_page', student_id=student.id)

    next_level = student.level.next_level if student.level else None
    return JsonResponse({
        'student_id': student.id,
        'student_name': student.name,
        'current_level': student.level.name if student.level else None,
        'next_level_id': next_level.id if next_level else None,
        'next_level_name': next_level.name if next_level else None,
    })


@require_POST
def students_bulk_promote(request):
    """Bulk promote selected students to their configured next level or a chosen target level."""
    from .models import Level
    from .utils import promote_student_level

    student_ids = request.POST.getlist('student_ids')
    if not student_ids:
        raw_ids = request.POST.get('student_ids_csv', '')
        student_ids = [s.strip() for s in raw_ids.split(',') if s.strip()]

    if not student_ids:
        messages.error(request, "Aucun élève sélectionné pour la promotion.")
        return redirect('core:students_list')

    target_level_id = request.POST.get('target_level_id')
    target_level = Level.objects.filter(pk=target_level_id).first() if target_level_id else None
    reason = request.POST.get('reason') or "Progression groupée de niveau"
    notes = request.POST.get('notes', '')

    promoted_count = 0
    skipped_count = 0

    students = Student.objects.filter(id__in=student_ids).select_related('level')
    for st in students:
        success, new_lvl, msg = promote_student_level(st, to_level=target_level, reason=reason, user=request.user, notes=notes)
        if success:
            promoted_count += 1
        else:
            skipped_count += 1

    if promoted_count > 0:
        messages.success(request, f"🎉 {promoted_count} élève(s) promu(s) avec succès.")
    if skipped_count > 0:
        messages.warning(request, f"⚠️ {skipped_count} élève(s) non promu(s) (aucun niveau supérieur configuré ou déjà au niveau cible).")

    return redirect('core:students_list')


@require_POST
def academic_auto_upgrade(request):
    """
    One-click auto upgrade: automatically promotes all active students
    who are currently enrolled in an ACADEMIC level to their configured next_level.
    Non-academic levels are untouched.
    """
    from .models import Student, Level, LevelType
    from .utils import promote_student_level

    reason = request.POST.get('reason') or "Passage de niveau académique annuel automatique"
    notes = request.POST.get('notes', '')

    academic_students = Student.objects.filter(
        is_active=True,
        level__isnull=False,
        level__level_type=LevelType.ACADEMIC
    ).select_related('level', 'level__next_level', 'level__category')

    upgraded_count = 0
    terminal_count = 0
    skipped_count = 0

    for st in academic_students:
        target_lvl = st.level.next_level
        if not target_lvl:
            target_lvl = Level.objects.filter(
                category=st.level.category,
                order__gt=st.level.order,
                level_type=LevelType.ACADEMIC
            ).order_by('order').first()

        if not target_lvl:
            terminal_count += 1
            continue

        success, new_lvl, msg = promote_student_level(
            st,
            to_level=target_lvl,
            reason=reason,
            user=request.user,
            notes=notes
        )
        if success:
            upgraded_count += 1
        else:
            skipped_count += 1

    if upgraded_count > 0:
        messages.success(request, f"🎉 {upgraded_count} élève(s) de niveau académique ont progressé vers leur niveau supérieur avec succès !")
    if terminal_count > 0:
        messages.info(request, f"ℹ️ {terminal_count} élève(s) sont en classe terminale (aucun niveau supérieur configuré).")
    if skipped_count > 0:
        messages.warning(request, f"⚠️ {skipped_count} élève(s) n'ont pas pu être promus.")
    if upgraded_count == 0 and terminal_count == 0:
        messages.info(request, "Aucun élève en niveau académique à faire progresser.")

    return redirect('core:students_list')



def sessions_today(request):
    """Enhanced session view with navigation and statistics, support for uncompleted past sessions"""
    from .utils import auto_generate_future_sessions
    auto_generate_future_sessions()
    
    today = timezone.now().date()
    mode = request.GET.get('mode')
    
    if mode == 'uncompleted':
        # Show all past planned sessions that need attendance input
        sessions_qs = Session.objects.filter(
            date__lt=today,
            status='PLANNED'
        ).select_related(
            'group',
            'group__teacher',
            'room'
        ).prefetch_related(
            'group__students'
        ).order_by('-date', 'start_time')
        
        view_date = None
        prev_day = None
        next_day = None
    else:
        # Determine the date to display
        date_param = request.GET.get('date')
        if date_param:
            try:
                from datetime import datetime
                view_date = datetime.strptime(date_param, '%Y-%m-%d').date()
            except (ValueError, TypeError):
                view_date = today
        else:
            view_date = today
        
        # Calculate navigation dates
        prev_day = view_date - timedelta(days=1)
        next_day = view_date + timedelta(days=1)
        
        # Base queryset for the view date
        sessions_qs = Session.objects.filter(
            date=view_date
        ).select_related(
            'group',
            'group__teacher',
            'room'
        ).prefetch_related(
            'group__students'
        ).order_by('start_time')
    
    # Hide draft schedules for teachers
    is_teacher = hasattr(request.user, 'profile') and request.user.profile.role == 'TEACHER'
    if is_teacher:
        sessions_qs = sessions_qs.filter(schedule_status='PUBLISHED')

    # Apply filters
    session_filter = SessionFilter(request.GET, queryset=sessions_qs)
    sessions = list(session_filter.qs)
    
    # Calculate statistics in memory to avoid multiple COUNT database queries
    total_count = len(sessions)
    if mode == 'uncompleted':
        stats = {
            'total': total_count,
            'planned': total_count,
            'done': 0,
            'cancelled': 0,
        }
    else:
        stats = {
            'total': total_count,
            'planned': sum(1 for s in sessions if s.status == 'PLANNED'),
            'done': sum(1 for s in sessions if s.status == 'DONE'),
            'cancelled': sum(1 for s in sessions if s.status == 'CANCELLED'),
        }
    
    # Check if any filters are active (excluding date parameter)
    filters_active = any([
        request.GET.get('date_after'),
        request.GET.get('date_before'),
        request.GET.get('room'),
        request.GET.get('teacher'),
        request.GET.get('status'),
        request.GET.get('group_name'),
    ])
    
    # Build querystring for navigation (preserve filters)
    qs_dict = request.GET.copy()
    qs_dict.pop('date', None)  # Remove date to add it dynamically
    querystring = qs_dict.urlencode()
    
    # Count of all past planned sessions for navigation badge
    past_uncompleted_count = Session.objects.filter(date__lt=today, status='PLANNED').count()
    
    context = {
        'sessions': sessions,
        'view_date': view_date,
        'today': today,
        'prev_day': prev_day,
        'next_day': next_day,
        'is_today': view_date == today,
        'filter': session_filter,
        'stats': stats,
        'filters_active': filters_active,
        'querystring': querystring,
        'mode': mode,
        'past_uncompleted_count': past_uncompleted_count,
    }
    
    return render(request, 'core/sessions_today.html', context)

@require_http_methods(['GET', 'POST'])
def session_create(request):
    """Create a new session (class)"""
    if request.method == 'POST':
        form = SessionForm(request.POST)
        if form.is_valid():
            s = form.save(commit=False)
            try:
                from core.services.scheduling.locking import LockingService
                from core.services.scheduling.audit import AuditService
                
                # Check Lock
                LockingService.check_lock(s.date)
                
                s.is_manually_edited = True
                s.full_clean()
                s.save()
                
                # Audit log creation
                AuditService.log_change(
                    session=s,
                    user=request.user,
                    action='create',
                    previous_values={},
                    new_values={
                        'date': str(s.date),
                        'start_time': s.start_time.strftime('%H:%M'),
                        'end_time': s.end_time.strftime('%H:%M'),
                        'room': s.room.name if s.room else '',
                        'status': s.status
                    },
                    change_reason=request.POST.get('change_reason', 'Création manuelle'),
                    ip_address=request.META.get('REMOTE_ADDR')
                )
            except Exception as e:
                form.add_error(None, str(e))
            else:
                return render(request, 'core/session_form_saved.html', {'session': s})
    else:
        form = SessionForm()

    return render(request, 'core/session_form.html', {
        'form': form,
        'action': 'Créer',
        'form_warnings': getattr(form, 'warnings', []),
    })


@require_http_methods(['GET', 'POST'])
def session_edit(request, session_id):
    """Edit an existing session with recurring schedule update modes."""
    session = get_object_or_404(Session, pk=session_id)
    if request.method == 'POST':
        form = SessionForm(request.POST, instance=session)
        if form.is_valid():
            scope = request.POST.get('update_mode', 'only_this')
            change_reason = request.POST.get('change_reason', '')
            
            updates = {
                'start_time': form.cleaned_data['start_time'],
                'end_time': form.cleaned_data['end_time'],
                'room_id': form.cleaned_data['room'].id if form.cleaned_data.get('room') else None,
                'status': form.cleaned_data['status'],
                'notes': form.cleaned_data['notes'],
                'substitute_teacher_id': form.cleaned_data['substitute_teacher'].id if form.cleaned_data.get('substitute_teacher') else None,
            }
            
            try:
                from core.services.scheduling import SchedulingFacade
                updated_list = SchedulingFacade.propagate_session_changes(
                    session=session,
                    scope=scope,
                    updates=updates,
                    user=request.user,
                    ip_address=request.META.get('REMOTE_ADDR'),
                    change_reason=change_reason
                )
                count = len(updated_list)
                return render(request, 'core/session_form_saved.html', {
                    'session': session,
                    'count': count,
                    'scope': scope
                })
            except Exception as e:
                form.add_error(None, str(e))
    else:
        form = SessionForm(instance=session)

    return render(request, 'core/session_form.html', {
        'form': form,
        'action': 'Modifier',
        'session': session,
        'form_warnings': getattr(form, 'warnings', []),
    })


@require_http_methods(['POST'])
def session_delete(request, session_id):
    """Delete a session with locking checks and audit logs."""
    session = get_object_or_404(Session, pk=session_id)
    try:
        from core.services.scheduling.locking import LockingService
        from core.services.scheduling.audit import AuditService
        
        LockingService.check_lock(session.date)
        
        # Log before deletion
        AuditService.log_change(
            session=session,
            user=request.user,
            action='delete',
            previous_values={
                'date': str(session.date),
                'start_time': session.start_time.strftime('%H:%M'),
                'end_time': session.end_time.strftime('%H:%M'),
                'group': session.group.name if session.group else '',
                'room': session.room.name if session.room else ''
            },
            new_values={},
            change_reason=request.POST.get('change_reason', 'Suppression manuelle'),
            ip_address=request.META.get('REMOTE_ADDR')
        )
        
        session.delete()
        return render(request, 'core/session_deleted.html', {'session_id': session_id})
    except Exception as e:
        from django.contrib import messages
        messages.error(request, str(e))
        return redirect('core:sessions_schedule')



@require_http_methods(['GET', 'POST'])
def session_attendance(request, session_id):
    """Show attendance checklist for a session and save attendance.

    Business rule: default all present; admin unchecks absentees.
    """
    session = get_object_or_404(Session, pk=session_id)
    students = session.group.students.filter(is_active=True)

    if request.method == 'GET':
        # prefill: check if Attendance exists for this date/group
        existing = Attendance.objects.filter(course_group=session.group, date=session.date)
        present_map = {a.student_id: a.is_present for a in existing}
        
        from .utils import populate_student_payment_and_fee_info
        month_covered = session.date.replace(day=1)
        students_obj_list = list(students)
        populate_student_payment_and_fee_info(students_obj_list, month_covered)
        
        students_list = []
        for s in students_obj_list:
            # default to True (present) when no record exists
            checked = present_map.get(s.id, True)
            is_unpaid = getattr(s, 'computed_payment_status', 'OK') in ('UNPAID', 'PARTIAL')
            students_list.append({
                'student': s,
                'checked': checked,
                'is_unpaid': is_unpaid,
                'remaining': getattr(s, 'computed_remaining', Decimal('0.00'))
            })

        return render(request, 'core/session_attendance.html', {
            'session': session,
            'students_list': students_list,
        })

    # POST: process attendance form
    # expected: checkbox 'present_<student_id>' for those present
    with transaction.atomic():
        for student in students:
            key = f'present_{student.id}'
            is_present = key in request.POST
            att, created = Attendance.objects.update_or_create(
                student=student,
                course_group=session.group,
                date=session.date,
                defaults={
                    'is_present': is_present,
                    'session': session,
                }
            )

    # mark session as DONE if attendance saved
    session.status = 'DONE'
    session.save()

    return render(request, 'core/session_attendance_saved.html', {'session': session})


def teacher_payroll(request):
    """Calculate payroll for a teacher for a selected month."""
    from .models import Teacher, Session, TeacherPayment, Payment
    from .utils import calculate_teacher_hours, calculate_student_monthly_total
    from django.db.models import Q, Sum
    from django.contrib import messages
    from datetime import date, datetime
    import calendar
    
    teacher_qs = Teacher.objects.filter(is_active=True).order_by('name')

    FRENCH_MONTHS = ['', 'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin', 'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']
    today = timezone.now().date()
    months_list = []
    for i in range(18):
        y = today.year
        m = today.month - i
        while m <= 0:
            m += 12
            y -= 1
        months_list.append({
            'value': f"{y}-{m:02d}",
            'label': f"{FRENCH_MONTHS[m]} {y}"
        })

    selected_month = request.POST.get('month') or request.GET.get('month') or f"{today.year}-{today.month:02d}"
    selected_teacher_id = request.POST.get('teacher_id') or request.GET.get('teacher_id') or ''

    result = None
    if request.method == 'POST' or request.GET.get('teacher_id'):
        action = request.POST.get('action') or 'calculate'
        teacher_id = request.POST.get('teacher_id') or request.GET.get('teacher_id')
        month_str = request.POST.get('month') or request.GET.get('month') or f"{today.year}-{today.month:02d}"

        if teacher_id and month_str:
            teacher = get_object_or_404(Teacher, pk=teacher_id)
            selected_teacher_id = str(teacher.id)
            selected_month = month_str

            try:
                year_m, mon_m = int(month_str[:4]), int(month_str[5:7])
                start_d = date(year_m, mon_m, 1)
                end_d = date(year_m, mon_m, calendar.monthrange(year_m, mon_m)[1])
            except (ValueError, IndexError):
                start_d = date(today.year, today.month, 1)
                end_d = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
                year_m, mon_m = today.year, today.month

            if action == 'save_payment':
                amount = request.POST.get('amount')
                pay_date_str = request.POST.get('payment_date')
                method = request.POST.get('payment_method', 'CASH')
                pay_type = request.POST.get('payment_type', 'SALARY')
                notes = request.POST.get('notes', '')

                if amount:
                    pay_date = datetime.strptime(pay_date_str, '%Y-%m-%d').date() if pay_date_str else today
                    TeacherPayment.objects.create(
                        teacher=teacher,
                        amount=Decimal(amount),
                        payment_date=pay_date,
                        payment_method=method,
                        payment_type=pay_type,
                        period_month=mon_m,
                        period_year=year_m,
                        notes=notes
                    )
                    messages.success(request, f"Paiement de {amount} DH enregistré pour {teacher.name}.")
                else:
                    messages.error(request, "Veuillez préciser le montant du versement.")

            # Sessions list
            sessions = Session.objects.filter(
                Q(group__teacher=teacher, substitute_teacher__isnull=True) | Q(substitute_teacher=teacher),
                status='DONE',
                date__range=[start_d, end_d]
            ).order_by('date', 'start_time')

            sessions_list = [{'session': s, 'hours': s.duration_hours()} for s in sessions]

            # Payroll calculation
            payroll_data = calculate_teacher_hours(teacher, start_d, end_d)

            # Enrich payroll_data based on payment method
            if teacher.payment_method == 'PERCENTAGE':
                total_active_students = 0
                total_paid_students = 0
                total_unpaid_students = 0
                total_group_revenue = Decimal('0.00')

                for cb in payroll_data.get('courses_breakdown', []):
                    c = cb['course']
                    active_enrollments = list(c.enrollment_set.filter(is_active=True).select_related('student'))
                    st_count = len(active_enrollments)
                    monthly_fee = c.monthly_price or Decimal('0.00')
                    group_paid_count = 0
                    group_collected_rev = Decimal('0.00')
                    students_info = []

                    for enr in active_enrollments:
                        st = enr.student
                        pmts = Payment.objects.filter(
                            student=st,
                            month_covered=start_d,
                            status='PAID'
                        ).order_by('-payment_date')
                        st_paid_total = pmts.aggregate(tot=Sum('amount'))['tot'] or Decimal('0.00')
                        req_total = calculate_student_monthly_total(st)

                        is_paid = (req_total > 0 and st_paid_total >= req_total) or (req_total == 0 and st_paid_total > 0)
                        is_partial = (req_total > 0 and 0 < st_paid_total < req_total)

                        pct = teacher.payment_percentage if teacher.payment_percentage is not None else Decimal('50.00')
                        if is_paid:
                            group_paid_count += 1
                            group_collected_rev += monthly_fee
                            st_share = (monthly_fee * pct / Decimal('100.00')).quantize(Decimal('0.01'))
                        elif is_partial:
                            group_paid_count += 1
                            ratio = min(st_paid_total / req_total, Decimal('1.00'))
                            effective_rev = (monthly_fee * ratio).quantize(Decimal('0.01'))
                            group_collected_rev += effective_rev
                            st_share = (effective_rev * pct / Decimal('100.00')).quantize(Decimal('0.01'))
                        else:
                            st_share = Decimal('0.00')

                        latest_p = pmts.first()
                        students_info.append({
                            'student': st,
                            'fee': monthly_fee,
                            'paid_amount': st_paid_total,
                            'status': 'PAID' if is_paid else ('PARTIAL' if is_partial else 'UNPAID'),
                            'payment_date': latest_p.payment_date if latest_p else None,
                            'payment_method': latest_p.get_payment_method_display() if latest_p else None,
                            'teacher_share': st_share,
                        })

                    group_unpaid_count = max(0, st_count - group_paid_count)
                    group_rec_pct = round((group_paid_count / st_count * 100), 1) if st_count > 0 else 0.0

                    cb['students_info'] = students_info
                    cb['paid_count'] = group_paid_count
                    cb['unpaid_count'] = group_unpaid_count
                    cb['recovery_pct'] = group_rec_pct
                    cb['monthly_fee'] = monthly_fee
                    cb['collected_revenue'] = group_collected_rev

                    total_active_students += st_count
                    total_paid_students += group_paid_count
                    total_unpaid_students += group_unpaid_count
                    total_group_revenue += group_collected_rev

                global_recovery_rate = round((total_paid_students / total_active_students * 100), 1) if total_active_students > 0 else 0.0
                payroll_data['total_active_students'] = total_active_students
                payroll_data['total_paid_students'] = total_paid_students
                payroll_data['total_unpaid_students'] = total_unpaid_students
                payroll_data['global_recovery_rate'] = global_recovery_rate
                payroll_data['total_group_revenue'] = total_group_revenue

            elif teacher.payment_method == 'HOURLY':
                hourly_rate = teacher.hourly_rate or Decimal('0.00')
                hourly_groups = []
                for course in teacher.course_groups.filter(is_active=True).prefetch_related('levels'):
                    group_sessions = [s for s in sessions if s.group_id == course.id]
                    h_taught = sum(Decimal(str(s.duration_hours())) for s in group_sessions)
                    subtotal = (h_taught * hourly_rate).quantize(Decimal('0.01'))
                    hourly_groups.append({
                        'group': course,
                        'sessions_count': len(group_sessions),
                        'hours_taught': h_taught,
                        'rate': hourly_rate,
                        'subtotal': subtotal
                    })

                for item in sessions_list:
                    h = Decimal(str(item['hours']))
                    item['rate'] = hourly_rate
                    item['subtotal'] = (h * hourly_rate).quantize(Decimal('0.01'))

                payroll_data['hourly_rate'] = hourly_rate
                payroll_data['hourly_groups'] = hourly_groups

            elif teacher.payment_method == 'SESSION':
                session_rate = teacher.session_rate or Decimal('0.00')
                for item in sessions_list:
                    item['rate'] = session_rate
                    item['subtotal'] = session_rate
                payroll_data['session_rate'] = session_rate

            # Logged payments for this month
            logged_payments = TeacherPayment.objects.filter(
                teacher=teacher,
                period_month=mon_m,
                period_year=year_m
            ).order_by('payment_date', 'id')
            total_paid = sum((p.amount for p in logged_payments), Decimal('0.00'))

            result = {
                'teacher': teacher,
                'sessions': sessions_list,
                'logged_payments': logged_payments,
                'total_paid': total_paid,
                'balance': payroll_data['salary_taught'] - total_paid,
                'month_str': month_str,
                'month_label': f"{FRENCH_MONTHS[mon_m]} {year_m}",
                'start_date_str': start_d.strftime('%Y-%m-%d'),
                'end_date_str': end_d.strftime('%Y-%m-%d'),
                'mon_m': mon_m,
                'year_m': year_m,
                **payroll_data
            }

    return render(request, 'core/teacher_payroll.html', {
        'teacher_qs': teacher_qs,
        'result': result,
        'months_list': months_list,
        'selected_month': selected_month,
        'selected_teacher_id': str(selected_teacher_id),
    })


def courses_list(request):
    """Display all course groups (classes) with summary info."""
    from .models import CourseGroup
    courses = CourseGroup.objects.all().select_related('teacher', 'level').prefetch_related('levels', 'schedules__room')
    
    # Annotate with enrollment count
    from django.db.models import Count
    courses = courses.annotate(enrollment_count=Count('enrollment'))

    course_filter = CourseGroupFilter(request.GET, queryset=courses)
    courses = course_filter.qs

    return render(request, 'core/courses_list.html', {'courses': courses, 'filter': course_filter})


def group_detail(request, group_id):
    """Detailed view for a single CourseGroup."""
    from .models import CourseGroup, Session, Payment
    from django.db.models import Sum, Q
    from django.utils import timezone

    group = get_object_or_404(
        CourseGroup.objects.select_related('teacher', 'level').prefetch_related('levels', 'schedules__room'),
        pk=group_id
    )

    # Students enrolled in this group
    students = list(group.students.select_related('level').order_by('name'))
    from .utils import populate_student_payment_and_fee_info
    populate_student_payment_and_fee_info(students)
    total_students = len(students)

    # Monthly revenue estimate
    monthly_revenue = group.monthly_price * total_students

    # Sessions stats
    sessions_qs = Session.objects.filter(group=group).select_related('room', 'substitute_teacher')
    total_sessions = sessions_qs.count()
    planned_sessions = sessions_qs.filter(status='PLANNED').count()
    done_sessions = sessions_qs.filter(status='DONE').count()
    cancelled_sessions = sessions_qs.filter(status='CANCELLED').count()

    # Recent/upcoming sessions (last 10 done + next 10 planned)
    from datetime import date
    today = date.today()
    past_sessions = list(sessions_qs.filter(date__lt=today).order_by('-date')[:10])
    future_sessions = list(sessions_qs.filter(date__gte=today).order_by('date')[:10])
    recent_sessions = sorted(past_sessions + future_sessions, key=lambda s: s.date, reverse=True)

    # Current month payments for students in this group
    now = timezone.now()
    current_month_payments = Payment.objects.filter(
        student__in=students,
        payment_date__year=now.year,
        payment_date__month=now.month,
    ).select_related('student').order_by('-payment_date')
    current_month_total = current_month_payments.aggregate(t=Sum('amount'))['t'] or 0

    schedules = group.schedules.all()
    available_students = Student.objects.filter(is_active=True).exclude(enrollment__course_group=group).order_by('name')

    return render(request, 'core/course_group_detail.html', {
        'group': group,
        'students': students,
        'available_students': available_students,
        'total_students': total_students,
        'monthly_revenue': monthly_revenue,
        'schedules': schedules,
        'total_sessions': total_sessions,
        'planned_sessions': planned_sessions,
        'done_sessions': done_sessions,
        'cancelled_sessions': cancelled_sessions,
        'recent_sessions': recent_sessions,
        'current_month_payments': current_month_payments,
        'current_month_total': current_month_total,
    })


def teachers_list(request):
    """Display all teachers with summary info."""
    from .models import Teacher

    teachers = Teacher.objects.annotate(
        course_count=Count('course_groups', distinct=True),
        session_count=Count(
            'course_groups__sessions',
            filter=Q(course_groups__sessions__status='PLANNED'),
            distinct=True
        )
    )

    teacher_filter = TeacherFilter(request.GET, queryset=teachers)
    teachers = teacher_filter.qs

    return render(request, 'core/teachers_list.html', {'teachers': teachers, 'filter': teacher_filter})

def rooms_list(request):
    """Display all rooms with summary info."""
    from .models import Room
    from django.db.models import Count
    
    rooms = Room.objects.all()
    rooms = rooms.annotate(
        course_count=Count('schedules__course_group', distinct=True),
        session_count=Count('sessions', filter=Q(sessions__status='PLANNED'), distinct=True)
    )
    
    room_filter = RoomFilter(request.GET, queryset=rooms)
    rooms = room_filter.qs

    return render(request, 'core/rooms_list.html', {'rooms': rooms, 'filter': room_filter})


def sessions_schedule(request):
    """Enhanced weekly schedule view with better structure and filtering"""
    from .utils import auto_generate_future_sessions
    auto_generate_future_sessions()

    from core.services.scheduling import SchedulingFacade
    
    # Get the week starting date (Monday)
    today = timezone.now().date()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    
    # Get week parameter from request
    week_param = request.GET.get('week')
    if week_param:
        try:
            parsed = datetime.strptime(week_param, '%Y-%m-%d').date()
            # Normalize to Monday
            week_start = parsed - timedelta(days=parsed.weekday())
            week_end = week_start + timedelta(days=6)
        except (ValueError, TypeError):
            pass  # Keep current week
    
    # Determine view mode (room-based or teacher-based)
    view_mode = request.GET.get('view', 'teacher')  # 'room' or 'teacher'
    
    # Get filter parameters
    room_filter = request.GET.get('room_id')
    teacher_filter = request.GET.get('teacher_id')
    group_filter = request.GET.get('group_id')
    status_filter = request.GET.get('status')
    search_query = request.GET.get('q', '').strip()
    exceptions_only = request.GET.get('exceptions_only') == 'on'
    
    # Build list of dates for the week
    dates = [week_start + timedelta(days=i) for i in range(7)]
    
    # Base sessions queryset for the week
    base_sessions = Session.objects.filter(
        date__range=[week_start, week_end]
    ).select_related(
        'group',
        'group__teacher',
        'substitute_teacher',
        'room'
    ).prefetch_related(
        'group__students'
    )
    
    # Hide draft schedules for teachers
    is_teacher = hasattr(request.user, 'profile') and request.user.profile.role == 'TEACHER'
    if is_teacher:
        base_sessions = base_sessions.filter(schedule_status='PUBLISHED')
    
    # Apply filters
    if room_filter:
        base_sessions = base_sessions.filter(room_id=room_filter)
    if teacher_filter:
        base_sessions = base_sessions.filter(
            Q(substitute_teacher_id=teacher_filter) |
            Q(substitute_teacher__isnull=True, group__teacher_id=teacher_filter)
        )
    if group_filter:
        base_sessions = base_sessions.filter(group_id=group_filter)
    if status_filter:
        base_sessions = base_sessions.filter(status=status_filter)
    if search_query:
        base_sessions = base_sessions.filter(
            Q(group__name__icontains=search_query) |
            Q(group__subject__icontains=search_query) |
            Q(group__teacher__name__icontains=search_query) |
            Q(substitute_teacher__name__icontains=search_query) |
            Q(room__name__icontains=search_query)
        )
    
    # Get all rooms and teachers for the filters
    rooms = Room.objects.filter(is_active=True).order_by('name')
    teachers = Teacher.objects.filter(is_active=True).order_by('name')
    
    # Annotate and load sessions in-memory
    annotated_sessions = _annotate_conflicts(base_sessions)
    if exceptions_only:
        annotated_sessions = [s for s in annotated_sessions if s.is_exceptional]

    from core.services.scheduling.audit import AuditService
    unhandled_changes_count = SchedulingFacade.get_unhandled_count()
    unhandled_session_ids = AuditService.get_unhandled_session_ids()
    for s in annotated_sessions:
        s.has_unhandled_change = s.id in unhandled_session_ids
    
    # Build schedule grid based on view mode
    if view_mode == 'teacher':
        rows = _build_teacher_schedule(teachers, dates, annotated_sessions)
        row_label = 'Professeur'
    else:
        rows = _build_room_schedule(rooms, dates, annotated_sessions)
        row_label = 'Salle'
    
    # Build date labels with weekday names
    weekdays = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche']
    date_labels = [
        {
            'weekday': weekdays[i],
            'date': date,
            'is_today': date == today,
            'is_weekend': i >= 5
        }
        for i, date in enumerate(dates)
    ]
    
    # Calculate statistics
    stats = _calculate_week_stats(annotated_sessions, dates)
    
    # Check if filters are active
    filters_active = any([room_filter, teacher_filter, group_filter, status_filter, search_query, exceptions_only])
    
    context = {
        'week_start': week_start,
        'week_end': week_end,
        'prev_week': week_start - timedelta(days=7),
        'next_week': week_start + timedelta(days=7),
        'dates': dates,
        'date_labels': date_labels,
        'rows': rows,
        'row_label': row_label,
        'view_mode': view_mode,
        'rooms': rooms,
        'teachers': teachers,
        'stats': stats,
        'today': today,
        'filters_active': filters_active,
        'room_filter': room_filter,
        'teacher_filter': teacher_filter,
        'group_filter': group_filter,
        'status_filter': status_filter,
        'search_query': search_query,
        'exceptions_only': exceptions_only,
        'courses': CourseGroup.objects.filter(is_active=True).order_by('name'),
        'all_levels': Level.objects.all().select_related('category').order_by('category__name', 'order', 'name'),
        'all_groups': CourseGroup.objects.filter(is_active=True).prefetch_related('levels').order_by('name'),
        'is_week_locked': any(SchedulingFacade.is_locked(d) for d in dates),
        'unhandled_changes_count': unhandled_changes_count,
        'unhandled_session_ids': list(unhandled_session_ids),
    }

    return render(request, 'core/sessions_schedule.html', context)


@require_GET
def sessions_search_ajax(request):
    """
    AJAX endpoint — returns JSON list of sessions matching the given filters.
    Supports: q, room_id, teacher_id, group_id, status, week (YYYY-MM-DD),
    date_from / date_to for arbitrary date ranges.
    """
    from django.db.models import Q
    today = timezone.now().date()

    # ── Date range ────────────────────────────────────────────────────────────
    week_param = request.GET.get('week')
    date_from_param = request.GET.get('date_from')
    date_to_param   = request.GET.get('date_to')

    if date_from_param and date_to_param:
        try:
            date_from = datetime.strptime(date_from_param, '%Y-%m-%d').date()
            date_to   = datetime.strptime(date_to_param,   '%Y-%m-%d').date()
        except ValueError:
            date_from = today - timedelta(days=today.weekday())
            date_to   = date_from + timedelta(days=6)
    else:
        if week_param:
            try:
                parsed = datetime.strptime(week_param, '%Y-%m-%d').date()
                date_from = parsed - timedelta(days=parsed.weekday())
            except ValueError:
                date_from = today - timedelta(days=today.weekday())
        else:
            date_from = today - timedelta(days=today.weekday())
        date_to = date_from + timedelta(days=6)

    qs = Session.objects.filter(
        date__range=[date_from, date_to]
    ).select_related('group', 'group__teacher', 'substitute_teacher', 'room')

    # ── Text search ───────────────────────────────────────────────────────────
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(group__name__icontains=q) |
            Q(group__subject__icontains=q) |
            Q(group__teacher__name__icontains=q) |
            Q(substitute_teacher__name__icontains=q) |
            Q(room__name__icontains=q)
        )

    # ── Dimension filters ─────────────────────────────────────────────────────
    room_id     = request.GET.get('room_id')
    teacher_id  = request.GET.get('teacher_id')
    group_id    = request.GET.get('group_id')
    status      = request.GET.get('status')

    if room_id:    qs = qs.filter(room_id=room_id)
    if teacher_id: qs = qs.filter(
        Q(substitute_teacher_id=teacher_id) |
        Q(substitute_teacher__isnull=True, group__teacher_id=teacher_id)
    )
    if group_id:   qs = qs.filter(group_id=group_id)
    if status:     qs = qs.filter(status=status)

    sessions_data = []
    for s in qs.order_by('date', 'start_time')[:200]:
        teacher_name = s.substitute_teacher.name if s.substitute_teacher else (s.group.teacher.name if s.group and s.group.teacher else '')
        sessions_data.append({
            'id':          s.pk,
            'date':        s.date.strftime('%Y-%m-%d'),
            'start_time':  s.start_time.strftime('%H:%M'),
            'end_time':    s.end_time.strftime('%H:%M'),
            'group':       s.group.name,
            'subject':     s.group.subject,
            'teacher':     teacher_name,
            'room':        s.room.name if s.room else '',
            'status':      s.status,
            'is_exceptional': s.is_exceptional,
        })

    return JsonResponse({'results': sessions_data, 'count': len(sessions_data)})


@require_GET
def print_admin_schedule(request):
    """Generate PDF of the full weekly schedule for admin."""
    week_param = request.GET.get('week')
    today = timezone.now().date()
    if week_param:
        try:
            parsed = datetime.strptime(week_param, '%Y-%m-%d').date()
            week_start = parsed - timedelta(days=parsed.weekday())
            week_end = week_start + timedelta(days=6)
        except Exception:
            week_start = today - timedelta(days=today.weekday())
            week_end = week_start + timedelta(days=6)
    else:
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)

    sessions_qs = Session.objects.filter(date__range=[week_start, week_end]).select_related('group', 'group__teacher', 'room').prefetch_related('group__students').order_by('date', 'start_time')
    sessions = list(sessions_qs)

    from .utils import generate_schedule_pdf
    pdf_buf = generate_schedule_pdf(sessions, title=f"Planification {week_start.strftime('%d/%m/%Y')} - {week_end.strftime('%d/%m/%Y')}")
    response = HttpResponse(pdf_buf.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="schedule_{week_start.strftime("%Y%m%d")}.pdf"'
    return response


@require_GET
def print_teacher_schedule(request, teacher_id):
    """Generate PDF schedule for a specific teacher for the selected week."""
    week_param = request.GET.get('week')
    today = timezone.now().date()
    if week_param:
        try:
            parsed = datetime.strptime(week_param, '%Y-%m-%d').date()
            week_start = parsed - timedelta(days=parsed.weekday())
            week_end = week_start + timedelta(days=6)
        except Exception:
            week_start = today - timedelta(days=today.weekday())
            week_end = week_start + timedelta(days=6)
    else:
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)

    sessions_qs = Session.objects.filter(
        date__range=[week_start, week_end]
    ).filter(
        Q(substitute_teacher_id=teacher_id) |
        Q(substitute_teacher__isnull=True, group__teacher_id=teacher_id)
    ).select_related('group', 'group__teacher', 'substitute_teacher', 'room').prefetch_related('group__students').order_by('date', 'start_time')
    sessions = list(sessions_qs)
    teacher = get_object_or_404(Teacher, pk=teacher_id)

    from .utils import generate_schedule_pdf
    pdf_buf = generate_schedule_pdf(sessions, title=f"Planification — {teacher.name} — semaine {week_start.strftime('%d/%m/%Y')}")
    response = HttpResponse(pdf_buf.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="schedule_teacher_{teacher_id}_{week_start.strftime("%Y%m%d")}.pdf"'
    return response


@require_GET
def print_student_schedule(request, student_id):
    """Generate PDF schedule for a specific student for the selected week."""
    week_param = request.GET.get('week')
    today = timezone.now().date()

    if week_param:
        try:
            parsed = datetime.strptime(week_param, '%Y-%m-%d').date()
            week_start = parsed - timedelta(days=parsed.weekday())
        except ValueError:
            week_start = today - timedelta(days=today.weekday())
    else:
        week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    student = get_object_or_404(Student, pk=student_id)
    enrollments = student.enrollment_set.filter(is_active=True).values_list('course_group_id', flat=True)

    sessions = list(
        Session.objects.filter(
            date__range=[week_start, week_end],
            group_id__in=list(enrollments),
        )
        .select_related('group', 'group__teacher', 'room')
        .order_by('date', 'start_time')
    )

    from .utils import generate_student_schedule_pdf
    pdf_buf = generate_student_schedule_pdf(
        sessions,
        student_name=student.name,
        title=f"Planification — {student.name} — semaine {week_start.strftime('%d/%m/%Y')}",
    )

    response = HttpResponse(pdf_buf.read(), content_type='application/pdf')
    response['Content-Disposition'] = (
        f'attachment; filename="schedule_student_{student_id}_{week_start.strftime("%Y%m%d")}.pdf"'
    )
    return response

@require_GET
def print_students_list(request):
    """Generate PDF list of all students with details."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from io import BytesIO
    
    # Get filtered students
    students_qs = Student.objects.filter(is_active=True).prefetch_related(
        'enrollment_set__course_group',
        'payments'
    ).order_by('name')
    
    # Apply filters if provided
    student_filter = StudentFilter(request.GET, queryset=students_qs)
    students = student_filter.qs
    
    # Create PDF buffer
    pdf_buffer = BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=A4, topMargin=20, bottomMargin=20, leftMargin=15, rightMargin=15)
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=6,
        fontName='Helvetica-Bold'
    )
    
    header_style = ParagraphStyle(
        'TableHeader',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.whitesmoke,
        fontName='Helvetica-Bold',
        alignment=1
    )
    
    # Document elements
    elements = []
    
    # Title
    elements.append(Paragraph("Liste des Élèves", title_style))
    elements.append(Spacer(1, 0.2*inch))
    
    # Build table data
    table_data = [['Matricule', 'Nom', 'Contact', 'Cours', 'Frais/mois', 'Statut']]
    
    from .utils import populate_student_payment_and_fee_info
    students_list_all = list(students)
    populate_student_payment_and_fee_info(students_list_all)
    
    for student in students_list_all:
        matricule = student.matricule or '—'
        name = student.name
        phone = student.parent_contact or '—'
        enrollments = len(getattr(student, 'computed_active_enrollments', []))
        courses = f"{enrollments} cours"
        fees = f"{getattr(student, 'computed_total_monthly_fees', student.total_monthly_fees())} DH"
        status = getattr(student, 'computed_payment_status', student.payment_status())
        status_display = {
            'OK': '✓ Payé',
            'PARTIAL': '⚠ Partiel',
            'UNPAID': '✗ Impayé'
        }.get(status, status)
        
        table_data.append([matricule, name, phone, courses, fees, status_display])
    
    # Create table
    if len(table_data) > 1:
        table = Table(table_data, colWidths=[0.9*inch, 1.6*inch, 1.4*inch, 0.9*inch, 1.1*inch, 1.0*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
        ]))
        elements.append(table)
    else:
        elements.append(Paragraph("Aucun élève à afficher.", styles['Normal']))
    
    elements.append(Spacer(1, 0.3*inch))
    elements.append(Paragraph(f"Total: <b>{len(table_data) - 1}</b> élèves", styles['Normal']))
    
    for row_index, student in enumerate(students_list_all, start=1):  # start=1 because row 0 is the header
        if getattr(student, 'computed_payment_status', 'OK') == 'UNPAID':
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, row_index), (-1, row_index), colors.HexColor('#ffcccc')),
                ('TEXTCOLOR', (0, row_index), (-1, row_index), colors.red),
                ('FONTNAME', (0, row_index), (-1, row_index), 'Helvetica-Bold'),
            ]))

    # Build PDF
    doc.build(elements)
    pdf_buffer.seek(0)
    
    response = HttpResponse(pdf_buffer.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="students_list_{timezone.now().strftime("%Y%m%d")}.pdf"'
    return response


@require_GET
def print_teachers_list(request):
    """Generate PDF list of all teachers with details."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from django.db.models import Count, Q
    
    # Get filtered teachers
    teachers_qs = Teacher.objects.filter(is_active=True).annotate(
        course_count=Count('course_groups', filter=Q(course_groups__is_active=True), distinct=True)
    ).order_by('name')
    
    # Apply filters if provided
    teacher_filter = TeacherFilter(request.GET, queryset=teachers_qs)
    teachers = teacher_filter.qs
    
    # Create PDF buffer
    pdf_buffer = BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=A4, topMargin=20, bottomMargin=20, leftMargin=15, rightMargin=15)
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=6,
        fontName='Helvetica-Bold'
    )
    
    # Document elements
    elements = []
    
    # Title
    elements.append(Paragraph("Liste des Professeurs", title_style))
    elements.append(Spacer(1, 0.2*inch))
    
    # Build table data
    table_data = [['Nom', 'Téléphone', 'Email', 'Mode de paiement', 'Groupes']]
    
    for teacher in teachers:
        name = teacher.name
        phone = teacher.phone or '—'
        email = teacher.email or '—'
        
        if teacher.payment_method == 'PERCENTAGE':
            payment_mode = f"{teacher.payment_percentage}% des gains"
        elif teacher.payment_method == 'SESSION':
            payment_mode = f"{teacher.session_rate} DH/session"
        else:
            payment_mode = f"{teacher.hourly_rate} DH/h"
        
        groups = f"{teacher.course_count}"
        
        table_data.append([name, phone, email, payment_mode, groups])
    
    # Create table
    if len(table_data) > 1:
        table = Table(table_data, colWidths=[1.5*inch, 1.2*inch, 1.5*inch, 1.8*inch, 0.8*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#27ae60')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (2, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
        ]))
        elements.append(table)
    else:
        elements.append(Paragraph("Aucun professeur à afficher.", styles['Normal']))
    
    elements.append(Spacer(1, 0.3*inch))
    elements.append(Paragraph(f"Total: <b>{len(table_data) - 1}</b> professeurs", styles['Normal']))
    
    # Build PDF
    doc.build(elements)
    pdf_buffer.seek(0)
    
    response = HttpResponse(pdf_buffer.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="teachers_list_{timezone.now().strftime("%Y%m%d")}.pdf"'
    return response

@require_POST
def session_quick_status_update(request, session_id):
    """
    Quick update session status via AJAX.
    Used for marking sessions as done/cancelled from schedule view.
    Logs unhandled change to SessionChangeHistory.
    """
    session = get_object_or_404(Session, id=session_id)
    new_status = request.POST.get('status')
    
    if new_status not in ['PLANNED', 'DONE', 'CANCELLED']:
        return JsonResponse({'success': False, 'error': 'Statut invalide.'}, status=400)
    
    prev_status = session.status
    session.status = new_status
    session.is_manually_edited = True
    session.save()

    if prev_status != new_status:
        from core.services.scheduling.audit import AuditService
        AuditService.log_change(
            session=session,
            user=request.user if request.user.is_authenticated else None,
            action='status_change',
            previous_values={'status': prev_status},
            new_values={'status': new_status},
            change_reason=f"Changement de statut rapide: {session.get_status_display()}",
            ip_address=request.META.get('REMOTE_ADDR'),
            is_handled=False
        )
    
    from core.services.scheduling import SchedulingFacade
    return JsonResponse({
        'success': True,
        'session_id': session.id,
        'new_status': new_status,
        'unhandled_count': SchedulingFacade.get_unhandled_count(),
        'message': f'Statut mis à jour: {session.get_status_display()}'
    })


def session_detail_ajax(request, session_id):
    """
    Get session details for modal display
    """
    from django.conf import settings
    session = get_object_or_404(
        Session.objects.select_related(
            'group',
            'group__teacher',
            'room',
            'substitute_teacher'
        ).prefetch_related(
            'group__students'
        ),
        id=session_id
    )
    
    # Get attendance if exists
    from .models import Attendance
    attendance = Attendance.objects.filter(
        course_group=session.group,
        date=session.date
    ).select_related('student')
    
    students = session.group.students.all()
    attendance_dict = {a.student_id: a.is_present for a in attendance}
    
    student_list = []
    for s in students:
        student_list.append({
            'id': s.id,
            'name': s.name,
            'matricule': s.matricule,
            'phone': s.phone,
            'parent_contact': s.parent_contact,
            'is_present': attendance_dict.get(s.id, None),
        })
    
    today = timezone.now().date()
    is_today = session.date == today
    is_past = session.date < today
    is_future = session.date >= today  # Today and future sessions can be modified

    substitute_teacher_id = session.substitute_teacher_id if session.substitute_teacher_id else None

    data = {
        'id': session.id,
        'group': {
            'id': session.group.id if session.group else None,
            'name': session.group.name if session.group else '',
            'subject': session.group.subject if session.group else '',
            'level': session.group.level.name if session.group and session.group.level else '',
            'level_id': session.group.level.id if session.group and session.group.level else None,
        },
        'date': session.date.strftime('%Y-%m-%d'),
        'start_time': session.start_time.strftime('%H:%M'),
        'end_time': session.end_time.strftime('%H:%M'),
        'duration': session.duration_hours(),
        'room': {
            'id': session.room.id,
            'name': session.room.name,
            'capacity': session.room.capacity,
        },
        'teacher': {
            'id': session.group.teacher.id,
            'name': session.group.teacher.name,
            'phone': session.group.teacher.phone,
        } if session.group and session.group.teacher else None,
        'substitute_teacher': {
            'id': session.substitute_teacher.id,
            'name': session.substitute_teacher.name,
        } if session.substitute_teacher else None,
        'substitute_teacher_id': substitute_teacher_id,
        'status': session.status,
        'status_display': session.get_status_display(),
        'students': student_list,
        'student_count': len(student_list),
        'notes': session.notes,
        'is_past': is_past,
        'is_today': is_today,
        'is_future': is_future,
        'is_editable': not is_past,
        'is_exceptional': session.is_exceptional,
        'exception_type': session.get_exception_type(),
        'default_schedule': {
            'start_time': session.get_default_schedule().start_time.strftime('%H:%M') if session.get_default_schedule() else None,
            'end_time': session.get_default_schedule().end_time.strftime('%H:%M') if session.get_default_schedule() else None,
            'room_name': session.get_default_schedule().room.name if session.get_default_schedule() else None,
        } if session.get_default_schedule() else None,
        'is_recurring': session.schedule_id is not None,
    }
    
    return JsonResponse(data)


@require_POST
def session_create_ajax(request):
    """
    AJAX POST endpoint to create a new session.
    """
    from datetime import datetime as dt
    from django.core.exceptions import ValidationError
    from core.services.scheduling.locking import LockingService
    from core.services.scheduling.audit import AuditService
    
    group_id = request.POST.get('group_id')
    date_str = request.POST.get('date')
    room_id = request.POST.get('room_id')
    start_time_str = request.POST.get('start_time')
    end_time_str = request.POST.get('end_time')
    substitute_teacher_id = request.POST.get('substitute_teacher_id')
    notes = request.POST.get('notes', '')
    
    if not (group_id and date_str and room_id and start_time_str and end_time_str):
        return JsonResponse({'success': False, 'error': 'Paramètres manquants.'}, status=400)
        
    try:
        group = get_object_or_404(CourseGroup, id=group_id)
        room = get_object_or_404(Room, id=room_id)
        
        date_obj = dt.strptime(date_str, '%Y-%m-%d').date()
        
        # Check lock
        LockingService.check_lock(date_obj)
        
        try:
            start_time = dt.strptime(start_time_str, '%H:%M:%S').time()
        except ValueError:
            start_time = dt.strptime(start_time_str, '%H:%M').time()
            
        try:
            end_time = dt.strptime(end_time_str, '%H:%M:%S').time()
        except ValueError:
            end_time = dt.strptime(end_time_str, '%H:%M').time()
        
        sub_teacher = None
        if substitute_teacher_id:
            sub_teacher = get_object_or_404(Teacher, id=substitute_teacher_id)
            
        session = Session(
            group=group,
            date=date_obj,
            start_time=start_time,
            end_time=end_time,
            room=room,
            status='PLANNED',
            notes=notes,
            is_manually_edited=True
        )
        if sub_teacher:
            session.substitute_teacher = sub_teacher
            
        session.full_clean()
        session.save()
        
        # Audit log creation as unhandled change
        AuditService.log_change(
            session=session,
            user=request.user if request.user.is_authenticated else None,
            action='create',
            previous_values={},
            new_values={
                'date': str(session.date),
                'start_time': session.start_time.strftime('%H:%M'),
                'end_time': session.end_time.strftime('%H:%M'),
                'room': session.room.name,
                'status': session.status
            },
            change_reason="Création manuelle via planning",
            ip_address=request.META.get('REMOTE_ADDR'),
            is_handled=False
        )
        
    except ValidationError as ve:
        error_msg = "; ".join(ve.messages) if hasattr(ve, 'messages') else str(ve)
        return JsonResponse({'success': False, 'error': error_msg}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
        
    from core.services.scheduling import SchedulingFacade
    return JsonResponse({
        'success': True,
        'session_id': session.id,
        'unhandled_count': SchedulingFacade.get_unhandled_count(),
        'message': 'Session créée avec succès.'
    })



@require_POST
def session_update_ajax(request, session_id):
    """
    AJAX POST endpoint to update session date, room, times, notes, or substitute teacher.
    Auto-saves immediately to DB, recording changes as unhandled for batch action handling.
    """
    from datetime import datetime as dt
    from django.core.exceptions import ValidationError
    from core.services.scheduling.locking import LockingService
    from core.services.scheduling.audit import AuditService
    from core.services.scheduling import SchedulingFacade
    
    session = get_object_or_404(Session, id=session_id)
    
    date_str = request.POST.get('date')
    room_id = request.POST.get('room_id')
    teacher_id = request.POST.get('teacher_id')
    start_time_str = request.POST.get('start_time')
    end_time_str = request.POST.get('end_time')
    notes = request.POST.get('notes')
    change_reason = request.POST.get('change_reason', 'Mise à jour rapide via planning')
    
    new_date = session.date
    if date_str:
        try:
            new_date = dt.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'success': False, 'error': 'Format de date invalide.'}, status=400)
            
    # Check locks
    try:
        LockingService.check_lock(session.date)
        if new_date != session.date:
            LockingService.check_lock(new_date)
    except ValidationError as ve:
        return JsonResponse({'success': False, 'error': str(ve)}, status=400)

    # Capture previous values for audit logging
    prev_vals = {
        'date': str(session.date),
        'start_time': session.start_time.strftime('%H:%M'),
        'end_time': session.end_time.strftime('%H:%M'),
        'room': session.room.name if session.room else '',
        'substitute_teacher': session.substitute_teacher.name if session.substitute_teacher else ''
    }

    if date_str:
        session.date = new_date
    if room_id:
        session.room_id = int(room_id)
        
    if teacher_id is not None:
        if teacher_id == "":
            session.substitute_teacher = None
        else:
            try:
                teacher_id_int = int(teacher_id)
                if session.group and session.group.teacher_id == teacher_id_int:
                    session.substitute_teacher = None
                else:
                    session.substitute_teacher_id = teacher_id_int
            except ValueError:
                pass
            
    if start_time_str:
        try:
            session.start_time = dt.strptime(start_time_str, '%H:%M').time()
        except ValueError:
            try:
                session.start_time = dt.strptime(start_time_str, '%H:%M:%S').time()
            except ValueError:
                return JsonResponse({'success': False, 'error': 'Format de début de session invalide.'}, status=400)
                
    if end_time_str:
        try:
            session.end_time = dt.strptime(end_time_str, '%H:%M').time()
        except ValueError:
            try:
                session.end_time = dt.strptime(end_time_str, '%H:%M:%S').time()
            except ValueError:
                return JsonResponse({'success': False, 'error': 'Format de fin de session invalide.'}, status=400)
                
    if notes is not None:
        session.notes = notes

    scope = request.POST.get('scope', 'only_this')
    if scope != 'only_this':
        updates = {}
        if date_str:
            updates['date'] = new_date
        if room_id:
            updates['room_id'] = int(room_id)
        if start_time_str:
            updates['start_time'] = session.start_time
        if end_time_str:
            updates['end_time'] = session.end_time
        if teacher_id is not None:
            if teacher_id == "":
                updates['substitute_teacher'] = None
            else:
                try:
                    teacher_id_int = int(teacher_id)
                    if session.group and session.group.teacher_id == teacher_id_int:
                        updates['substitute_teacher'] = None
                    else:
                        updates['substitute_teacher_id'] = teacher_id_int
                except ValueError:
                    pass
        if notes is not None:
            updates['notes'] = notes
            
        try:
            propagated = SchedulingFacade.propagate_session_changes(
                session=session,
                scope=scope,
                updates=updates,
                user=request.user if request.user.is_authenticated else None,
                ip_address=request.META.get('REMOTE_ADDR'),
                change_reason=change_reason
            )
            
            return JsonResponse({
                'success': True,
                'message': f"Modifications auto-enregistrées sur {len(propagated)} séance(s).",
                'propagated_count': len(propagated),
                'unhandled_count': SchedulingFacade.get_unhandled_count(),
                'room_name': session.room.name if session.room else ''
            })
        except ValidationError as ve:
            error_msg = "; ".join(ve.messages) if hasattr(ve, 'messages') else str(ve)
            return JsonResponse({'success': False, 'error': error_msg}, status=400)
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
        
    try:
        session.is_manually_edited = True
        session.full_clean()
        session.save()
        
        # Compare and log changes as unhandled
        new_vals = {
            'date': str(session.date),
            'start_time': session.start_time.strftime('%H:%M'),
            'end_time': session.end_time.strftime('%H:%M'),
            'room': session.room.name if session.room else '',
            'substitute_teacher': session.substitute_teacher.name if session.substitute_teacher else ''
        }
        
        changed_prev = {}
        changed_new = {}
        for k, v in new_vals.items():
            if prev_vals[k] != v:
                changed_prev[k] = prev_vals[k]
                changed_new[k] = v

        if changed_prev or changed_new:
            AuditService.log_change(
                session=session,
                user=request.user if request.user.is_authenticated else None,
                action='manual_override',
                previous_values=changed_prev,
                new_values=changed_new,
                change_reason=change_reason,
                ip_address=request.META.get('REMOTE_ADDR'),
                is_handled=False
            )
            
        return JsonResponse({
            'success': True,
            'message': 'Séance enregistrée (en attente de traitement).',
            'session_id': session.id,
            'date': session.date.strftime('%Y-%m-%d'),
            'start_time': session.start_time.strftime('%H:%M'),
            'end_time': session.end_time.strftime('%H:%M'),
            'room_id': session.room_id,
            'room_name': session.room.name if session.room else '',
            'substitute_teacher_id': session.substitute_teacher_id,
            'unhandled_count': SchedulingFacade.get_unhandled_count(),
        })
            
    except ValidationError as ve:
        error_msg = "; ".join(ve.messages) if hasattr(ve, 'messages') else str(ve)
        return JsonResponse({'success': False, 'error': error_msg}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def whatsapp_schedule_notifications(request):
    """
    Dedicated page for managing and dispatching WhatsApp notifications
    for scheduling changes. Displays pending unhandled changes, summary stats,
    recent handled history, and exposes batch/individual send actions.
    """
    from core.services.scheduling.audit import AuditService
    from core.services.scheduling.notifications import NotificationService
    from core.models import SessionChangeHistory
    from django.utils import timezone as tz
    from core.utils import WhatsAppServiceAPI

    # WhatsApp status check
    try:
        status_data = WhatsAppServiceAPI.get_status()
        wa_ready = not status_data.get('offline') and status_data.get('status') == 'READY'
    except Exception:
        wa_ready = False

    # Unhandled changes stats
    unhandled_qs = AuditService.get_unhandled_changes()
    unhandled_count = unhandled_qs.count()

    # Count distinct students and teachers affected
    students_affected = 0
    teachers_affected = set()
    for h in unhandled_qs.select_related('session__group__teacher', 'session__substitute_teacher').prefetch_related('session__group__students'):
        s = h.session
        if s and s.group:
            students_affected += s.group.students.filter(is_active=True).count()
            if s.group.teacher_id:
                teachers_affected.add(s.group.teacher_id)
        if s and s.substitute_teacher_id:
            teachers_affected.add(s.substitute_teacher_id)

    # Handled today count
    today = tz.localdate()
    handled_today = SessionChangeHistory.objects.filter(
        is_handled=True,
        handled_at__date=today
    ).count()

    # Recent handled history (last 50)
    recent_handled = SessionChangeHistory.objects.filter(
        is_handled=True
    ).select_related('session__group', 'session', 'user').order_by('-handled_at')[:50]

    return render(request, 'core/whatsapp_schedule_notifications.html', {
        'status_data': status_data,
        'wa_ready': wa_ready,
        'unhandled_count': unhandled_count,
        'students_affected': students_affected,
        'teachers_affected': len(teachers_affected),
        'handled_today': handled_today,
        'recent_handled': recent_handled,
        'filter_date_start': request.GET.get('date_start', ''),
        'filter_date_end': request.GET.get('date_end', ''),
    })


@login_required
@require_GET
def schedule_unhandled_changes_ajax(request):
    """
    AJAX GET endpoint returning all unhandled session changes with metadata, diffs, and recipients.
    """
    from core.services.scheduling import SchedulingFacade
    from core.services.scheduling.notifications import NotificationService
    from core.utils import WhatsAppUtils

    date_start_str = request.GET.get('date_start')
    date_end_str = request.GET.get('date_end')
    session_id_str = request.GET.get('session_id')

    date_start = None
    date_end = None
    if date_start_str and date_end_str:
        try:
            from datetime import datetime as dt
            date_start = dt.strptime(date_start_str, '%Y-%m-%d').date()
            date_end = dt.strptime(date_end_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    session_id = int(session_id_str) if session_id_str and session_id_str.isdigit() else None

    unhandled_qs = SchedulingFacade.get_unhandled_changes(date_start=date_start, date_end=date_end, session_id=session_id)
    
    changes_data = []
    total_students_affected = 0
    total_teachers_affected = set()

    for h in unhandled_qs:
        s = h.session
        diffs = NotificationService.format_history_diff(h)
        group_name = s.group.name if s and s.group else "Séance sans groupe"
        subject = s.group.subject if s and s.group else ""
        teacher_name = s.substitute_teacher.name if s and s.substitute_teacher else (s.group.teacher.name if s and s.group and s.group.teacher else "Non assigné")
        teacher_phone = s.substitute_teacher.phone if s and s.substitute_teacher and s.substitute_teacher.phone else (s.group.teacher.phone if s and s.group and s.group.teacher and s.group.teacher.phone else '')
        room_name = s.room.name if s and s.room else "Non assignée"
        date_display = s.date.strftime('%d/%m/%Y') if s and s.date else "—"
        time_display = f"{s.start_time.strftime('%H:%M')} - {s.end_time.strftime('%H:%M')}" if s and s.start_time and s.end_time else "—"
        students_count = s.group.students.filter(is_active=True).count() if s and s.group else 0

        if s and s.group and s.group.teacher:
            total_teachers_affected.add(s.group.teacher_id)
        if s and s.substitute_teacher:
            total_teachers_affected.add(s.substitute_teacher_id)
        total_students_affected += students_count

        diffs_text = "\n• ".join(diffs) if diffs else "Modification de planning"
        reason_text = f"\n\n*Motif :* {h.change_reason}" if h.change_reason else ""

        teacher_msg = f"📢 *Notification de cours — {group_name}*\n\nBonjour {teacher_name},\nVotre cours du {date_display} a été modifié :\n• {diffs_text}{reason_text}\n\nCordialement,\nLa Direction."
        teacher_link = WhatsAppUtils.generate_chat_link(teacher_phone, teacher_msg) if teacher_phone else ""

        recipients = []
        if teacher_phone:
            recipients.append({
                'type': 'teacher',
                'name': teacher_name,
                'label': 'Professeur',
                'phone': teacher_phone,
                'message': teacher_msg,
                'whatsapp_link': teacher_link,
            })

        if s and s.group:
            for st in s.group.students.filter(is_active=True):
                st_phone = st.parent_contact or st.parent_contact_2 or st.phone
                if not st_phone:
                    continue
                p_name = st.parent_name or st.name
                st_msg = f"📢 *Information Planning — {group_name}*\n\nBonjour {p_name},\nLa séance de votre cours du {date_display} pour {st.name} a été modifiée :\n• {diffs_text}{reason_text}\n\nMerci de prendre note de ce changement.\nLa Direction."
                st_link = WhatsAppUtils.generate_chat_link(st_phone, st_msg)
                recipients.append({
                    'type': 'student',
                    'student_id': st.id,
                    'student_name': st.name,
                    'name': p_name,
                    'label': 'Parent / Élève',
                    'phone': st_phone,
                    'message': st_msg,
                    'whatsapp_link': st_link,
                })

        changes_data.append({
            'id': h.id,
            'session_id': s.id if s else None,
            'action': h.action,
            'group_name': group_name,
            'subject': subject,
            'teacher_name': teacher_name,
            'teacher_phone': teacher_phone,
            'room_name': room_name,
            'date': date_display,
            'time': time_display,
            'diffs': diffs,
            'change_reason': h.change_reason or '',
            'user': h.user.username if h.user else 'Système',
            'timestamp': h.timestamp.strftime('%d/%m/%Y %H:%M'),
            'students_count': students_count,
            'status': s.status if s else 'PLANNED',
            'teacher_message': teacher_msg,
            'teacher_whatsapp_link': teacher_link,
            'recipients': recipients,
            'recipients_count': len(recipients),
        })

    return JsonResponse({
        'success': True,
        'count': len(changes_data),
        'changes': changes_data,
        'summary': {
            'total_changes': len(changes_data),
            'students_affected': total_students_affected,
            'teachers_affected': len(total_teachers_affected)
        }
    })


@login_required
@require_POST
def schedule_handle_changes_ajax(request):
    """
    AJAX POST endpoint to handle/resolve saved changes.
    Supports:
      - action = 'send_all' : process all unhandled changes and notify
      - action = 'send_selected' : process specific history_ids and notify
      - action = 'mark_handled_silent' : mark all or selected as handled without notifications
    """
    from core.services.scheduling import SchedulingFacade
    from core.services.scheduling.audit import AuditService

    action = request.POST.get('action', 'send_all')
    raw_ids = request.POST.get('history_ids', '')
    history_ids = []
    if raw_ids:
        try:
            history_ids = [int(i.strip()) for i in raw_ids.split(',') if i.strip().isdigit()]
        except Exception:
            pass

    notify_teachers = request.POST.get('notify_teachers', '1') in ['1', 'true', 'True', 'on']
    notify_students = request.POST.get('notify_students', '1') in ['1', 'true', 'True', 'on']

    if action == 'send_all':
        result = SchedulingFacade.handle_changes(
            handle_all=True,
            send_notifications=True,
            notify_teachers=notify_teachers,
            notify_students=notify_students,
            user=request.user
        )
    elif action == 'send_selected':
        if not history_ids:
            return JsonResponse({'success': False, 'error': 'Veuillez sélectionner au moins une modification.'}, status=400)
        result = SchedulingFacade.handle_changes(
            history_ids=history_ids,
            handle_all=False,
            send_notifications=True,
            notify_teachers=notify_teachers,
            notify_students=notify_students,
            user=request.user
        )
    elif action == 'mark_handled_silent':
        handle_all = not bool(history_ids)
        result = SchedulingFacade.handle_changes(
            history_ids=history_ids if not handle_all else None,
            handle_all=handle_all,
            send_notifications=False,
            user=request.user
        )
    else:
        return JsonResponse({'success': False, 'error': f"Action inconnue '{action}'."}, status=400)

    result['success'] = True
    result['unhandled_count'] = AuditService.get_unhandled_count()
    return JsonResponse(result)



@require_http_methods(['GET', 'POST'])
def session_generate_bulk(request):
    """On-demand generate/update sessions for a date range with preview diff support."""
    from datetime import timedelta
    from core.services.scheduling import SchedulingFacade
    
    summary = None
    preview_diff = None
    errors = []
    weeks = 4
    force = False
    
    if request.method == 'POST':
        try:
            weeks = int(request.POST.get('weeks', 4))
        except (ValueError, TypeError):
            weeks = 4
        force = request.POST.get('force') == 'on'
        confirm_save = request.POST.get('confirm_save') == 'on'
        
        today = timezone.now().date()
        start_date = today
        end_date = today + timedelta(weeks=weeks)
        
        try:
            if confirm_save:
                # Atomically execute generation
                summary = SchedulingFacade.execute_regeneration(
                    start_date=start_date,
                    end_date=end_date,
                    force=force,
                    user=request.user,
                    ip_address=request.META.get('REMOTE_ADDR')
                )
            else:
                # Generate read-only preview diff
                preview_diff = SchedulingFacade.preview_regeneration(
                    start_date=start_date,
                    end_date=end_date,
                    force=force
                )
        except Exception as e:
            errors.append(str(e))
            
    return render(request, 'core/session_generate.html', {
        'summary': summary,
        'preview_diff': preview_diff,
        'errors': errors,
        'weeks': weeks,
        'force': force,
    })



# =====================
# STUDENT CRUD VIEWS
# =====================

def student_create(request):
    if request.method == 'POST':
        form = StudentForm(request.POST)
        if form.is_valid():
            student = form.save()

            messages.success(
                request,
                f'Élève {student.name} créé avec succès!'
            )

            if form.cleaned_data["create_payment"]:
                return redirect(
                    f"{reverse('core:payment_create')}?student_id={student.id}"
                )

            return redirect('core:student_page', student_id=student.id)

    else:
        form = StudentForm()

    return render(request, 'core/student_form.html', {
        'form': form,
        'title': 'Ajouter un nouvel élève',
        'button_text': 'Créer élève'
    })


def student_edit(request, student_id):
    """Edit an existing student"""
    student = get_object_or_404(Student, pk=student_id)
    
    if request.method == 'POST':
        form = StudentForm(request.POST, instance=student)
        if form.is_valid():
            form.save()
            messages.success(request, f'Élève {student.name} mise à jour avec succès!')
            return redirect('core:student_page', student_id=student.id)
    else:
        form = StudentForm(instance=student)
    
    return render(request, 'core/student_form.html', {
        'form': form,
        'student': student,
        'title': f'Modifier - {student.name}',
        'button_text': 'Mettre à jour'
    })


@require_POST
def student_delete(request, student_id):
    """Delete a student"""
    student = get_object_or_404(Student, pk=student_id)
    student_name = student.name
    student.delete()
    messages.success(request, f'Élève {student_name} supprimé avec succès!')
    return redirect('core:students_list')


def student_delete_confirm(request, student_id):
    """Confirmation page before deleting a student"""
    student = get_object_or_404(Student, pk=student_id)
    
    # Get student's enrollments and related payments
    enrollments = student.enrollment_set.all()
    payments = student.payments.all()
    
    return render(request, 'core/student_delete_confirm.html', {
        'student': student,
        'enrollments': enrollments,
        'payment_count': payments.count(),
    })


@require_POST
def enrollment_add(request, student_id):
    """Add an enrollment for a student"""
    student = get_object_or_404(Student, pk=student_id)
    course_group_id = request.POST.get('course_group_id')
    next_url = request.POST.get('next')
    
    if not course_group_id:
        messages.error(request, 'Veuillez sélectionner un groupe de cours')
        if next_url:
            return redirect(next_url)
        return redirect('core:student_page', student_id=student_id)
    
    course_group = get_object_or_404(CourseGroup, pk=course_group_id)
    
    # Check if already enrolled
    if student.enrollment_set.filter(course_group=course_group).exists():
        messages.warning(request, f'{student.name} est déjà inscrit à {course_group.name}')
        if next_url:
            return redirect(next_url)
        return redirect('core:student_page', student_id=student_id)
    
    enrollment = Enrollment.objects.create(
        student=student,
        course_group=course_group,
        is_active=True
    )
    
    messages.success(request, f'Inscription de {student.name} à {course_group.name} ajoutée !')
    if next_url:
        return redirect(next_url)
    return redirect('core:student_page', student_id=student_id)


@require_POST
def enrollment_remove(request, enrollment_id):
    """Remove an enrollment (AJAX endpoint)"""
    enrollment = get_object_or_404(Enrollment, id=enrollment_id)
    student = enrollment.student
    course_name = enrollment.course_group.name
    
    # Store info before deletion
    student_id = student.id
    
    # Delete the enrollment
    enrollment.delete()
    
    # Return JSON response for AJAX
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'message': f'L\'inscription au groupe "{course_name}" a été retirée avec succès.',
            'student_id': student_id,
            'new_total': float(student.total_monthly_fees())
        })
    
    # Fallback for non-AJAX requests
    messages.success(request, f'L\'inscription au groupe "{course_name}" a été retirée avec succès.')
    return redirect('core:student_page', student_id=student_id)

###############################  WHATSAPP INTEGRATION  #######################################

@require_GET
def whatsapp_payment_reminders(request):
    """Generate WhatsApp links for payment reminders to unpaid students"""
    from django.utils import timezone
    from dateutil.relativedelta import relativedelta

    # Month selector — allow choosing a past or current month
    month_param = request.GET.get('month')
    if month_param:
        try:
            current_month = datetime.strptime(month_param, '%Y-%m').date().replace(day=1)
        except ValueError:
            current_month = timezone.now().date().replace(day=1)
    else:
        current_month = timezone.now().date().replace(day=1)

    # Build months choices (last 6 months + current)
    today = timezone.now().date()
    months_choices = []
    for i in range(-5, 1):
        m = today + relativedelta(months=i)
        months_choices.append(m.replace(day=1))

    # Get all active students
    students = Student.objects.filter(is_active=True)
    
    # Build list of unpaid students with WhatsApp links
    unpaid_contacts = []
    
    for student in students:
        required = calculate_student_monthly_total(student)
        paid = Payment.objects.filter(
            student=student,
            month_covered=current_month,
            status='PAID'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        
        due_amount = required - paid
        
        if due_amount > 0 and (student.parent_contact or student.parent_contact_2):
            # Generate personalized message using French month name
            from .utils import month_name_fr
            month_fr = f"{month_name_fr(current_month.month)} {current_month.year}"
            template = WhatsAppMessageTemplates.CUSTOMER_SERVICE['payment_reminder']
            parent_name = student.parent_name or 'Parent'
            message = WhatsAppUtils.create_template_message(
                template,
                {
                    'name': parent_name,
                    'amount': f"{due_amount} DH",
                    'invoice_id': month_fr,
                }
            )

            # Build one entry per available phone number
            phones = [p for p in [student.parent_contact, student.parent_contact_2] if p]
            for idx, phone in enumerate(phones):
                contact = {
                    'phone': phone,
                    'phone_label': f'Parent {idx + 1}' if len(phones) > 1 else 'Parent',
                    'name': parent_name,
                    'student_name': student.name,
                    'amount': str(due_amount),
                    'currency': 'DH',
                    'month': current_month.strftime('%B %Y'),
                    'whatsapp_link': WhatsAppUtils.generate_chat_link(phone, message),
                    'message': message,
                    'student': student,
                    'due_amount': due_amount,
                }
                unpaid_contacts.append(contact)
    
    status_data = WhatsAppServiceAPI.get_status()
    
    context = {
        'unpaid_contacts': unpaid_contacts,
        'total_unpaid': len(unpaid_contacts),
        'current_month': current_month,
        'months_choices': months_choices,
        'status_data': status_data,
    }
    
    return render(request, 'core/whatsapp_payment_reminders.html', context)


@require_GET
def whatsapp_absence_notifications(request):
    """Generate WhatsApp links to notify parents of student absences"""

    # Day-of-week mapping (Python weekday() -> CourseGroupSchedule.day code)
    WEEKDAY_TO_CODE = {0: 'MON', 1: 'TUE', 2: 'WED', 3: 'THU', 4: 'FRI', 5: 'SAT', 6: 'SUN'}

    # Get date parameter (default to today)
    date_param = request.GET.get('date')
    if date_param:
        try:
            target_date = datetime.strptime(date_param, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            target_date = timezone.now().date()
    else:
        target_date = timezone.now().date()

    day_code = WEEKDAY_TO_CODE[target_date.weekday()]

    # Get all absence records for the date, prefetching schedules to avoid N+1
    absences = Attendance.objects.filter(
        date=target_date,
        is_present=False
    ).select_related(
        'student',
        'course_group',
        'course_group__teacher',
    ).prefetch_related(
        'course_group__schedules__room'
    )

    # Build notification contacts (deduplicated per student and course)
    absence_contacts = []
    seen_student_courses = set()

    for absence in absences:
        student = absence.student
        course = absence.course_group

        if not student or not course:
            continue

        dedup_key = (student.id, course.id)
        if dedup_key in seen_student_courses:
            continue
        seen_student_courses.add(dedup_key)

        primary_phone = student.parent_contact or student.parent_contact_2 or student.phone
        if not primary_phone:
            continue

        # Find the schedule slot that matches the absence date's weekday
        matching_schedule = next(
            (s for s in course.schedules.all() if s.day == day_code),
            None
        )

        if matching_schedule:
            time_str = f"{matching_schedule.start_time.strftime('%H:%M')} - {matching_schedule.end_time.strftime('%H:%M')}"
            room_str = matching_schedule.room.name if matching_schedule.room else ''
        else:
            slots = course.schedules.all()
            if slots:
                s = slots[0]
                time_str = f"{s.start_time.strftime('%H:%M')} - {s.end_time.strftime('%H:%M')}"
                room_str = s.room.name if s.room else ''
            else:
                time_str = ''
                room_str = ''

        parent_name = student.parent_name or 'Parent'
        time_info = f" 🕒 prévu à {time_str}" if time_str else ""
        date_str = target_date.strftime('%d/%m/%Y')

        # Generate personalised absence message
        default_absence_template = (
            "Bonjour {name} 👋,\n\n"
            "📢 Nous vous informons que {student_name} n'a pas assisté au cours de {course_name}{time_info} le 📅 {date}.\n\n"
            "ℹ️ Si cette absence est due à une raison particulière ou si vous souhaitez obtenir "
            "plus d'informations, n'hésitez pas à nous contacter.\n\n"
            "🤝 Merci de votre confiance.\n\n"
            "Cordialement,\n"
            "🎓 L'équipe pédagogique"
        )
        template_str = load_message_template('whatsapp_absence_notification.txt', default_absence_template)
        message = template_str.format_map(SafeDict({
            'name': parent_name,
            'student_name': student.name,
            'course_name': course.name,
            'time_info': time_info,
            'date': date_str,
        }))

        whatsapp_link = WhatsAppUtils.generate_chat_link(primary_phone, message)
        contact = {
            'phone': primary_phone,
            'phone_label': 'Parent',
            'secondary_phone': student.parent_contact_2 if student.parent_contact_2 and student.parent_contact_2 != primary_phone else None,
            'name': parent_name,
            'student_name': student.name,
            'course_name': course.name,
            'date': date_str,
            'time': time_str,
            'room': room_str,
            'teacher': course.teacher.name if course.teacher else '',
            'schedule': matching_schedule,
            'whatsapp_link': whatsapp_link,
            'message': message,
            'student': student,
            'absence': absence,
        }
        absence_contacts.append(contact)

    status_data = WhatsAppServiceAPI.get_status()

    context = {
        'absence_contacts': absence_contacts,
        'total_absences': len(absence_contacts),
        'target_date': target_date,
        'status_data': status_data,
    }

    return render(request, 'core/whatsapp_absence_notifications.html', context)



@require_http_methods(["GET", "POST"])
def whatsapp_bulk_announcements(request):
    """
    Advanced bulk WhatsApp announcements with multi-audience targeting,
    rich categorized templates, dynamic variable tags, and attachments.
    """
    school_name = getattr(settings, 'SCHOOL_NAME', 'Établissement')
    today_str = timezone.now().strftime('%d/%m/%Y')
    status_data = WhatsAppServiceAPI.get_status()

    # Query all necessary master data
    levels = Level.objects.all().select_related('category').order_by('category__name', 'name')
    course_groups = CourseGroup.objects.filter(is_active=True).select_related('teacher', 'level').order_by('name')
    teachers = Teacher.objects.filter(is_active=True).prefetch_related('course_groups').order_by('name')
    all_active_students = Student.objects.filter(is_active=True).select_related('level').prefetch_related('enrollment_set__course_group').order_by('name')

    # Groups with active WhatsApp invite link
    groups_with_link = CourseGroup.objects.filter(
        is_active=True,
        whatsapp_group_link__isnull=False
    ).exclude(whatsapp_group_link='').select_related('teacher', 'level').order_by('name')

    # Templates catalog
    templates_catalog = {
        'pedagogique': {
            'label': '🎓 Pédagogie & Examens',
            'templates': [
                {
                    'id': 'controle_continu',
                    'title': 'Contrôle Continu',
                    'badge': 'Contrôle',
                    'text': "Bonjour {name},\n\nNous vous informons qu'un contrôle continu pour le cours de {groups} est prévu le [DATE] pour l'élève {student_name}.\n\nMerci de veiller à une bonne préparation.\nCordialement,\n{school_name}"
                },
                {
                    'id': 'examens_blancs',
                    'title': 'Examens Blancs',
                    'badge': 'Examens',
                    'text': "Bonjour {name},\n\nLes examens blancs pour le niveau {level} débuteront le [DATE DÉBUT] et se poursuivront jusqu'au [DATE FIN].\n\nLe planning détaillé a été transmis à {student_name}.\nNous leur souhaitons plein succès !\n{school_name}"
                },
                {
                    'id': 'bulletins',
                    'title': 'Remise des Bulletins',
                    'badge': 'Bulletins',
                    'text': "Bonjour {name},\n\nLes bulletins de notes de la période pour {student_name} ({level}) sont prêts et disponibles auprès de la direction.\n\nCordialement,\n{school_name}"
                },
                {
                    'id': 'devoirs',
                    'title': 'Devoirs & Travail à faire',
                    'badge': 'Devoirs',
                    'text': "Bonjour {name},\n\nUn devoir maison important a été assigné pour le cours de {groups} à rendre au plus tard le [DATE]. Merci de vérifier l'avancement de {student_name}.\n\nCordialement,\n{school_name}"
                },
            ]
        },
        'evenements': {
            'label': '📅 Événements & Réunions',
            'templates': [
                {
                    'id': 'reunion_parents',
                    'title': 'Réunion Parents-Professeurs',
                    'badge': 'Réunion',
                    'text': "Bonjour {name},\n\nNous vous convions à la réunion parents-professeurs le [DATE] à partir de [HEURE] afin d'échanger sur les progrès et le suivi de {student_name} ({level}).\n\nVotre présence est vivement encouragée.\n{school_name}"
                },
                {
                    'id': 'portes_ouvertes',
                    'title': 'Journée Portes Ouvertes',
                    'badge': 'Portes Ouvertes',
                    'text': "Bonjour {name},\n\n{school_name} a le plaisir de vous inviter à sa Journée Portes Ouvertes & Orientation le [DATE] de [HEURE DÉBUT] à [HEURE FIN].\n\nVenez découvrir nos méthodes et nos programmes !\n{school_name}"
                },
                {
                    'id': 'atelier_orientation',
                    'title': 'Atelier Orientation & Concours',
                    'badge': 'Atelier',
                    'text': "Bonjour {name},\n\nUn atelier de préparation et d'orientation vers les grandes écoles est organisé le [DATE] pour les élèves de {level}.\n\n{student_name} y est chaleureusement invité(e).\nCordialement,\n{school_name}"
                },
            ]
        },
        'administratif': {
            'label': '🏛️ Administratif & Horaires',
            'templates': [
                {
                    'id': 'vacances',
                    'title': 'Vacances Scolaires',
                    'badge': 'Vacances',
                    'text': "Bonjour {name},\n\nNous vous informons que les vacances scolaires débuteront le [DATE DÉBUT] après les cours. La reprise officielle des cours aura lieu le [DATE REPRISE].\n\nExcellentes vacances à {student_name} !\n{school_name}"
                },
                {
                    'id': 'fermeture',
                    'title': 'Fermeture Exceptionnelle',
                    'badge': 'Fermeture',
                    'text': "Bonjour {name},\n\nL'établissement sera exceptionnellement fermé le [DATE]. Les cours reprendront selon les horaires normaux le [DATE REPRISE].\n\nMerci pour votre compréhension.\nLa direction de {school_name}"
                },
                {
                    'id': 'horaires_ramadan',
                    'title': 'Aménagement Horaires (Ramadan)',
                    'badge': 'Horaires',
                    'text': "Bonjour {name},\n\nÀ l'occasion du mois sacré de Ramadan, les créneaux horaires des groupes ({groups}) sont réaménagés comme suit :\n[NOUVEAUX HORAIRES].\n\nRamadan Moubarak à vous et à vos proches !\n{school_name}"
                },
                {
                    'id': 'reprise_cours',
                    'title': 'Rappel de Reprise',
                    'badge': 'Reprise',
                    'text': "Bonjour {name},\n\nNous vous rappelons que la rentrée / reprise des cours pour {student_name} ({level}) aura lieu le [DATE] aux horaires habituels.\n\nBonne reprise à tous !\n{school_name}"
                },
            ]
        },
        'paiement': {
            'label': '💳 Règlements & Inscriptions',
            'templates': [
                {
                    'id': 'rappel_mensualite',
                    'title': 'Rappel Mensualité en attente',
                    'badge': 'Mensualité',
                    'text': "Bonjour {name},\n\nNous vous informons avec bienveillance que le règlement de la mensualité pour {student_name} ({level}) est actuellement en attente pour le mois en cours.\n\nMerci de vous rapprocher de l'administration pour régularisation.\nCordialement,\n{school_name}"
                },
                {
                    'id': 'reinscription',
                    'title': 'Campagne de Réinscription',
                    'badge': 'Réinscription',
                    'text': "Bonjour {name},\n\nLes réinscriptions pour la prochaine année scolaire sont ouvertes pour {student_name} ({level}). Le nombre de places par groupe étant limité, merci de confirmer l'inscription avant le [DATE LIMITE].\n\nCordialement,\n{school_name}"
                },
            ]
        },
        'urgence': {
            'label': '🚨 Alertes & Urgences',
            'templates': [
                {
                    'id': 'intemperies',
                    'title': 'Suspension des Cours (Météo / Urgence)',
                    'badge': 'Urgent',
                    'text': "⚠️ ALERTE / INFORMATION IMPORTANTE\n\nBonjour {name},\n\nEn raison de circonstances exceptionnelles / intempéries, les cours sont suspendus le [DATE].\n\nNous vous tiendrons informés de l'évolution de la situation.\nLa direction de {school_name}"
                },
                {
                    'id': 'report_seance',
                    'title': 'Report Imprévu de Séance',
                    'badge': 'Report',
                    'text': "⚠️ CHANGEMENT DE SÉANCE\n\nBonjour {name},\n\nLa séance de {groups} initialement programmée le [DATE] à [HEURE] pour {student_name} est reportée au [NOUVELLE DATE] à [NOUVELLE HEURE].\n\nMerci de votre compréhension,\n{school_name}"
                },
            ]
        },
        'enseignants': {
            'label': '👨‍🏫 Note aux Enseignants',
            'templates': [
                {
                    'id': 'reunion_pedagogique',
                    'title': 'Réunion Pédagogique',
                    'badge': 'Réunion Profs',
                    'text': "Bonjour cher(e) professeur {name},\n\nUne réunion de coordination pédagogique se tiendra le [DATE] à [HEURE] en salle des réunions.\n\nMerci pour votre engagement constant.\nLa direction de {school_name}"
                },
                {
                    'id': 'remise_notes',
                    'title': 'Dépôt des Notes & Feuilles de Présence',
                    'badge': 'Remise Notes',
                    'text': "Bonjour {name},\n\nNous vous prions de bien vouloir finaliser la transmission des notes et états de présence des groupes ({groups}) avant le [DATE LIMITE].\n\nMerci pour votre précieuse collaboration,\n{school_name}"
                },
                {
                    'id': 'conseil_classe',
                    'title': 'Conseil de Classe',
                    'badge': 'Conseil',
                    'text': "Bonjour {name},\n\nLe conseil de classe pour les niveaux ({level}) aura lieu le [DATE] à [HEURE]. Votre participation active est vivement appréciée.\n\nCordialement,\n{school_name}"
                },
            ]
        },
    }

    if request.method == 'POST':
        audience_type = request.POST.get('audience_type', 'all_parents_students')
        contact_channel = request.POST.get('contact_channel', 'all_available')
        level_ids = [int(x) for x in request.POST.getlist('level_ids') if x.isdigit()]
        group_ids = [int(x) for x in request.POST.getlist('group_ids') if x.isdigit()]
        selected_student_ids = [int(x) for x in request.POST.getlist('student_ids') if x.isdigit()]
        teacher_ids = [int(x) for x in request.POST.getlist('teacher_ids') if x.isdigit()]
        payment_filter = request.POST.get('payment_filter', 'all')
        message_template = request.POST.get('message_template', '').strip()

        # Handle uploaded attachments
        attachments = []
        uploaded_files = request.FILES.getlist('attachments')
        for f in uploaded_files:
            filename = f"{uuid.uuid4().hex}_{f.name}"
            save_path = f"whatsapp_attachments/{filename}"
            saved_path = default_storage.save(save_path, ContentFile(f.read()))
            file_url = default_storage.url(saved_path)
            attachments.append({
                'name': f.name,
                'url': file_url,
                'path': saved_path,
            })

        if not message_template and not attachments:
            messages.error(request, "Veuillez saisir un message ou joindre au moins un fichier.")
            return redirect('core:whatsapp_bulk_announcements')

        contacts = []
        seen_phones = set()
        if audience_type == 'custom':
            custom_phones = request.POST.get('custom_phones', '').strip()
            for line in custom_phones.splitlines():
                line = line.strip()
                if not line:
                    continue
                if ',' in line:
                    parts = [p.strip() for p in line.split(',', 1)]
                elif ';' in line:
                    parts = [p.strip() for p in line.split(';', 1)]
                elif '-' in line:
                    parts = [p.strip() for p in line.split('-', 1)]
                else:
                    parts = [line]
                
                phone = parts[0]
                name = parts[1] if len(parts) > 1 and parts[1] else 'Destinataire'
                p_clean = WhatsAppUtils.clean_phone_number(phone)
                if p_clean and p_clean not in seen_phones:
                    seen_phones.add(p_clean)
                    contacts.append({
                        'phone': phone,
                        'name': name,
                        'student_name': name,
                        'recipient_name': name,
                        'recipient_type': 'Contact Annonce / Pub',
                        'level': 'Contact Externe',
                        'groups': 'Annonce / Publicité',
                        'school_name': school_name,
                        'date': today_str,
                    })
        elif audience_type == 'teachers':
            teacher_qs = Teacher.objects.filter(is_active=True).prefetch_related('course_groups')
            if teacher_ids:
                teacher_qs = teacher_qs.filter(id__in=teacher_ids)

            for t in teacher_qs:
                if not t.phone:
                    continue
                p_clean = WhatsAppUtils.clean_phone_number(t.phone)
                if p_clean and p_clean not in seen_phones:
                    seen_phones.add(p_clean)
                    taught_groups = ", ".join([g.name for g in t.course_groups.filter(is_active=True)])
                    contacts.append({
                        'phone': t.phone,
                        'name': t.name,
                        'student_name': t.name,
                        'recipient_name': t.name,
                        'recipient_type': 'Enseignant',
                        'level': 'Corps Enseignant',
                        'groups': taught_groups or 'Aucun groupe assigné',
                        'school_name': school_name,
                        'date': today_str,
                    })
        else:
            students_qs = Student.objects.filter(is_active=True).select_related('level').prefetch_related('enrollment_set__course_group')

            if audience_type == 'by_level' and level_ids:
                students_qs = students_qs.filter(level_id__in=level_ids)
            elif audience_type == 'by_group' and group_ids:
                students_qs = students_qs.filter(enrollment__course_group_id__in=group_ids, enrollment__is_active=True).distinct()
            elif audience_type == 'by_student' and selected_student_ids:
                students_qs = students_qs.filter(id__in=selected_student_ids)

            # Payment filter
            if payment_filter in ['unpaid', 'paid']:
                current_month = timezone.now().date().replace(day=1)
                filtered_students = []
                for st in students_qs:
                    required = calculate_student_monthly_total(st)
                    paid = Payment.objects.filter(
                        student=st,
                        month_covered=current_month,
                        status='PAID'
                    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
                    is_unpaid = (required - paid) > 0
                    if payment_filter == 'unpaid' and is_unpaid:
                        filtered_students.append(st)
                    elif payment_filter == 'paid' and not is_unpaid:
                        filtered_students.append(st)
                students_qs = filtered_students

            for student in students_qs:
                parent_name = student.parent_name or 'Parent'
                level_name = student.level.name if student.level else ''
                group_names = ", ".join([e.course_group.name for e in student.enrollment_set.all() if e.is_active])

                # Channels determination
                include_p1 = False
                include_p2 = False
                include_student = False

                if audience_type == 'all_parents_students':
                    include_p1 = True
                    include_p2 = True
                    include_student = True
                elif audience_type == 'all_parents':
                    include_p1 = True
                    include_p2 = True
                elif audience_type == 'all_students':
                    include_student = True
                else:
                    if contact_channel in ['all_available', 'parents_and_students']:
                        include_p1 = True
                        include_p2 = True
                        include_student = True
                    elif contact_channel == 'parents_only':
                        include_p1 = True
                        include_p2 = True
                    elif contact_channel == 'parent_1_only':
                        include_p1 = True
                    elif contact_channel == 'parent_2_only':
                        include_p2 = True
                    elif contact_channel == 'student_only':
                        include_student = True

                if include_p1 and student.parent_contact:
                    p_clean = WhatsAppUtils.clean_phone_number(student.parent_contact)
                    if p_clean and p_clean not in seen_phones:
                        seen_phones.add(p_clean)
                        contacts.append({
                            'phone': student.parent_contact,
                            'name': parent_name,
                            'recipient_name': parent_name,
                            'recipient_type': 'Parent 1',
                            'student_name': student.name,
                            'level': level_name,
                            'groups': group_names,
                            'school_name': school_name,
                            'date': today_str,
                            'student_id': student.id,
                        })

                if include_p2 and student.parent_contact_2:
                    p_clean = WhatsAppUtils.clean_phone_number(student.parent_contact_2)
                    if p_clean and p_clean not in seen_phones:
                        seen_phones.add(p_clean)
                        contacts.append({
                            'phone': student.parent_contact_2,
                            'name': parent_name,
                            'recipient_name': f"{parent_name} (Contact 2)",
                            'recipient_type': 'Parent 2',
                            'student_name': student.name,
                            'level': level_name,
                            'groups': group_names,
                            'school_name': school_name,
                            'date': today_str,
                            'student_id': student.id,
                        })

                if include_student and student.phone:
                    p_clean = WhatsAppUtils.clean_phone_number(student.phone)
                    if p_clean and p_clean not in seen_phones:
                        seen_phones.add(p_clean)
                        contacts.append({
                            'phone': student.phone,
                            'name': student.name,
                            'recipient_name': student.name,
                            'recipient_type': 'Élève',
                            'student_name': student.name,
                            'level': level_name,
                            'groups': group_names,
                            'school_name': school_name,
                            'date': today_str,
                            'student_id': student.id,
                        })

        if not contacts:
            messages.warning(request, "Aucun destinataire correspondant aux critères sélectionnés n'a été trouvé.")
            return redirect('core:whatsapp_bulk_announcements')

        bulk_links = WhatsAppUtils.generate_bulk_links(
            contacts,
            message_template or ""
        )

        audience_labels = {
            'all_parents_students': 'Tous les parents et tous les élèves',
            'all_parents': 'Tous les parents d\'élèves',
            'all_students': 'Tous les élèves (numéros directs)',
            'by_level': 'Par Niveaux scolaires sélectionnés',
            'by_group': 'Par Groupes de cours sélectionnés',
            'by_student': 'Sélection personnalisée d\'élèves',
            'by_payment': 'Filtré par statut de paiement',
            'teachers': 'Corps enseignant (Professeurs)',
            'custom': 'Contacts personnalisés (Annonce / Publicité)',
        }

        context = {
            'bulk_links': bulk_links,
            'message_template': message_template,
            'total_contacts': len(bulk_links),
            'status_data': status_data,
            'attachments': attachments,
            'audience_type_label': audience_labels.get(audience_type, 'Audience personnalisée'),
        }

        return render(request, 'core/whatsapp_bulk_results.html', context)

    # Build JSON directory of students for instant frontend filtering and live counter
    students_json_list = []
    for st in all_active_students:
        students_json_list.append({
            'id': st.id,
            'name': st.name,
            'parent_name': st.parent_name or 'Parent',
            'has_p1': bool(st.parent_contact),
            'has_p2': bool(st.parent_contact_2),
            'has_st_phone': bool(st.phone),
            'level_id': st.level_id or 0,
            'level_name': st.level.name if st.level else 'Sans niveau',
            'group_ids': [e.course_group_id for e in st.enrollment_set.all() if e.is_active],
            'group_names': ", ".join([e.course_group.name for e in st.enrollment_set.all() if e.is_active]),
        })

    teachers_json_list = []
    for t in teachers:
        teachers_json_list.append({
            'id': t.id,
            'name': t.name,
            'phone': t.phone,
            'has_phone': bool(t.phone),
            'group_names': ", ".join([g.name for g in t.course_groups.filter(is_active=True)]),
        })

    # Default all contacts count
    initial_contacts_count = sum(
        bool(s.parent_contact) + bool(s.parent_contact_2) + bool(s.phone)
        for s in all_active_students
    )

    context = {
        'levels': levels,
        'course_groups': course_groups,
        'teachers': teachers,
        'all_active_students': all_active_students,
        'students_json': students_json_list,
        'teachers_json': teachers_json_list,
        'initial_contacts_count': initial_contacts_count,
        'total_students': all_active_students.count(),
        'total_teachers': teachers.count(),
        'groups_with_link': groups_with_link,
        'templates_catalog': templates_catalog,
        'status_data': status_data,
        'school_name': school_name,
        'today_date': today_str,
    }

    return render(request, 'core/whatsapp_bulk_announcements.html', context)


@require_GET
def whatsapp_payment_confirmation(request, payment_id):
    """Generate WhatsApp link to send payment confirmation"""
    
    payment = get_object_or_404(Payment, pk=payment_id)
    student = payment.student
    
    if not student.parent_contact and not student.parent_contact_2:
        messages.error(request, "Aucun numéro de téléphone disponible pour ce parent")
        return redirect('core:student_page', student_id=student.id)
    
    # Generate confirmation message
    default_confirmation_template = (
        "Bonjour {name},\n\n"
        "Nous confirmons la réception de votre paiement:\n\n"
        "Montant: {amount} DH\n"
        "Date: {date}\n"
        "Reçu N°: {receipt_number}\n"
        "Pour le mois de: {month}\n\n"
        "Merci pour votre confiance!\n\n"
        "Cordialement,\n"
        "L'équipe administrative"
    )
    template_str = load_message_template('whatsapp_payment_confirmation.txt', default_confirmation_template)
    message = template_str.format_map(SafeDict({
        'name': student.parent_name or 'Parent',
        'amount': str(payment.amount),
        'date': payment.payment_date.strftime('%d/%m/%Y'),
        'receipt_number': payment.receipt_number,
        'month': format_date_fr(payment.month_covered),
    }))
    
    # Generate WhatsApp link (primary contact)
    whatsapp_link = WhatsAppUtils.generate_chat_link(
        student.parent_contact or student.parent_contact_2,
        message
    )
    
    # Secondary contact link if available
    whatsapp_link_2 = None
    if student.parent_contact and student.parent_contact_2:
        whatsapp_link_2 = WhatsAppUtils.generate_chat_link(
            student.parent_contact_2,
            message
        )
    
    status_data = WhatsAppServiceAPI.get_status()
    
    enrolled_groups_with_links = [
        e.course_group for e in student.enrollment_set.filter(is_active=True).select_related('course_group')
        if e.course_group and e.course_group.whatsapp_group_link and e.course_group.whatsapp_group_link.strip()
    ]
    
    context = {
        'payment': payment,
        'student': student,
        'whatsapp_link': whatsapp_link,
        'whatsapp_link_2': whatsapp_link_2,
        'message': message,
        'status_data': status_data,
        'enrolled_groups_with_links': enrolled_groups_with_links,
    }
    
    return render(request, 'core/whatsapp_payment_confirmation.html', context)


@require_GET
def whatsapp_session_reminder(request, session_id):
    """Generate WhatsApp links to remind students about upcoming session"""
    
    session = get_object_or_404(
        Session.objects.select_related('group', 'group__teacher', 'schedule__room'),
        pk=session_id
    )
    
    students = session.group.students.filter(is_active=True)
    
    # Build reminder contacts
    reminder_contacts = []
    
    for student in students:
        phones = [p for p in [student.parent_contact, student.parent_contact_2] if p]
        if not phones:
            continue

        parent_name = student.parent_name or 'Parent'
        room_name = (session.schedule.room.name if session.schedule and session.schedule.room else 'N/A')

        # Use template — same message for both numbers
        template = WhatsAppMessageTemplates.EDUCATION['class_reminder']
        message = WhatsAppUtils.create_template_message(
            template,
            {
                'student_name': student.name,
                'subject': session.group.name,
                'date': f"{session.date.strftime('%d/%m/%Y')} à {session.start_time.strftime('%H:%M')}"
            }
        )

        for idx, phone in enumerate(phones):
            contact = {
                'phone': phone,
                'phone_label': f'Parent {idx + 1}' if len(phones) > 1 else 'Parent',
                'name': parent_name,
                'student_name': student.name,
                'course_name': session.group.name,
                'date': session.date.strftime('%d/%m/%Y'),
                'time': session.start_time.strftime('%H:%M'),
                'room': room_name,
                'whatsapp_link': WhatsAppUtils.generate_chat_link(phone, message),
                'message': message,
                'student': student,
            }
            reminder_contacts.append(contact)
    
    status_data = WhatsAppServiceAPI.get_status()
    
    context = {
        'session': session,
        'reminder_contacts': reminder_contacts,
        'total_students': len(reminder_contacts),
        'status_data': status_data,
    }
    
    return render(request, 'core/whatsapp_session_reminder.html', context)


@require_GET
def whatsapp_generate_link_ajax(request):
    """AJAX endpoint to generate a WhatsApp link on-demand"""
    
    phone = request.GET.get('phone')
    message = request.GET.get('message')
    use_web = request.GET.get('use_web', 'false') == 'true'
    
    if not phone:
        return JsonResponse({'error': 'Phone number required'}, status=400)
    
    try:
        whatsapp_link = WhatsAppUtils.generate_chat_link(
            phone,
            message,
            use_web
        )
        
        return JsonResponse({
            'success': True,
            'whatsapp_link': whatsapp_link,
            'phone': WhatsAppUtils.clean_phone_number(phone),
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@require_GET
def whatsapp_dashboard(request):
    """WhatsApp integration dashboard with connection status and session control"""
    from core.services.scheduling.audit import AuditService
    status_data = WhatsAppServiceAPI.get_status()
    
    # If request is AJAX or has ajax=1 query param, return status data as JSON
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('ajax') == '1':
        return JsonResponse(status_data)
        
    recent_logs = WhatsAppSendLog.objects.select_related('student').all()[:20]
    unhandled_changes_count = AuditService.get_unhandled_count()
    
    context = {
        'status_data': status_data,
        'recent_logs': recent_logs,
        'unhandled_changes_count': unhandled_changes_count,
    }
    return render(request, 'core/whatsapp_dashboard.html', context)


@require_POST
def whatsapp_send_ajax(request):
    """
    AJAX endpoint to send a WhatsApp message using the background service.
    Logs every attempt to WhatsAppSendLog.
    """
    phone = request.POST.get('phone')
    message = request.POST.get('message', '') or ''
    message_type = request.POST.get('message_type', 'other')
    raw_attachments = request.POST.get('attachments')
    attachments = []
    student_schedule = request.POST.get("student_schedule")
    week = request.POST.get("week")

    if not raw_attachments and request.content_type == 'application/json':
        try:
            body_data = json.loads(request.body.decode('utf-8') or '{}')
            raw_attachments = body_data.get('attachments')
            if not phone:
                phone = body_data.get('phone')
            if not message:
                message = body_data.get('message', '') or ''
            if message_type == 'other':
                message_type = body_data.get('message_type', 'other')
        except Exception:
            raw_attachments = raw_attachments or None

    if raw_attachments:
        try:
            attachments = json.loads(raw_attachments) if isinstance(raw_attachments, str) else raw_attachments
        except Exception:
            return JsonResponse({
                'success': False,
                'error': 'Données d\'attachment invalides.'
            }, status=400)

    if not phone:
        return JsonResponse({'success': False, 'error': 'Phone number is required.'}, status=400)

    if not message and not attachments:
        return JsonResponse({
            'success': False,
            'error': 'Please provide a message or at least one file attachment.'
        }, status=400)

    prepared_attachments = []
    for attachment in attachments:
        file_path = attachment.get('path')
        name = attachment.get('name')
        if not file_path or not name:
            continue

        if not default_storage.exists(file_path):
            return JsonResponse({
                'success': False,
                'error': f'Attachment file not found: {name}'
            }, status=400)

        try:
            with default_storage.open(file_path, 'rb') as fp:
                file_data = fp.read()
        except Exception:
            return JsonResponse({
                'success': False,
                'error': f'Unable to read attachment: {name}'
            }, status=400)

        mime_type, _ = mimetypes.guess_type(name)
        if not mime_type:
            mime_type = 'application/octet-stream'

        prepared_attachments.append({
            'name': name,
            'mime_type': mime_type,
            'data': base64.b64encode(file_data).decode('utf-8'),
        })


    if student_schedule:
        from datetime import datetime, timedelta
        from .utils import generate_student_schedule_pdf

        student = get_object_or_404(Student, pk=student_schedule)

        parsed = datetime.strptime(week, "%Y-%m-%d").date()
        week_start = parsed - timedelta(days=parsed.weekday())
        week_end = week_start + timedelta(days=6)

        enrollments = student.enrollment_set.filter(
            is_active=True
        ).values_list("course_group_id", flat=True)

        sessions = list(
            Session.objects.filter(
                date__range=[week_start, week_end],
                group_id__in=enrollments,
            )
            .select_related("group", "group__teacher", "room")
            .order_by("date", "start_time")
        )

        pdf_buf = generate_student_schedule_pdf(
            sessions,
            student_name=student.name,
            title=f"Planification — {student.name} — semaine {week_start:%d/%m/%Y}",
        )

        prepared_attachments.append({
            "name": f"schedule_{student.name}_{week_start:%Y%m%d}.pdf",
            "mime_type": "application/pdf",
            "data": base64.b64encode(pdf_buf.getvalue()).decode("utf-8"),
        })

    res = WhatsAppServiceAPI.send_message(
        phone,
        message,
        attachments=prepared_attachments or None
    )

    # Resolve student by phone for richer log
    from .utils import WhatsAppUtils
    cleaned = WhatsAppUtils.clean_phone_number(phone)
    student = (
        Student.objects.filter(parent_contact__icontains=phone).first()
        or Student.objects.filter(parent_contact__icontains=cleaned).first()
        or Student.objects.filter(parent_contact_2__icontains=phone).first()
        or Student.objects.filter(parent_contact_2__icontains=cleaned).first()
    )

    message_preview = message[:300]
    if not message_preview and prepared_attachments:
        attachment_names = [att.get('name') for att in prepared_attachments if att.get('name')]
        message_preview = 'Fichiers joints: ' + ', '.join(attachment_names)[:300]

    # Write log entry
    WhatsAppSendLog.objects.create(
        student=student,
        phone=phone,
        message_type=message_type,
        message_preview=message_preview,
        status='SENT' if res.get('success') else 'FAILED',
        error_message=res.get('error', '') if not res.get('success') else '',
    )

    if res.get('success'):
        history_id = request.POST.get('history_id')
        if history_id and history_id.isdigit():
            from core.models import SessionChangeHistory
            SessionChangeHistory.objects.filter(id=int(history_id)).update(
                is_handled=True,
                handled_at=timezone.now()
            )
        return JsonResponse({'success': True, 'message_id': res.get('messageId')})
    else:
        err = res.get('error', 'Erreur inconnue.')
        if 'not ready' in err.lower() or 'unavailable' in err.lower():
            err = "Le service WhatsApp n'est pas encore prêt. Veuillez patienter ou vérifier l'état du service."
        elif 'timed out in queue' in err.lower():
            err = "L'envoi a expiré dans la file d'attente (délai dépassé)."
        elif 'could not connect' in err.lower():
            err = "Impossible de joindre le service WhatsApp. Assurez-vous que le service en arrière-plan est actif."
        return JsonResponse({'success': False, 'error': err}, status=400)


@require_POST
def whatsapp_logout_ajax(request):
    """
    AJAX endpoint to logout the WhatsApp session.
    """
    res = WhatsAppServiceAPI.logout()
    if res.get('success'):
        return JsonResponse({'success': True})
    else:
        return JsonResponse({'success': False, 'error': res.get('error', 'Logout failed')}, status=400)


@require_POST
def whatsapp_restart_ajax(request):
    """
    AJAX endpoint to restart the WhatsApp client session.
    """
    res = WhatsAppServiceAPI.restart()
    if res.get('success'):
        return JsonResponse({'success': True, 'message': res.get('message', 'Restart initiated')})
    else:
        return JsonResponse({'success': False, 'error': res.get('error', 'Restart failed')}, status=400)


@require_POST
def whatsapp_check_number_ajax(request):
    """
    AJAX endpoint to check if a phone number is registered on WhatsApp.
    """
    phone = request.POST.get('phone', '').strip()
    if not phone:
        return JsonResponse({'success': False, 'error': 'Numéro de téléphone requis.'}, status=400)

    from .utils import WhatsAppServiceAPI
    res = WhatsAppServiceAPI.check_number(phone)
    return JsonResponse(res)


# ==============================================================================
# COURSE GROUP CRUD VIEWS
# ==============================================================================
from .forms import CourseGroupForm, CourseGroupScheduleFormSet

@require_http_methods(['GET', 'POST'])
def course_group_create(request):
    """Create a new course group (class)"""
    if request.method == 'POST':
        form = CourseGroupForm(request.POST)
        formset = CourseGroupScheduleFormSet(request.POST)
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                course = form.save()
                formset.instance = course
                formset.save()
            messages.success(request, f"Le groupe '{course.name}' a été créé avec succès.")
            return redirect('core:courses_list')
    else:
        form = CourseGroupForm()
        formset = CourseGroupScheduleFormSet()
    
    return render(request, 'core/course_group_form.html', {
        'form': form,
        'formset': formset,
        'title': 'Ajouter un groupe',
        'button_text': 'Créer le groupe'
    })


@require_http_methods(['GET', 'POST'])
def course_group_edit(request, group_id):
    """Edit an existing course group (class)"""
    course = get_object_or_404(CourseGroup, pk=group_id)
    if request.method == 'POST':
        form = CourseGroupForm(request.POST, instance=course)
        formset = CourseGroupScheduleFormSet(request.POST, instance=course)
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                form.save()
                formset.save()
            messages.success(request, f"Le groupe '{course.name}' a été mis à jour avec succès.")
            return redirect('core:courses_list')
    else:
        form = CourseGroupForm(instance=course)
        formset = CourseGroupScheduleFormSet(instance=course)
    
    return render(request, 'core/course_group_form.html', {
        'form': form,
        'formset': formset,
        'course': course,
        'title': f"Modifier le groupe : {course.name}",
        'button_text': 'Mettre à jour'
    })


@require_http_methods(['GET', 'POST'])
def course_group_delete_confirm(request, group_id):
    """Confirmation page before deleting a course group"""
    course = get_object_or_404(CourseGroup, pk=group_id)
    enrollment_count = course.enrollment_set.count()
    session_count = course.sessions.count()
    attendance_count = Attendance.objects.filter(course_group=course).count()
    
    return render(request, 'core/course_group_delete_confirm.html', {
        'course': course,
        'enrollment_count': enrollment_count,
        'session_count': session_count,
        'attendance_count': attendance_count,
    })


@require_POST
def course_group_delete(request, group_id):
    """Perform deletion of a course group"""
    course = get_object_or_404(CourseGroup, pk=group_id)
    name = course.name
    course.delete()
    messages.success(request, f"Le groupe '{name}' a été supprimé avec succès.")
    return redirect('core:courses_list')


from django.contrib.admin.views.decorators import staff_member_required

@staff_member_required
def admin_kpis_api(request):
    """
    API endpoint for admin dashboard KPI counts
    """
    students_count = Student.objects.filter(is_active=True).count()
    teachers_count = Teacher.objects.filter(is_active=True).count()
    groups_count = CourseGroup.objects.filter(is_active=True).count()
    payments_count = Payment.objects.count()
    sessions_count = Session.objects.count()
    rooms_count = Room.objects.filter(is_active=True).count()
    
    return JsonResponse({
        'students': students_count,
        'teachers': teachers_count,
        'groups': groups_count,
        'payments': payments_count,
        'sessions': sessions_count,
        'rooms': rooms_count,
    })


@staff_member_required
def admin_statistics(request):
    """
    Statistics page for admin: monthly revenue gains + room usage percentage.
    """
    from dateutil.relativedelta import relativedelta
    from .models import Room, Session, CourseGroupSchedule
    from .utils import month_name_fr

    today = timezone.now().date()

    # ── Monthly revenue (last 12 months) ──────────────────────────
    monthly_revenue = []
    for i in range(11, -1, -1):
        month_start = (today - relativedelta(months=i)).replace(day=1)
        month_end_rd = month_start + relativedelta(months=1)
        total = Payment.objects.filter(
            month_covered=month_start,
            status='PAID'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        monthly_revenue.append({
            'month_label': f"{month_name_fr(month_start.month)} {month_start.year}",
            'month_str': month_start.strftime('%Y-%m'),
            'revenue': float(total),
        })

    # ── Room usage percentage ─────────────────────────────────────
    # Total working hours per week (Mon–Sat, 08:00–22:00 = 14h/day × 6 days = 84h/week)
    WEEK_AVAILABLE_HOURS = Decimal('84')

    rooms = Room.objects.filter(is_active=True)
    room_stats = []
    for room in rooms:
        # Sum of scheduled weekly hours for this room (active groups)
        schedules = CourseGroupSchedule.objects.filter(
            room=room,
            course_group__is_active=True
        )
        weekly_hours = sum(
            (sch.duration_hours() for sch in schedules),
            0.0
        )
        pct = round(weekly_hours / float(WEEK_AVAILABLE_HOURS) * 100, 1)
        pct = min(pct, 100.0)  # cap at 100%
        # Count active groups using this room
        groups_count_room = CourseGroup.objects.filter(
            schedules__room=room,
            is_active=True
        ).distinct().count()
        room_stats.append({
            'name': room.name,
            'capacity': room.capacity,
            'weekly_hours': round(weekly_hours, 1),
            'usage_pct': pct,
            'groups_count': groups_count_room,
        })

    # Sort rooms by usage descending
    room_stats.sort(key=lambda x: x['usage_pct'], reverse=True)

    # ── Summary KPIs ─────────────────────────────────────────────
    current_month_start = today.replace(day=1)
    revenue_this_month = Payment.objects.filter(
        month_covered=current_month_start,
        status='PAID'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    prev_month_start = (today - relativedelta(months=1)).replace(day=1)
    revenue_prev_month = Payment.objects.filter(
        month_covered=prev_month_start,
        status='PAID'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    if revenue_prev_month > 0:
        revenue_growth = round(float((revenue_this_month - revenue_prev_month) / revenue_prev_month * 100), 1)
    else:
        revenue_growth = None

    total_revenue_ytd = Payment.objects.filter(
        month_covered__year=today.year,
        status='PAID'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    context = {
        'monthly_revenue': monthly_revenue,
        'room_stats': room_stats,
        'revenue_this_month': revenue_this_month,
        'revenue_prev_month': revenue_prev_month,
        'revenue_growth': revenue_growth,
        'total_revenue_ytd': total_revenue_ytd,
        'current_month_label': f"{month_name_fr(current_month_start.month)} {current_month_start.year}",
    }
    return render(request, 'admin/statistics.html', context)


def schedule_conflicts(request):
    """
    Dashboard displaying all schedule, session, capacity, and student overlap conflicts.
    """
    from core.services.scheduling import SchedulingFacade
    from django.utils import timezone as tz
    
    past_days = 14
    future_days = 30
    
    conflicts_data = SchedulingFacade.get_conflicts(past_days=past_days, future_days=future_days)
    conflicts_data['last_checked'] = tz.now()
    return render(request, 'core/schedule_conflicts.html', conflicts_data)



def check_conflict_ajax(request):
    """
    AJAX endpoint for real-time conflict checking on session/schedule forms.
    Checks room, teacher, capacity, group, teacher leave, and teacher availability.
    """
    from .models import Room, Teacher, CourseGroup, Session, CourseGroupSchedule, TeacherLeave, TeacherAvailability
    from datetime import datetime as dt

    check_type = request.GET.get('type')  # 'session' or 'schedule'
    room_id = request.GET.get('room_id')
    teacher_id = request.GET.get('teacher_id')
    start_time_str = request.GET.get('start_time')
    end_time_str = request.GET.get('end_time')
    exclude_id = request.GET.get('exclude_id')

    if not (room_id and start_time_str and end_time_str):
        return JsonResponse({'conflicts': [], 'has_conflict': False})

    try:
        start_time = dt.strptime(start_time_str, '%H:%M').time()
        end_time = dt.strptime(end_time_str, '%H:%M').time()
    except ValueError:
        return JsonResponse({'error': 'Format de l\'heure invalide. Utilisez HH:MM.'}, status=400)

    if end_time <= start_time:
        return JsonResponse({'error': 'L\'heure de fin doit être postérieure à l\'heure de début.'}, status=400)

    conflicts = []

    if check_type == 'schedule':
        day = request.GET.get('day')
        if not day:
            return JsonResponse({'error': 'Le jour (day) est requis pour les schedules.'}, status=400)

        # Check room conflicts in weekly schedule
        room_qs = CourseGroupSchedule.objects.filter(
            room_id=room_id, day=day, course_group__is_active=True
        )
        if exclude_id:
            room_qs = room_qs.exclude(id=exclude_id)
        for sch in room_qs:
            if start_time < sch.end_time and end_time > sch.start_time:
                conflicts.append({
                    'type': 'ROOM',
                    'severity': 'critical',
                    'message': f"La salle est déjà réservée par le groupe '{sch.course_group.name}' de {sch.start_time.strftime('%H:%M')} à {sch.end_time.strftime('%H:%M')}."
                })

        # Check teacher conflicts in weekly schedule
        if not teacher_id:
            group_id = request.GET.get('group_id')
            if group_id:
                grp = CourseGroup.objects.filter(id=group_id).select_related('teacher').first()
                if grp and grp.teacher_id:
                    teacher_id = grp.teacher_id

        if teacher_id:
            teacher_qs = CourseGroupSchedule.objects.filter(
                course_group__teacher_id=teacher_id, day=day, course_group__is_active=True
            )
            if exclude_id:
                teacher_qs = teacher_qs.exclude(id=exclude_id)
            for sch in teacher_qs:
                if start_time < sch.end_time and end_time > sch.start_time:
                    conflicts.append({
                        'type': 'TEACHER',
                        'severity': 'critical',
                        'message': f"Le professeur est déjà affecté au groupe '{sch.course_group.name}' de {sch.start_time.strftime('%H:%M')} à {sch.end_time.strftime('%H:%M')}."
                    })

    else:  # session check
        date_str = request.GET.get('date')
        if not date_str:
            return JsonResponse({'error': 'La date est requise pour les sessions.'}, status=400)
        try:
            date_obj = dt.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'error': 'Format de date invalide.'}, status=400)

        # ── Room conflicts ────────────────────────────────────────────
        room_qs = Session.objects.filter(date=date_obj, room_id=room_id).exclude(status='CANCELLED')
        if exclude_id:
            room_qs = room_qs.exclude(id=exclude_id)
        for s in room_qs:
            if start_time < s.end_time and end_time > s.start_time:
                conflicts.append({
                    'type': 'ROOM',
                    'severity': 'critical',
                    'message': f"La salle est déjà réservée par le groupe '{s.group.name}' de {s.start_time.strftime('%H:%M')} à {s.end_time.strftime('%H:%M')}."
                })

        # ── Derive teacher from group if not explicitly passed ─────────
        group_id = request.GET.get('group_id')
        if not teacher_id and group_id:
            grp = CourseGroup.objects.filter(id=group_id).select_related('teacher').first()
            if grp and grp.teacher_id:
                teacher_id = grp.teacher_id

        # ── Teacher session conflicts ──────────────────────────────────
        if teacher_id:
            teacher_sess_qs = Session.objects.filter(date=date_obj).filter(
                Q(group__teacher_id=teacher_id, substitute_teacher__isnull=True) |
                Q(substitute_teacher_id=teacher_id)
            ).exclude(status='CANCELLED')
            if exclude_id:
                teacher_sess_qs = teacher_sess_qs.exclude(id=exclude_id)
            for s in teacher_sess_qs:
                if start_time < s.end_time and end_time > s.start_time:
                    conflicts.append({
                        'type': 'TEACHER',
                        'severity': 'critical',
                        'message': f"Le professeur est déjà affecté au groupe '{s.group.name}' de {s.start_time.strftime('%H:%M')} à {s.end_time.strftime('%H:%M')}."
                    })

            # ── Teacher leave check ───────────────────────────────────
            teacher_leaves = TeacherLeave.objects.filter(
                teacher_id=teacher_id,
                start_date__lte=date_obj,
                end_date__gte=date_obj
            ).select_related('teacher')
            for leave in teacher_leaves:
                conflicts.append({
                    'type': 'TEACHER_LEAVE',
                    'severity': 'critical',
                    'message': f"Le professeur est en congé ce jour ({leave.get_leave_type_display()})."
                })

            # ── Teacher availability check ─────────────────────────────
            DAY_MAP = {0: 'MON', 1: 'TUE', 2: 'WED', 3: 'THU', 4: 'FRI', 5: 'SAT', 6: 'SUN'}
            day_str = DAY_MAP[date_obj.weekday()]
            avail_entries = TeacherAvailability.objects.filter(
                teacher_id=teacher_id, day=day_str
            )
            unavail = [e for e in avail_entries if not e.is_available]
            for e in unavail:
                if start_time < e.end_time and end_time > e.start_time:
                    conflicts.append({
                        'type': 'TEACHER_UNAVAILABLE',
                        'severity': 'warning',
                        'message': f"Le professeur est indisponible de {e.start_time.strftime('%H:%M')} à {e.end_time.strftime('%H:%M')} ce jour."
                    })
            avail = [e for e in avail_entries if e.is_available]
            if avail and not any(start_time >= e.start_time and end_time <= e.end_time for e in avail):
                conflicts.append({
                    'type': 'TEACHER_OUT_OF_BOUNDS',
                    'severity': 'warning',
                    'message': "La séance est planifiée en dehors des heures de disponibilité du professeur."
                })

        # ── Capacity check ────────────────────────────────────────────
        if group_id:
            group = CourseGroup.objects.filter(id=group_id).first()
            room = Room.objects.filter(id=room_id).first()
            if group and room:
                student_count = group.students.filter(is_active=True).count()
                if student_count > room.capacity:
                    overflow = student_count - room.capacity
                    conflicts.append({
                        'type': 'CAPACITY',
                        'severity': 'warning',
                        'message': f"Le nombre d'élèves inscrits ({student_count}) dépasse la capacité de la salle '{room.name}' ({room.capacity} places, +{overflow} en trop)."
                    })

            # ── Group double-booking ──────────────────────────────────
            if date_str:
                try:
                    date_obj_g = dt.strptime(date_str, '%Y-%m-%d').date()
                    grp_qs = Session.objects.filter(date=date_obj_g, group_id=group_id).exclude(status='CANCELLED')
                    if exclude_id:
                        grp_qs = grp_qs.exclude(id=exclude_id)
                    for s in grp_qs:
                        if start_time < s.end_time and end_time > s.start_time:
                            conflicts.append({
                                'type': 'GROUP',
                                'severity': 'warning',
                                'message': f"Le groupe a déjà une session planifiée de {s.start_time.strftime('%H:%M')} à {s.end_time.strftime('%H:%M')}."
                            })
                except ValueError:
                    pass

    return JsonResponse({
        'has_conflict': len(conflicts) > 0,
        'conflicts': conflicts
    })


    


# ==================== LEVELS CRUD ====================

def levels_list(request):
    """List all levels"""
    from .models import Level
    from django.db.models import Case, When, Value, IntegerField
    levels = Level.objects.select_related('category').all().annotate(
        category_order=Case(
            When(category__code='GARDERIE', then=Value(1)),
            When(category__code='PRIMAIRE', then=Value(2)),
            When(category__code='COLLEGE', then=Value(3)),
            When(category__code='LYCEE', then=Value(4)),
            default=Value(5),
            output_field=IntegerField(),
        )
    ).order_by('category_order', 'name')
    return render(request, 'core/levels_list.html', {'levels': levels})

def level_detail(request, level_id):
    """Detail page for a specific academic level"""
    from .models import Level
    level = get_object_or_404(Level, pk=level_id)
    
    # Get course groups for this level, optimized with teacher prefetch
    course_groups = level.course_groups.all().select_related('teacher').prefetch_related('schedules__room')
    course_groups = course_groups.annotate(enrollment_count=Count('enrollment'))
    
    # Get students in this level
    students = list(level.students.all().prefetch_related('enrollment_set__course_group', 'payments').order_by('name'))
    from .utils import populate_student_payment_and_fee_info
    populate_student_payment_and_fee_info(students)
    
    # Compute quick stats
    total_students = len(students)
    active_students = sum(1 for s in students if s.is_active)
    total_groups = course_groups.count()
    
    # Total monthly expected revenue from this level
    total_monthly_fees = sum((getattr(s, 'computed_total_monthly_fees', Decimal('0.00')) for s in students if s.is_active), Decimal('0.00'))
    
    context = {
        'level': level,
        'course_groups': course_groups,
        'students': students,
        'total_students': total_students,
        'active_students': active_students,
        'total_groups': total_groups,
        'total_monthly_fees': total_monthly_fees,
    }
    return render(request, 'core/level_detail.html', context)


@require_http_methods(['GET', 'POST'])
def level_create(request):
    """Create a new level"""
    from .forms import LevelForm
    if request.method == 'POST':
        form = LevelForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Niveau créé avec succès.")
            return redirect('core:levels_list')
    else:
        form = LevelForm()
    return render(request, 'core/level_form.html', {'form': form, 'action': 'Créer'})

@require_http_methods(['GET', 'POST'])
def level_edit(request, level_id):
    """Edit an existing level"""
    from .models import Level
    from .forms import LevelForm
    level = get_object_or_404(Level, pk=level_id)
    if request.method == 'POST':
        form = LevelForm(request.POST, instance=level)
        if form.is_valid():
            form.save()
            messages.success(request, "Niveau modifié avec succès.")
            return redirect('core:levels_list')
    else:
        form = LevelForm(instance=level)
    return render(request, 'core/level_form.html', {'form': form, 'action': 'Modifier', 'level': level})

def level_delete_confirm(request, level_id):
    """Confirmation page for deleting a level"""
    from .models import Level
    level = get_object_or_404(Level, pk=level_id)
    return render(request, 'core/level_delete_confirm.html', {'level': level})

@require_POST
def level_delete(request, level_id):
    """Delete a level"""
    from .models import Level
    from django.db.models import ProtectedError
    level = get_object_or_404(Level, pk=level_id)
    try:
        level.delete()
        messages.success(request, "Niveau supprimé avec succès.")
    except ProtectedError:
        messages.error(request, "Impossible de supprimer ce niveau car il est utilisé par des groupes de cours.")
    return redirect('core:levels_list')


# =====================
# TEACHER CRUD VIEWS
# =====================

def teacher_detail(request, teacher_id):
    """Detail page for a specific teacher"""
    from .models import Teacher, TeacherLeave, TeacherAvailability, Session
    from django.db.models import Count, Q, Sum
    from datetime import date

    teacher = get_object_or_404(Teacher, pk=teacher_id)

    # Course groups
    course_groups = teacher.course_groups.all().prefetch_related('schedules__room').annotate(
        enrollment_count=Count('enrollment', distinct=True)
    )

    # Availability slots
    availabilities = teacher.availabilities.all().order_by('day', 'start_time')

    # Upcoming leaves
    today = date.today()
    leaves = teacher.leaves.order_by('-start_date')[:10]
    active_leave = teacher.leaves.filter(start_date__lte=today, end_date__gte=today).first()

    # Sessions stats
    sessions_qs = Session.objects.filter(group__teacher=teacher).exclude(status='CANCELLED')
    done_sessions = sessions_qs.filter(status='DONE').count()
    planned_sessions = sessions_qs.filter(status='PLANNED').count()

    # Recent sessions
    recent_sessions = Session.objects.filter(
        group__teacher=teacher
    ).select_related('group', 'room').order_by('-date')[:10]

    context = {
        'teacher': teacher,
        'course_groups': course_groups,
        'availabilities': availabilities,
        'leaves': leaves,
        'active_leave': active_leave,
        'done_sessions': done_sessions,
        'planned_sessions': planned_sessions,
        'recent_sessions': recent_sessions,
        'total_groups': course_groups.count(),
    }
    return render(request, 'core/teacher_detail.html', context)


@require_http_methods(['GET', 'POST'])
def teacher_create(request):
    """Create a new teacher"""
    from .forms import TeacherForm
    if request.method == 'POST':
        form = TeacherForm(request.POST)
        if form.is_valid():
            teacher = form.save()
            messages.success(request, f'Professeur {teacher.name} créé avec succès.')
            return redirect('core:teacher_detail', teacher_id=teacher.id)
    else:
        form = TeacherForm()
    return render(request, 'core/teacher_form.html', {'form': form, 'action': 'Créer'})


@require_http_methods(['POST'])
def teacher_quick_add(request):
    """AJAX endpoint: quickly create a teacher from a popup and return JSON."""
    from .forms import TeacherForm
    post_data = request.POST.copy()
    # Explicitly ensure newly created teacher is marked active
    if 'is_active' not in post_data:
        post_data['is_active'] = 'on'
    form = TeacherForm(post_data)
    if form.is_valid():
        teacher = form.save(commit=False)
        teacher.is_active = True
        teacher.save()
        return JsonResponse({'success': True, 'id': teacher.id, 'name': teacher.name})
    # Collect all field errors
    errors = {field: errs.as_text() for field, errs in form.errors.items()}
    return JsonResponse({'success': False, 'errors': errors}, status=400)


@require_http_methods(['POST'])
def room_quick_add(request):
    """AJAX endpoint: quickly create a room from a popup and return JSON."""
    from .models import Room
    name = request.POST.get('name', '').strip()
    capacity_raw = request.POST.get('capacity', '').strip()
    building = request.POST.get('building', '').strip()
    floor_raw = request.POST.get('floor', '').strip()

    errors = {}
    if not name:
        errors['name'] = "Le nom de la salle est requis."
    elif Room.objects.filter(name__iexact=name).exists():
        errors['name'] = "Une salle avec ce nom existe déjà."

    if not capacity_raw:
        errors['capacity'] = "La capacité est requise."
    else:
        try:
            capacity = int(capacity_raw)
            if capacity < 1:
                errors['capacity'] = "La capacité doit être d'au moins 1 place."
        except ValueError:
            errors['capacity'] = "La capacité doit être un nombre entier valide."

    floor = None
    if floor_raw:
        try:
            floor = int(floor_raw)
        except ValueError:
            errors['floor'] = "L'étage doit être un nombre entier valide."

    if errors:
        return JsonResponse({'success': False, 'errors': errors}, status=400)

    room = Room.objects.create(
        name=name,
        capacity=capacity,
        building=building,
        floor=floor,
        is_active=True,
    )
    return JsonResponse({
        'success': True,
        'id': room.id,
        'name': room.name,
        'capacity': room.capacity,
        'label': f"{room.name} ({room.capacity} places)",
    })


@require_http_methods(['GET', 'POST'])
def teacher_edit(request, teacher_id):
    """Edit an existing teacher"""
    from .models import Teacher
    from .forms import TeacherForm
    teacher = get_object_or_404(Teacher, pk=teacher_id)
    if request.method == 'POST':
        form = TeacherForm(request.POST, instance=teacher)
        if form.is_valid():
            form.save()
            messages.success(request, f'Professeur {teacher.name} modifié avec succès.')
            return redirect('core:teacher_detail', teacher_id=teacher.id)
    else:
        form = TeacherForm(instance=teacher)
    return render(request, 'core/teacher_form.html', {'form': form, 'action': 'Modifier', 'teacher': teacher})


def teacher_delete_confirm(request, teacher_id):
    """Confirmation page before deleting a teacher"""
    from .models import Teacher
    teacher = get_object_or_404(Teacher, pk=teacher_id)
    groups_count = teacher.course_groups.count()
    return render(request, 'core/teacher_delete_confirm.html', {
        'teacher': teacher,
        'groups_count': groups_count,
    })


@require_POST
def teacher_delete(request, teacher_id):
    """Delete a teacher"""
    from .models import Teacher
    from django.db.models import ProtectedError
    teacher = get_object_or_404(Teacher, pk=teacher_id)
    teacher_name = teacher.name
    try:
        teacher.delete()
        messages.success(request, f'Professeur {teacher_name} supprimé avec succès.')
    except ProtectedError:
        messages.error(request, f'Impossible de supprimer {teacher_name} car il est affecté à des groupes de cours.')
    return redirect('core:teachers_list')


# =====================
# TEACHER AVAILABILITY VIEWS
# =====================

@require_http_methods(['GET', 'POST'])
def teacher_availability(request, teacher_id):
    """Manage a teacher's weekly availability slots – list + inline add."""
    from .models import Teacher, TeacherAvailability
    from .forms import TeacherAvailabilityForm

    teacher = get_object_or_404(Teacher, pk=teacher_id)

    if request.method == 'POST':
        form = TeacherAvailabilityForm(request.POST)
        if form.is_valid():
            slot = form.save(commit=False)
            slot.teacher = teacher
            try:
                slot.full_clean()
                slot.save()
                messages.success(request, 'Créneau de disponibilité ajouté.')
            except Exception as e:
                messages.error(request, str(e))
            return redirect('core:teacher_availability', teacher_id=teacher.id)
    else:
        form = TeacherAvailabilityForm()

    # Group by day for display
    DAY_ORDER = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN']
    DAY_LABELS = {
        'MON': 'Lundi', 'TUE': 'Mardi', 'WED': 'Mercredi',
        'THU': 'Jeudi', 'FRI': 'Vendredi', 'SAT': 'Samedi', 'SUN': 'Dimanche',
    }
    slots = teacher.availabilities.all().order_by('day', 'start_time')
    by_day = {d: [] for d in DAY_ORDER}
    for s in slots:
        by_day[s.day].append(s)

    days = [{'code': d, 'label': DAY_LABELS[d], 'slots': by_day[d]} for d in DAY_ORDER]

    return render(request, 'core/teacher_availability.html', {
        'teacher': teacher,
        'form': form,
        'days': days,
        'total_slots': slots.count(),
    })


@require_POST
def teacher_availability_delete(request, teacher_id, slot_id):
    """Delete a single availability slot (POST or AJAX)."""
    from .models import TeacherAvailability
    slot = get_object_or_404(TeacherAvailability, pk=slot_id, teacher_id=teacher_id)
    slot.delete()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})
    messages.success(request, 'Créneau supprimé.')
    return redirect('core:teacher_availability', teacher_id=teacher_id)


# =====================
# TEACHER LEAVE VIEWS
# =====================

@require_http_methods(['GET', 'POST'])
def teacher_leaves(request, teacher_id):
    """Manage a teacher's leaves – list + inline add."""
    from .models import Teacher, TeacherLeave
    from .forms import TeacherLeaveForm
    from datetime import date

    teacher = get_object_or_404(Teacher, pk=teacher_id)

    if request.method == 'POST':
        form = TeacherLeaveForm(request.POST)
        if form.is_valid():
            leave = form.save(commit=False)
            leave.teacher = teacher
            try:
                leave.full_clean()
                leave.save()
                messages.success(request, 'Congé enregistré avec succès.')
            except Exception as e:
                messages.error(request, str(e))
            return redirect('core:teacher_leaves', teacher_id=teacher.id)
    else:
        form = TeacherLeaveForm()

    today = date.today()
    leaves = teacher.leaves.order_by('-start_date')
    active_leaves = [l for l in leaves if l.start_date <= today <= l.end_date]
    upcoming_leaves = [l for l in leaves if l.start_date > today]
    past_leaves = [l for l in leaves if l.end_date < today]

    return render(request, 'core/teacher_leaves.html', {
        'teacher': teacher,
        'form': form,
        'leaves': leaves,
        'active_leaves': active_leaves,
        'upcoming_leaves': upcoming_leaves,
        'past_leaves': past_leaves,
        'today': today,
    })


@require_http_methods(['GET', 'POST'])
def teacher_leave_edit(request, teacher_id, leave_id):
    """Edit a specific leave period."""
    from .models import Teacher, TeacherLeave
    from .forms import TeacherLeaveForm

    teacher = get_object_or_404(Teacher, pk=teacher_id)
    leave = get_object_or_404(TeacherLeave, pk=leave_id, teacher=teacher)

    if request.method == 'POST':
        form = TeacherLeaveForm(request.POST, instance=leave)
        if form.is_valid():
            try:
                l = form.save(commit=False)
                l.full_clean()
                l.save()
                messages.success(request, 'Congé modifié avec succès.')
                return redirect('core:teacher_leaves', teacher_id=teacher.id)
            except Exception as e:
                form.add_error(None, str(e))
    else:
        form = TeacherLeaveForm(instance=leave)

    return render(request, 'core/teacher_leave_edit.html', {
        'teacher': teacher,
        'leave': leave,
        'form': form,
    })


@require_POST
def teacher_leave_delete(request, teacher_id, leave_id):
    """Delete a leave record."""
    from .models import TeacherLeave
    leave = get_object_or_404(TeacherLeave, pk=leave_id, teacher_id=teacher_id)
    leave.delete()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})
    messages.success(request, 'Congé supprimé.')
    return redirect('core:teacher_leaves', teacher_id=teacher_id)


# =====================
# LEVEL CATEGORY CRUD VIEWS
# =====================

def level_categories_list(request):
    """List all level categories"""
    from .models import LevelCategory
    from django.db.models import Count
    categories = LevelCategory.objects.annotate(
        level_count=Count('levels', distinct=True)
    ).order_by('name')
    return render(request, 'core/level_categories_list.html', {'categories': categories})


def level_category_detail(request, category_id):
    """Detail page for a level category"""
    from .models import LevelCategory
    from django.db.models import Count
    category = get_object_or_404(LevelCategory, pk=category_id)
    levels = category.levels.annotate(
        group_count=Count('course_groups', distinct=True),
        student_count=Count('students', distinct=True),
    ).order_by('name')
    return render(request, 'core/level_category_detail.html', {
        'category': category,
        'levels': levels,
    })


@require_http_methods(['GET', 'POST'])
def level_category_create(request):
    """Create a new level category"""
    from .forms import LevelCategoryForm
    if request.method == 'POST':
        form = LevelCategoryForm(request.POST)
        if form.is_valid():
            cat = form.save()
            messages.success(request, f'Catégorie « {cat.name} » créée avec succès.')
            return redirect('core:level_categories_list')
    else:
        form = LevelCategoryForm()
    return render(request, 'core/level_category_form.html', {'form': form, 'action': 'Créer'})


@require_http_methods(['GET', 'POST'])
def level_category_edit(request, category_id):
    """Edit an existing level category"""
    from .models import LevelCategory
    from .forms import LevelCategoryForm
    category = get_object_or_404(LevelCategory, pk=category_id)
    if request.method == 'POST':
        form = LevelCategoryForm(request.POST, instance=category)
        if form.is_valid():
            form.save()
            messages.success(request, f'Catégorie « {category.name} » modifiée avec succès.')
            return redirect('core:level_category_detail', category_id=category.id)
    else:
        form = LevelCategoryForm(instance=category)
    return render(request, 'core/level_category_form.html', {'form': form, 'action': 'Modifier', 'category': category})


def level_category_delete_confirm(request, category_id):
    """Confirmation page before deleting a level category"""
    from .models import LevelCategory
    category = get_object_or_404(LevelCategory, pk=category_id)
    levels_count = category.levels.count()
    return render(request, 'core/level_category_delete_confirm.html', {
        'category': category,
        'levels_count': levels_count,
    })


@require_POST
def level_category_delete(request, category_id):
    """Delete a level category"""
    from .models import LevelCategory
    from django.db.models import ProtectedError
    category = get_object_or_404(LevelCategory, pk=category_id)
    cat_name = category.name
    try:
        category.delete()
        messages.success(request, f'Catégorie « {cat_name} » supprimée avec succès.')
    except ProtectedError:
        messages.error(request, f'Impossible de supprimer « {cat_name} » car elle contient des niveaux.')
    return redirect('core:level_categories_list')


def session_exceptions_list(request):
    """List all auto-detected exceptional/modified sessions."""
    today = timezone.now().date()
    
    # Query exceptional sessions (cancelled, manual edit, or substitute teacher)
    sessions = Session.objects.filter(
        Q(status='CANCELLED') | 
        Q(substitute_teacher__isnull=False) | 
        Q(is_manually_edited=True)
    ).select_related(
        'group', 
        'room', 
        'substitute_teacher', 
        'group__teacher',
        'group__level'
    )
    
    # Filter by group_id if provided
    group_id = request.GET.get('group_id')
    if group_id:
        sessions = sessions.filter(group_id=group_id)
        
    # Order by date
    sessions = sessions.order_by('-date', 'start_time')
    
    # Load course groups for filter select
    courses = CourseGroup.objects.filter(is_active=True).prefetch_related('schedules__room').order_by('name')
    rooms = Room.objects.all()
    
    # Build list containing true exceptional state (in case default schedule was deleted)
    filtered_sessions = []
    for s in sessions:
        if s.is_exceptional:
            filtered_sessions.append(s)
            
    context = {
        'exceptions': filtered_sessions,
        'courses': courses,
        'rooms': rooms,
        'selected_group_id': group_id,
    }
    return render(request, 'core/session_exceptions_list.html', context)


@require_POST
def session_reset_to_default_ajax(request, session_id):
    """
    Reset an exceptional session back to its group's default schedule.
    """
    from django.core.exceptions import ValidationError
    
    session = get_object_or_404(Session, id=session_id)
    default_sch = session.get_default_schedule()
    
    if not default_sch:
        return JsonResponse({
            'success': False, 
            'error': "Ce groupe n'a pas d'horaire par défaut configuré pour ce jour de la semaine."
        }, status=400)
        
    try:
        session.start_time = default_sch.start_time
        session.end_time = default_sch.end_time
        session.room = default_sch.room
        session.substitute_teacher = None
        session.status = 'PLANNED'
        session.is_manually_edited = False
        
        session.full_clean()
        session.save()
        
        return JsonResponse({
            'success': True,
            'message': "La séance a été réinitialisée aux horaires et salle par défaut."
        })
    except ValidationError as ve:
        error_msg = "; ".join(ve.messages) if hasattr(ve, 'messages') else str(ve)
        return JsonResponse({'success': False, 'error': error_msg}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def sessions_monthly(request):
    """Vue du calendrier mensuel des séances"""
    from datetime import date
    import calendar
    import datetime
    from django.db.models import Q
    from .models import CourseGroup, Teacher, Room, Session

    today = date.today()
    try:
        year = int(request.GET.get('year', today.year))
        month = int(request.GET.get('month', today.month))
    except ValueError:
        year = today.year
        month = today.month

    if month < 1 or month > 12:
        month = today.month

    start_date = datetime.date(year, month, 1)
    _, last_day = calendar.monthrange(year, month)
    end_date = datetime.date(year, month, last_day)

    sessions_qs = Session.objects.filter(date__range=[start_date, end_date]).select_related(
        'group', 'group__teacher', 'room', 'substitute_teacher'
    )
    is_teacher = hasattr(request.user, 'profile') and request.user.profile.role == 'TEACHER'
    if is_teacher:
        sessions_qs = sessions_qs.filter(schedule_status='PUBLISHED')

    group_id = request.GET.get('group_id')
    teacher_id = request.GET.get('teacher_id')
    room_id = request.GET.get('room_id')

    if group_id:
        sessions_qs = sessions_qs.filter(group_id=group_id)
    if teacher_id:
        sessions_qs = sessions_qs.filter(Q(group__teacher_id=teacher_id) | Q(substitute_teacher_id=teacher_id))
    if room_id:
        sessions_qs = sessions_qs.filter(room_id=room_id)

    sessions_qs = sessions_qs.order_by('date', 'start_time')
    sessions = list(sessions_qs)

    cal = calendar.Calendar(firstweekday=0)
    weeks_data = []
    for week in cal.monthdatescalendar(year, month):
        week_data = []
        for d in week:
            day_sessions = [s for s in sessions if s.date == d]
            week_data.append({
                'date': d,
                'is_current_month': d.month == month,
                'is_today': d == today,
                'sessions': day_sessions,
            })
        weeks_data.append(week_data)

    prev_month_date = start_date - datetime.timedelta(days=1)
    next_month_date = end_date + datetime.timedelta(days=1)

    groups = CourseGroup.objects.filter(is_active=True).order_by('name')
    teachers = Teacher.objects.filter(is_active=True).order_by('name')
    rooms = Room.objects.filter(is_active=True).order_by('name')

    context = {
        'weeks': weeks_data,
        'year': year,
        'month': month,
        'month_name_fr': ['Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin', 'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre'][month - 1],
        'prev_year': prev_month_date.year,
        'prev_month': prev_month_date.month,
        'next_year': next_month_date.year,
        'next_month': next_month_date.month,
        'groups': groups,
        'teachers': teachers,
        'rooms': rooms,
        'selected_group_id': int(group_id) if group_id else None,
        'selected_teacher_id': int(teacher_id) if teacher_id else None,
        'selected_room_id': int(room_id) if room_id else None,
    }
    return render(request, 'core/sessions_monthly.html', context)


def create_makeup_session(request):
    """Planifier une séance de rattrapage liée à une séance annulée"""
    from django.db import transaction
    from django.contrib import messages
    from .models import Session, Room, Teacher, MakeupSession

    original_session_id = request.GET.get('original_session_id') or request.POST.get('original_session_id')
    orig = get_object_or_404(Session, pk=original_session_id)

    students = orig.group.students.filter(is_active=True)
    rooms = Room.objects.filter(is_active=True)
    teachers = Teacher.objects.filter(is_active=True)

    if request.method == 'POST':
        date_str = request.POST.get('date')
        start_time_str = request.POST.get('start_time')
        end_time_str = request.POST.get('end_time')
        room_id = request.POST.get('room')
        substitute_teacher_id = request.POST.get('substitute_teacher')
        notes = request.POST.get('notes', '')
        student_ids = request.POST.getlist('students')

        try:
            with transaction.atomic():
                makeup_sess = Session(
                    group=orig.group,
                    date=date_str,
                    start_time=start_time_str,
                    end_time=end_time_str,
                    room_id=room_id,
                    substitute_teacher_id=substitute_teacher_id or None,
                    status='PLANNED',
                    notes=f"Rattrapage de la séance du {orig.date.strftime('%d/%m/%Y')} : {notes}",
                    is_manually_edited=True
                )
                makeup_sess.full_clean()
                makeup_sess.save()

                ms = MakeupSession.objects.create(
                    original_session=orig,
                    makeup_session=makeup_sess,
                    notes=notes
                )
                if student_ids:
                    ms.students.set(student_ids)

            messages.success(request, "La séance de rattrapage a été planifiée avec succès.")
            return redirect('core:sessions_monthly')
        except Exception as e:
            messages.error(request, f"Erreur lors de la planification : {str(e)}")

    context = {
        'original_session': orig,
        'students': students,
        'rooms': rooms,
        'teachers': teachers,
    }
    return render(request, 'core/makeup_session_form.html', context)


def attendance_report(request):
    """Rapport d'absence agrégé par élève et groupe"""
    from datetime import date
    import datetime
    from django.db.models import Count, Q
    from .models import Attendance

    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')

    today = date.today()
    default_start = today.replace(day=1)
    default_end = today

    try:
        start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else default_start
        end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else default_end
    except ValueError:
        start_date = default_start
        end_date = default_end

    attendance_qs = Attendance.objects.filter(date__range=[start_date, end_date])

    report_data = (
        attendance_qs.values('student_id', 'student__name', 'course_group_id', 'course_group__name')
        .annotate(
            total_sessions=Count('id'),
            absences=Count('id', filter=Q(is_present=False)),
            presences=Count('id', filter=Q(is_present=True))
        )
        .order_by('-absences', 'student__name')
    )

    results = []
    for item in report_data:
        total = item['total_sessions']
        absences = item['absences']
        absence_percentage = (absences / total * 100) if total > 0 else 0.0
        results.append({
            'student_id': item['student_id'],
            'student_name': item['student__name'],
            'course_group_id': item['course_group_id'],
            'course_group_name': item['course_group__name'],
            'total_sessions': total,
            'absences': absences,
            'presences': item['presences'],
            'absence_percentage': round(absence_percentage, 1),
        })

    # Only show combinations with > 0 absences
    results = [r for r in results if r['absences'] > 0]

    context = {
        'results': results,
        'start_date': start_date.strftime('%Y-%m-%d'),
        'end_date': end_date.strftime('%Y-%m-%d'),
    }
    return render(request, 'core/attendance_report.html', context)


# ==============================================================================
# ATTENDANCE ANALYTICS & AT-RISK DASHBOARD
# ==============================================================================

def attendance_analytics(request):
    """
    Aggregated absence analytics dashboard.

    Filters:
        start_date  – ISO date string (default: first day of current month)
        end_date    – ISO date string (default: today)
        group_id    – optional CourseGroup PK filter
        student_q   – optional student name substring filter

    Per-student metrics:
        total_sessions  – total Attendance records in range
        absences        – records where is_present=False
        absence_rate    – absences / total * 100  (%)
        is_at_risk      – absence_rate > 20 %

    At-risk students receive a WhatsApp parent follow-up action button.
    """
    from datetime import date as date_type
    import datetime as dt_mod
    from django.db.models import Count, Q, FloatField, ExpressionWrapper, F

    AT_RISK_THRESHOLD = 20.0   # percent

    # ── Date range ──────────────────────────────────────────────────────────
    today = date_type.today()
    default_start = today.replace(day=1)
    default_end = today

    start_date_str = request.GET.get('start_date', '')
    end_date_str   = request.GET.get('end_date', '')
    group_id_str   = request.GET.get('group_id', '')
    student_q      = request.GET.get('student_q', '').strip()

    try:
        start_date = dt_mod.datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else default_start
    except ValueError:
        start_date = default_start

    try:
        end_date = dt_mod.datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else default_end
    except ValueError:
        end_date = default_end

    # Clamp end_date >= start_date
    if end_date < start_date:
        end_date = start_date

    # ── Base queryset ────────────────────────────────────────────────────────
    from .models import Attendance, CourseGroup as CG

    qs = Attendance.objects.filter(date__range=[start_date, end_date])

    if group_id_str:
        try:
            qs = qs.filter(course_group_id=int(group_id_str))
        except ValueError:
            pass

    if student_q:
        qs = qs.filter(student__name__icontains=student_q)

    # ── ORM aggregation grouped by student ──────────────────────────────────
    # We aggregate at the student level (across all groups in range)
    raw = (
        qs
        .values('student_id', 'student__name', 'student__parent_contact', 'student__parent_contact_2', 'student__parent_name')
        .annotate(
            total_sessions=Count('id'),
            absences=Count('id', filter=Q(is_present=False)),
        )
        .order_by('-absences', 'student__name')
    )

    # ── Build result rows ────────────────────────────────────────────────────
    results = []
    total_at_risk = 0
    global_total = 0
    global_absences = 0

    for item in raw:
        total = item['total_sessions']
        absences = item['absences']
        absence_rate = round((absences / total * 100) if total > 0 else 0.0, 1)
        is_at_risk = absence_rate > AT_RISK_THRESHOLD

        global_total += total
        global_absences += absences
        if is_at_risk:
            total_at_risk += 1

        # Build WhatsApp parent follow-up link
        parent_phone = item['student__parent_contact'] or item['student__parent_contact_2'] or ''
        parent_name  = item['student__parent_name'] or 'Parent'
        student_name = item['student__name']

        wa_link = ''
        if parent_phone:
            followup_msg = (
                f"Bonjour {parent_name},\n\n"
                f"Nous souhaitons vous informer que {student_name} présente un taux d'absence "
                f"de {absence_rate}% sur la période du "
                f"{start_date.strftime('%d/%m/%Y')} au {end_date.strftime('%d/%m/%Y')}.\n\n"
                f"Merci de nous contacter afin d'en discuter.\n\n"
                f"Cordialement,\nL'équipe pédagogique"
            )
            wa_link = WhatsAppUtils.generate_chat_link(parent_phone, followup_msg)

        results.append({
            'student_id':      item['student_id'],
            'student_name':    student_name,
            'parent_phone':    parent_phone,
            'parent_name':     parent_name,
            'total_sessions':  total,
            'absences':        absences,
            'presences':       total - absences,
            'absence_rate':    absence_rate,
            'is_at_risk':      is_at_risk,
            'wa_link':         wa_link,
        })

    # Sort: at-risk first, then by descending absence rate
    results.sort(key=lambda r: (not r['is_at_risk'], -r['absence_rate']))

    global_rate = round((global_absences / global_total * 100) if global_total > 0 else 0.0, 1)

    # ── Filter controls data ─────────────────────────────────────────────────
    groups = CG.objects.filter(is_active=True).order_by('name')

    context = {
        'results':         results,
        'total_students':  len(results),
        'total_at_risk':   total_at_risk,
        'global_rate':     global_rate,
        'at_risk_threshold': AT_RISK_THRESHOLD,
        'start_date':      start_date.strftime('%Y-%m-%d'),
        'end_date':        end_date.strftime('%Y-%m-%d'),
        'groups':          groups,
        'selected_group':  group_id_str,
        'student_q':       student_q,
    }
    return render(request, 'core/attendance_analytics.html', context)


# ==============================================================================
# ANALYTICS & REPORTING cockpit & dashboard views
# ==============================================================================

from datetime import date
from dateutil.relativedelta import relativedelta
from django.contrib.admin.views.decorators import staff_member_required
from core.analytics import (
    RevenueAnalytics, AttendanceAnalytics, TeacherAnalytics,
    StudentAnalytics, OperationalAnalytics, director_dashboard,
    ReportExporter,
)

@staff_member_required
def analytics_dashboard(request):
    """Main analytics hub dashboard."""
    data = director_dashboard()
    return render(request, 'core/analytics_dashboard.html', data)


@staff_member_required
def analytics_revenue(request):
    """Monthly revenue details, forecast, expected vs paid, and collection rate."""
    months = int(request.GET.get('months', 3))
    context = {
        'monthly_series': RevenueAnalytics.monthly_series(months),
        'ytd': RevenueAnalytics.ytd_summary(),
        'by_group': RevenueAnalytics.revenue_by_course_group(),
        'methods': RevenueAnalytics.payment_method_breakdown(),
        'current_month': RevenueAnalytics.current_month_summary(),
        'months': months,
    }
    return render(request, 'core/analytics_revenue.html', context)


@staff_member_required
def analytics_attendance(request):
    """Weekly trends, daily absence heatmaps, student at-risk risk scoring and WhatsApp follow-up."""
    today = date.today()
    start_str = request.GET.get('start_date', today.replace(day=1).isoformat())
    end_str = request.GET.get('end_date', today.isoformat())
    from datetime import datetime
    try:
        start = datetime.strptime(start_str, '%Y-%m-%d').date()
    except ValueError:
        start = today.replace(day=1)
    try:
        end = datetime.strptime(end_str, '%Y-%m-%d').date()
    except ValueError:
        end = today
    context = {
        'students': AttendanceAnalytics.student_absence_summary(start, end),
        'weekly': AttendanceAnalytics.weekly_trend(),
        'groups': AttendanceAnalytics.group_attendance_matrix(start.replace(day=1)),
        'heatmap': AttendanceAnalytics.daily_absence_heatmap(start.replace(day=1)),
        'start_date': start_str,
        'end_date': end_str,
    }
    return render(request, 'core/analytics_attendance.html', context)


@staff_member_required
def analytics_operational(request):
    """Scheduled vs completed session rates, cancellation details, past planned sessions, scheduling conflicts and system health score."""
    context = {
        'completion': OperationalAnalytics.session_completion_rate(months=6),
        'cancellations': OperationalAnalytics.cancellation_reasons_by_group(),
        'uncompleted': OperationalAnalytics.uncompleted_sessions(),
        'health': OperationalAnalytics.scheduling_health(),
    }
    return render(request, 'core/analytics_operational.html', context)


@staff_member_required
def analytics_students(request):
    """Enrollment trends, student levels distribution and active warning triggers/signals."""
    context = {
        'enrollment_trend': StudentAnalytics.enrollment_trend(),
        'churn': StudentAnalytics.churn_signals(),
        'level_dist': StudentAnalytics.level_distribution(),
        'enroll_stats': StudentAnalytics.enrollment_stats(),
        'multi_group': StudentAnalytics.multi_group_students(),
    }
    return render(request, 'core/analytics_students.html', context)


@staff_member_required
def analytics_rooms(request):
    """Classroom occupancy, capacity utilization rates, and scheduling density."""
    from core.analytics import RoomAnalytics
    from core.models import Room
    from datetime import date
    from django.utils import timezone
    
    today = timezone.now().date()
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

    rooms_list = list(Room.objects.filter(is_active=True).order_by('name'))
    selected_room_id = request.GET.get('room_id')
    
    selected_room = None
    if selected_room_id:
        try:
            selected_room = Room.objects.filter(id=int(selected_room_id)).first()
        except ValueError:
            pass
    if not selected_room and rooms_list:
        selected_room = rooms_list[0]

    room_stats = {}
    if selected_room:
        room_stats = RoomAnalytics.utilization_dashboard_stats(selected_room, start_date, end_date)

    day_names = {
        'MON': 'Lundi', 'TUE': 'Mardi', 'WED': 'Mercredi', 'THU': 'Jeudi',
        'FRI': 'Vendredi', 'SAT': 'Samedi', 'SUN': 'Dimanche'
    }

    context = {
        'occupancy': RoomAnalytics.occupancy_summary(),
        'peak_hours': RoomAnalytics.peak_hour_matrix(),
        'class_sizes': RoomAnalytics.class_size_distribution(),
        'class_usage': RoomAnalytics.class_usage_list(),
        'start_date': start_str,
        'end_date': end_str,
        'rooms_list': rooms_list,
        'selected_room': selected_room,
        'room_stats': room_stats,
        'day_names': day_names
    }
    return render(request, 'core/analytics_rooms.html', context)


@staff_member_required
def analytics_teachers(request):
    """Teacher payroll list, workload factors, and dashboards."""
    from core.analytics import TeacherAnalytics
    from core.models import Teacher
    from datetime import date
    from django.utils import timezone
    
    today = timezone.now().date()
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

    teachers_list = list(Teacher.objects.filter(is_active=True).order_by('name'))
    selected_teacher_id = request.GET.get('teacher_id')
    
    selected_teacher = None
    if selected_teacher_id:
        try:
            selected_teacher = Teacher.objects.filter(id=int(selected_teacher_id)).first()
        except ValueError:
            pass
    if not selected_teacher and teachers_list:
        selected_teacher = teachers_list[0]

    teacher_stats = {}
    if selected_teacher:
        teacher_stats = TeacherAnalytics.workload_dashboard_stats(selected_teacher, start_date, end_date)

    day_names = {
        'MON': 'Lundi', 'TUE': 'Mardi', 'WED': 'Mercredi', 'THU': 'Jeudi',
        'FRI': 'Vendredi', 'SAT': 'Samedi', 'SUN': 'Dimanche'
    }

    context = {
        'payroll': TeacherAnalytics.payroll_summary(start_date, end_date),
        'load': TeacherAnalytics.weekly_load(),
        'subs': TeacherAnalytics.substitution_rate(),
        'start_date': start_str,
        'end_date': end_str,
        'teachers_list': teachers_list,
        'selected_teacher': selected_teacher,
        'teacher_stats': teacher_stats,
        'day_names': day_names
    }

    return render(request, 'core/analytics_teachers.html', context)



# ── PDF and CSV export views ──────────────────────────────────────────────────

@staff_member_required
def export_revenue_pdf(request):
    months = int(request.GET.get('months', 12))
    buf = ReportExporter.revenue_report_pdf(months=months)
    resp = HttpResponse(buf.read(), content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="revenus_{date.today()}.pdf"'
    return resp


@staff_member_required
def export_attendance_pdf(request):
    today = date.today()
    start = (today - relativedelta(months=1)).replace(day=1)
    end = today
    buf = ReportExporter.attendance_report_pdf(start, end)
    resp = HttpResponse(buf.read(), content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="absences_{date.today()}.pdf"'
    return resp


@staff_member_required
def export_payroll_pdf(request):
    today = date.today()
    month_start = today.replace(day=1)
    
    start_str = request.GET.get('start_date')
    end_str = request.GET.get('end_date')
    
    from datetime import datetime
    try:
        start = datetime.strptime(start_str, '%Y-%m-%d').date() if start_str else month_start
    except ValueError:
        start = month_start
    try:
        end = datetime.strptime(end_str, '%Y-%m-%d').date() if end_str else today
    except ValueError:
        end = today
        
    buf = ReportExporter.teacher_payroll_pdf(start, end)
    resp = HttpResponse(buf.read(), content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="paie_{start}_{end}.pdf"'
    return resp


@staff_member_required
def export_teacher_payslip_pdf(request):
    """
    Export detailed PDF payslip for a specific teacher and period.
    """
    from .models import Teacher, Session, TeacherPayment
    from .utils import calculate_teacher_hours, generate_teacher_payslip_pdf, get_months_in_range
    from django.db.models import Q
    from datetime import datetime
    
    teacher_id = request.GET.get('teacher_id')
    start_str = request.GET.get('start_date')
    end_str = request.GET.get('end_date')
    
    if not (teacher_id and start_str and end_str):
        return HttpResponseBadRequest("Missing required parameters")
        
    teacher = get_object_or_404(Teacher, pk=teacher_id)
    try:
        start = datetime.strptime(start_str, '%Y-%m-%d').date()
        end = datetime.strptime(end_str, '%Y-%m-%d').date()
    except ValueError:
        return HttpResponseBadRequest("Invalid date format")
        
    # Recalculate payroll data
    payroll_data = calculate_teacher_hours(teacher, start, end)
    
    # Get payments for matching period months
    target_months = get_months_in_range(start, end)
    q_filter = Q()
    for m in target_months:
        q_filter |= Q(period_month=m.month, period_year=m.year)
        
    logged_payments = []
    if target_months:
        logged_payments = TeacherPayment.objects.filter(
            Q(teacher=teacher) & q_filter
        ).order_by('payment_date', 'id')
    
    result = {
        'teacher': teacher,
        'logged_payments': logged_payments,
        **payroll_data
    }
    
    pdf_buf = generate_teacher_payslip_pdf(teacher, start, end, result)
    response = HttpResponse(pdf_buf.read(), content_type='application/pdf')
    filename = f"bulletin_{teacher.name.replace(' ', '_')}_{start}_{end}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@staff_member_required
def export_churn_pdf(request):
    buf = ReportExporter.churn_report_pdf()
    resp = HttpResponse(buf.read(), content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="retention_{date.today()}.pdf"'
    return resp


@staff_member_required
def export_csv_view(request):
    report_type = request.GET.get('type', 'revenue')
    today = date.today()
    if report_type == 'revenue':
        data = RevenueAnalytics.monthly_series(12)
        fname = f'revenus_{today}.csv'
    elif report_type == 'attendance':
        start = (today - relativedelta(months=1)).replace(day=1)
        raw = AttendanceAnalytics.student_absence_summary(start, today)
        data = [{k: v for k, v in r.items() if k not in ('groups', 'wa_link')} for r in raw]
        fname = f'absences_{today}.csv'
    elif report_type == 'payroll':
        start_str = request.GET.get('start_date')
        end_str = request.GET.get('end_date')
        from datetime import datetime
        try:
            start = datetime.strptime(start_str, '%Y-%m-%d').date() if start_str else today.replace(day=1)
        except ValueError:
            start = today.replace(day=1)
        try:
            end = datetime.strptime(end_str, '%Y-%m-%d').date() if end_str else today
        except ValueError:
            end = today
        data = TeacherAnalytics.payroll_summary(start, end)
        fname = f'paie_{start}_{end}.csv'
    else:
        data = []
        fname = 'export.csv'

    buf = ReportExporter.export_csv(data)
    resp = HttpResponse(buf.read(), content_type='text/csv; charset=utf-8')
    resp['Content-Disposition'] = f'attachment; filename="{fname}"'
    return resp


@require_http_methods(['GET', 'POST'])
def public_teacher_attendance_login(request):
    """Secure landing page for unregistered teachers to verify identity.

    Stores active validation in request.session['public_teacher_id']
    """
    if 'public_teacher_id' in request.session:
        return redirect('core:public_teacher_attendance_dashboard')

    teachers = Teacher.objects.filter(is_active=True).order_by('name')
    error = None

    if request.method == 'POST':
        teacher_id = request.POST.get('teacher_id')
        credential = request.POST.get('credential', '').strip()

        if not teacher_id or not credential:
            error = "Veuillez sélectionner votre nom et saisir votre identifiant de validation."
        else:
            try:
                teacher = Teacher.objects.get(pk=teacher_id, is_active=True)

                # Helper to clean numbers for formatting-agnostic phone check
                def clean_phone(p):
                    return "".join(c for c in p if c.isdigit())

                cred_clean = clean_phone(credential)
                teacher_phone_clean = clean_phone(teacher.phone)

                email_match = teacher.email and teacher.email.strip().lower() == credential.lower()
                phone_match = False
                if cred_clean and teacher_phone_clean:
                    # Match if one contains the other, or match last 9 digits to bypass country code differences
                    if len(cred_clean) >= 9 and len(teacher_phone_clean) >= 9:
                        phone_match = cred_clean[-9:] == teacher_phone_clean[-9:]
                    else:
                        phone_match = cred_clean in teacher_phone_clean or teacher_phone_clean in cred_clean

                if email_match or phone_match:
                    request.session['public_teacher_id'] = teacher.id
                    messages.success(request, f"Connexion réussie. Bienvenue Pr. {teacher.name} !")
                    return redirect('core:public_teacher_attendance_dashboard')
                else:
                    error = "Les informations fournies ne correspondent pas à ce professeur."
            except Teacher.DoesNotExist:
                error = "Enseignant introuvable."

    return render(request, 'core/public_attendance_login.html', {
        'teachers': teachers,
        'error': error,
    })


def public_teacher_attendance_dashboard(request):
    """List sessions associated with verified teacher.

    Categorized into today's sessions, pending sessions, and past history.
    """
    teacher_id = request.session.get('public_teacher_id')
    if not teacher_id:
        return redirect('core:public_teacher_attendance_login')

    teacher = get_object_or_404(Teacher, pk=teacher_id, is_active=True)
    today = timezone.now().date()

    # Retrieve all sessions where this teacher is assigned as group teacher OR substitute
    sessions_qs = Session.objects.filter(
        Q(group__teacher=teacher) | Q(substitute_teacher=teacher)
    ).select_related('group', 'group__teacher', 'room')

    today_sessions = sessions_qs.filter(date=today).order_by('start_time')
    pending_sessions = sessions_qs.filter(date__lt=today, status='PLANNED').order_by('-date', 'start_time')

    # History of completed/cancelled classes from last 7 days
    seven_days_ago = today - timedelta(days=7)
    history_sessions = sessions_qs.filter(
        date__range=[seven_days_ago, today],
        status__in=['DONE', 'CANCELLED']
    ).exclude(date=today, status='PLANNED').order_by('-date', '-start_time')

    return render(request, 'core/public_attendance_dashboard.html', {
        'teacher': teacher,
        'today': today,
        'today_sessions': today_sessions,
        'pending_sessions': pending_sessions,
        'history_sessions': history_sessions,
    })


@require_http_methods(['GET', 'POST'])
def public_teacher_attendance_session(request, session_id):
    """Interactive mobile-friendly page for teacher to register/edit student attendance."""
    teacher_id = request.session.get('public_teacher_id')
    if not teacher_id:
        return redirect('core:public_teacher_attendance_login')

    teacher = get_object_or_404(Teacher, pk=teacher_id, is_active=True)
    session = get_object_or_404(Session, pk=session_id)

    # Security: ensure teacher is authorized for this session
    is_assigned = (session.group.teacher == teacher) or (session.substitute_teacher == teacher)
    if not is_assigned:
        messages.error(request, "Vous n'avez pas l'autorisation d'accéder à cette séance.")
        return redirect('core:public_teacher_attendance_dashboard')

    students = session.group.students.filter(is_active=True)

    if request.method == 'GET':
        existing = Attendance.objects.filter(course_group=session.group, date=session.date)
        present_map = {a.student_id: a.is_present for a in existing}

        from .utils import populate_student_payment_and_fee_info
        month_covered = session.date.replace(day=1)
        students_obj_list = list(students)
        populate_student_payment_and_fee_info(students_obj_list, month_covered)

        students_list = []
        for s in students_obj_list:
            # Default to present (True) if no entry yet exists
            checked = present_map.get(s.id, True)
            is_unpaid = getattr(s, 'computed_payment_status', 'OK') in ('UNPAID', 'PARTIAL')
            students_list.append({
                'student': s,
                'checked': checked,
                'is_unpaid': is_unpaid,
                'remaining': getattr(s, 'computed_remaining', Decimal('0.00'))
            })

        return render(request, 'core/public_attendance_session.html', {
            'session': session,
            'students_list': students_list,
        })

    # POST: Save attendance changes
    with transaction.atomic():
        for student in students:
            key = f'present_{student.id}'
            is_present = key in request.POST
            Attendance.objects.update_or_create(
                student=student,
                course_group=session.group,
                date=session.date,
                defaults={
                    'is_present': is_present,
                    'session': session,
                }
            )

    # Mark the session status as DONE
    session.status = 'DONE'
    session.save()

    messages.success(request, f"Les présences pour le groupe « {session.group.name} » ont été enregistrées.")
    return redirect('core:public_teacher_attendance_dashboard')


def public_teacher_attendance_logout(request):
    """Clear public teacher login state from session."""
    if 'public_teacher_id' in request.session:
        del request.session['public_teacher_id']
    messages.info(request, "Vous avez été déconnecté avec succès.")
    return redirect('core:public_teacher_attendance_login')


def kiosk_home(request):
    """
    Renders the public Parent Kiosk home screen.
    Includes active general announcements, upcoming events, and a clean interface.
    """
    from .models import Announcement, Holiday
    today = timezone.now().date()
    
    # General active announcements
    announcements = Announcement.objects.filter(
        category='general',
        is_active=True
    ).order_by('-created_at')[:5]
    
    # Upcoming events (Holiday + Event Announcements in the future)
    upcoming_events_list = []
    
    # 1. Holidays
    holidays = Holiday.objects.filter(date__gte=today).order_by('date')[:5]
    for h in holidays:
        upcoming_events_list.append({
            'date': h.date,
            'title': f"Congé : {h.name}",
            'description': h.notes or "Tous les groupes concernés" if h.affects_all else "Certains groupes concernés",
            'type': 'holiday'
        })
        
    # 2. Event announcements
    events = Announcement.objects.filter(
        category='event',
        is_active=True,
        event_date__gte=today
    ).order_by('event_date')[:5]
    for e in events:
        upcoming_events_list.append({
            'date': e.event_date,
            'title': e.title,
            'description': e.content,
            'type': 'event'
        })
        
    # Sort events by date
    upcoming_events_list = sorted(upcoming_events_list, key=lambda x: x['date'])[:6]
    
    # Clear previous kiosk search details on landing
    if 'kiosk_student_id' in request.session:
        del request.session['kiosk_student_id']
    if 'kiosk_search_matches' in request.session:
        del request.session['kiosk_search_matches']

    timeout = getattr(settings, 'KIOSK_TIMEOUT', 45)
    
    return render(request, 'core/kiosk_home.html', {
        'announcements': announcements,
        'upcoming_events': upcoming_events_list,
        'timeout': timeout,
        'SCHOOL_NAME': getattr(settings, 'SCHOOL_NAME', 'Centre'),
    })


@require_POST
def kiosk_search(request):
    """
    Validates search query (matricule or parent contact) and handles matching.
    """
    query = request.POST.get('search_query', '').strip()
    if not query:
        messages.error(request, "Veuillez entrer un matricule ou un numéro de téléphone.")
        return redirect('core:kiosk_home')
        
    # 1. Try search by matricule (exact, case-insensitive)
    year_prefix = timezone.now().strftime('%y')
    prefix = f"M{year_prefix}-"
    # Only prepend the prefix when the user typed the short numeric part
    # (not the full matricule). Avoids double-prefix like "M26-M26-00001".
    if not query.upper().startswith('M'):
        query = prefix + query
    student = Student.objects.filter(matricule__iexact=query, is_active=True).first()
    if student:
        request.session['kiosk_student_id'] = student.id
        return redirect('core:kiosk_student')
        
    # Helper to clean non-digit chars from query and phone fields
    def clean_phone(p):
        return "".join(c for c in p if c.isdigit())
        
    query_digits = clean_phone(query)
    
    # Only perform phone search if the query digits are long enough
    if len(query_digits) >= 4:
        active_students = Student.objects.filter(is_active=True)
        matching_students = []
        for s in active_students:
            s_phone1 = clean_phone(s.parent_contact)
            s_phone2 = clean_phone(s.parent_contact_2)
            
            for s_phone in filter(None, [s_phone1, s_phone2]):
                # Compare last 9 digits (handles country codes / missing zeros)
                if len(query_digits) >= 9 and len(s_phone) >= 9:
                    if query_digits[-9:] == s_phone[-9:]:
                        matching_students.append(s)
                        break
                elif query_digits in s_phone or s_phone in query_digits:
                    matching_students.append(s)
                    break
                
        if len(matching_students) == 1:
            request.session['kiosk_student_id'] = matching_students[0].id
            return redirect('core:kiosk_student')
        elif len(matching_students) > 1:
            request.session['kiosk_search_matches'] = [s.id for s in matching_students]
            return redirect('core:kiosk_select')
            
    messages.error(request, "Aucun élève actif trouvé pour ce matricule ou numéro de téléphone.")
    return redirect('core:kiosk_home')


def kiosk_select(request):
    """
    Renders selection page if parent contact matched multiple active students.
    """
    match_ids = request.session.get('kiosk_search_matches')
    if not match_ids:
        messages.error(request, "Aucune recherche active.")
        return redirect('core:kiosk_home')
        
    # Load and validate students
    students = Student.objects.filter(id__in=match_ids, is_active=True)
    if not students.exists():
        messages.error(request, "Aucun élève trouvé.")
        return redirect('core:kiosk_home')
        
    timeout = getattr(settings, 'KIOSK_TIMEOUT', 45)
    
    return render(request, 'core/kiosk_select.html', {
        'students': students,
        'timeout': timeout,
        'SCHOOL_NAME': getattr(settings, 'SCHOOL_NAME', 'Centre'),
    })


def kiosk_select_student(request, student_id):
    """
    Secure endpoint to select one child from the session-matched list.
    """
    match_ids = request.session.get('kiosk_search_matches')
    if not match_ids or student_id not in match_ids:
        messages.error(request, "Sélection invalide ou expirée.")
        return redirect('core:kiosk_home')
        
    student = get_object_or_404(Student, pk=student_id, is_active=True)
    request.session['kiosk_student_id'] = student.id
    
    # Clean matches list
    if 'kiosk_search_matches' in request.session:
        del request.session['kiosk_search_matches']
        
    return redirect('core:kiosk_student')


def kiosk_student(request):
    """
    Displays detail dashboard for verified student.
    """
    student_id = request.session.get('kiosk_student_id')
    if not student_id:
        messages.error(request, "Session expirée ou non autorisée.")
        return redirect('core:kiosk_home')
        
    student = get_object_or_404(Student, pk=student_id, is_active=True)
    
    # Active enrollments
    enrollments = student.enrollment_set.filter(is_active=True).select_related('course_group', 'course_group__teacher')
    active_groups = [e.course_group for e in enrollments]
    
    # Attendance summary
    attendances = Attendance.objects.filter(student=student).order_by('-date')
    total_atts = attendances.count()
    present_count = attendances.filter(is_present=True).count()
    absent_count = total_atts - present_count
    presence_rate = int(round(present_count / total_atts * 100)) if total_atts > 0 else None
    
    # Recent attendance (last 10 records)
    recent_attendances = attendances[:10]
    
    # Remarks (recent attendance notes if available)
    remarks = []
    attendance_notes = Attendance.objects.filter(student=student).exclude(notes='').exclude(notes__isnull=True).select_related('course_group', 'course_group__teacher').order_by('-date')[:5]
    for att in attendance_notes:
        remarks.append({
            'date': att.date,
            'course_group': att.course_group.name,
            'teacher_name': att.course_group.teacher.name,
            'note': att.notes
        })
        
    # School announcements targeted to this student
    from .models import Announcement
    q_filter = Q(target_levels__isnull=True, target_groups__isnull=True)
    if student.level:
        q_filter |= Q(target_levels=student.level)
    if active_groups:
        q_filter |= Q(target_groups__in=active_groups)
        
    announcements = Announcement.objects.filter(
        is_active=True
    ).filter(q_filter).distinct().order_by('-created_at')[:8]
    
    timeout = getattr(settings, 'KIOSK_TIMEOUT', 45)
    
    return render(request, 'core/kiosk_student.html', {
        'student': student,
        'active_groups': active_groups,
        'total_atts': total_atts,
        'present_count': present_count,
        'absent_count': absent_count,
        'presence_rate': presence_rate,
        'recent_attendances': recent_attendances,
        'remarks': remarks,
        'announcements': announcements,
        'timeout': timeout,
        'SCHOOL_NAME': getattr(settings, 'SCHOOL_NAME', 'Centre'),
    })


def kiosk_clear(request):
    """
    Clears Kiosk session tokens and redirects to kiosk home.
    """
    if 'kiosk_student_id' in request.session:
        del request.session['kiosk_student_id']
    if 'kiosk_search_matches' in request.session:
        del request.session['kiosk_search_matches']
    return redirect('core:kiosk_home')


@staff_member_required
def session_reschedule_suggestions_ajax(request, session_id):
    """
    AJAX view returning ranked rescheduling suggestions for a session.
    """
    session = get_object_or_404(Session, id=session_id)
    from core.services.scheduling import SchedulingFacade
    suggestions = SchedulingFacade.get_reschedule_suggestions(session)
    
    data = []
    for sug in suggestions:
        data.append({
            'date': sug.date.strftime('%Y-%m-%d'),
            'date_fr': sug.date.strftime('%d/%m/%Y'),
            'start_time': sug.start_time.strftime('%H:%M'),
            'end_time': sug.end_time.strftime('%H:%M'),
            'room_id': sug.room_id,
            'room_name': sug.room_name,
            'teacher_id': sug.teacher_id,
            'teacher_name': sug.teacher_name,
            'conflict_score': sug.conflict_score,
            'reason': sug.reason
        })
    return JsonResponse({'success': True, 'suggestions': data})


@require_POST
@staff_member_required
def session_reschedule_apply_ajax(request, session_id):
    """
    AJAX view to apply a selected rescheduling suggestion.
    """
    session = get_object_or_404(Session, id=session_id)
    from core.services.scheduling import SchedulingFacade, RescheduleSuggestion
    from datetime import datetime as dt
    
    date_str = request.POST.get('date')
    start_time_str = request.POST.get('start_time')
    end_time_str = request.POST.get('end_time')
    room_id = int(request.POST.get('room_id'))
    teacher_id = int(request.POST.get('teacher_id'))
    conflict_score = int(request.POST.get('conflict_score', 0))
    reason = request.POST.get('reason', '')
    change_reason = request.POST.get('change_reason', 'Rattrapage programmé')
    
    sug = RescheduleSuggestion(
        date=dt.strptime(date_str, '%Y-%m-%d').date(),
        start_time=dt.strptime(start_time_str, '%H:%M').time(),
        end_time=dt.strptime(end_time_str, '%H:%M').time(),
        room_id=room_id,
        room_name='',
        teacher_id=teacher_id,
        teacher_name='',
        conflict_score=conflict_score,
        reason=reason
    )
    
    try:
        makeup_sess = SchedulingFacade.apply_reschedule_suggestion(
            session=session,
            suggestion=sug,
            user=request.user,
            ip_address=request.META.get('REMOTE_ADDR'),
            change_reason=change_reason
        )
        return JsonResponse({
            'success': True,
            'message': f"Rattrapage créé avec succès pour le {makeup_sess.date.strftime('%d/%m/%Y')} dans la salle {makeup_sess.room.name}."
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@require_POST
@staff_member_required
def session_reset_attendance_ajax(request, session_id):
    """
    AJAX view to reset all attendance records for a session.
    """
    session = get_object_or_404(Session, id=session_id)
    from core.services.scheduling import SchedulingFacade
    try:
        count = SchedulingFacade.reset_session_attendance(
            session=session,
            user=request.user,
            ip_address=request.META.get('REMOTE_ADDR')
        )
        return JsonResponse({
            'success': True,
            'message': f"Présences réinitialisées ({count} enregistrements supprimés)."
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@require_POST
@staff_member_required
def schedule_lock_toggle_ajax(request):
    """
    AJAX view for staff/admins to lock/unlock the schedule.
    """
    if not request.user.is_superuser:
        return JsonResponse({'success': False, 'error': 'Seuls les administrateurs peuvent modifier le verrouillage.'}, status=403)
    
    from core.services.scheduling import SchedulingFacade
    from datetime import datetime as dt
    
    is_locked = request.POST.get('is_locked') == 'on'
    start_date_str = request.POST.get('start_date')
    end_date_str = request.POST.get('end_date')
    academic_year = request.POST.get('academic_year')
    notes = request.POST.get('notes', '')
    
    start_date = None
    end_date = None
    if is_locked:
        if start_date_str:
            try:
                start_date = dt.strptime(start_date_str, '%Y-%m-%d').date()
              # Format validation or bypass
            except ValueError:
                pass
        if end_date_str:
            try:
                end_date = dt.strptime(end_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass
    
    try:
        lock = SchedulingFacade.toggle_schedule_lock(
            is_locked=is_locked,
            start_date=start_date,
            end_date=end_date,
            academic_year=academic_year,
            user=request.user,
            notes=notes
        )
        status_str = "verrouillé" if lock.is_locked else "déverrouillé"
        return JsonResponse({
            'success': True,
            'is_locked': lock.is_locked,
            'message': f"Le planning a été {status_str} avec succès."
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@staff_member_required
def session_history_view(request, session_id):
    """
    View displaying the audit history timeline for a session.
    """
    session = get_object_or_404(Session, id=session_id)
    history = session.change_history.all().select_related('user')
    return render(request, 'core/session_history.html', {
        'session': session,
        'history': history
    })


from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404, render
from django.http import JsonResponse, HttpResponse
from django.db.models import Count, Avg, F, Q
from django.utils import timezone
from django.core import signing
from datetime import datetime as dt_class, date, timedelta
import json

from core.models import Session, Teacher, Student, Room, CourseGroup, SessionChangeHistory, Enrollment
from core.services.scheduling import SchedulingFacade

@login_required
def conflict_suggestions_ajax(request):
    """
    Exposes resolution suggestions for a session or conflict.
    """
    session_id = request.GET.get('session_id')
    if not session_id:
        return JsonResponse({'error': 'session_id is required'}, status=400)
    
    session = get_object_or_404(Session, id=session_id)
    
    # Run conflict detection to identify active conflicts involving this session
    from core.services.scheduling.domain import Conflict, ConflictType, ConflictSeverity
    conflicts_dict = SchedulingFacade.get_conflicts()
    all_conflicts = conflicts_dict.get('session_conflicts', []) + conflicts_dict.get('student_conflicts', [])
    
    matching_conflicts = [c for c in all_conflicts if c.session1_id == session.id or c.session2_id == session.id]
    
    if not matching_conflicts:
        # If no active database conflicts, create a default query structure
        matching_conflicts = [Conflict(
            type=ConflictType.TEACHER_DOUBLE_BOOKING,
            severity=ConflictSeverity.WARNING,
            description="Suggestions de planification",
            session1_id=session.id,
            date=session.date,
            start_time=session.start_time,
            end_time=session.end_time
        )]
        
    suggestions = []
    for c in matching_conflicts:
        suggestions.extend(SchedulingFacade.get_conflict_suggestions(c))
        
    return JsonResponse({'success': True, 'suggestions': suggestions})


@login_required
@require_POST
def publish_schedule_ajax(request):
    """
    Publishes draft schedules within a date range.
    """
    if not request.user.is_superuser and getattr(request.user, 'profile', None) and request.user.profile.role not in ['SCHEDULER', 'ACADEMIC_MANAGER', 'BRANCH_MANAGER']:
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)
        
    start_date_str = request.POST.get('start_date')
    end_date_str = request.POST.get('end_date')
    
    if not start_date_str or not end_date_str:
        return JsonResponse({'success': False, 'error': 'Dates are required.'}, status=400)
        
    try:
        from datetime import datetime as dt
        start_date = dt.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = dt.strptime(end_date_str, '%Y-%m-%d').date()
        
        result = SchedulingFacade.publish_schedule(
            start_date=start_date,
            end_date=end_date,
            user=request.user,
            ip_address=request.META.get('REMOTE_ADDR')
        )
        return JsonResponse({'success': True, 'published_count': result['published_count']})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required
def bulk_operations_ajax(request):
    """
    Handles bulk operations (cancel, move, room change, etc.) with previews.
    """
    if not request.user.is_superuser and getattr(request.user, 'profile', None) and request.user.profile.role not in ['SCHEDULER', 'ACADEMIC_MANAGER', 'BRANCH_MANAGER']:
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)

    if request.method == 'POST':
        action = request.POST.get('action')
        filters_str = request.POST.get('filters', '{}')
        params_str = request.POST.get('params', '{}')
        
        try:
            filters = json.loads(filters_str)
            params = json.loads(params_str)
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid JSON format in filters or params.'}, status=400)
            
        # Parse filter dates
        for dkey in ['date_start', 'date_end']:
            if filters.get(dkey):
                from datetime import datetime as dt
                filters[dkey] = dt.strptime(filters[dkey], '%Y-%m-%d').date()
                
        try:
            res = SchedulingFacade.execute_bulk_operation(
                action=action,
                filters=filters,
                params=params,
                user=request.user,
                ip_address=request.META.get('REMOTE_ADDR')
            )
            return JsonResponse({'success': True, 'result': res})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)
            
    else:
        # GET -> Preview affected sessions
        date_start_str = request.GET.get('date_start')
        date_end_str = request.GET.get('date_end')
        teacher_id = request.GET.get('teacher_id')
        room_id = request.GET.get('room_id')
        group_id = request.GET.get('group_id')
        weekday = request.GET.getlist('weekday')
        
        qs = Session.objects.all()
        if date_start_str and date_end_str:
            from datetime import datetime as dt
            try:
                date_start = dt.strptime(date_start_str, '%Y-%m-%d').date()
                date_end = dt.strptime(date_end_str, '%Y-%m-%d').date()
                qs = qs.filter(date__range=[date_start, date_end])
            except ValueError:
                return JsonResponse({'success': False, 'error': 'Invalid dates.'}, status=400)
                
        if teacher_id:
            qs = qs.filter(Q(group__teacher_id=teacher_id) | Q(substitute_teacher_id=teacher_id))
        if room_id:
            qs = qs.filter(room_id=room_id)
        if group_id:
            qs = qs.filter(group_id=group_id)
            
        sessions = list(qs.select_related('group', 'room', 'substitute_teacher', 'group__teacher'))
        if weekday:
            day_map = {0: 'MON', 1: 'TUE', 2: 'WED', 3: 'THU', 4: 'FRI', 5: 'SAT', 6: 'SUN'}
            sessions = [s for s in sessions if day_map[s.date.weekday()] in weekday]
            
        affected = [{
            'id': s.id,
            'group_name': s.group.name if s.group else 'Rattrapage',
            'date': s.date.strftime('%Y-%m-%d'),
            'time': f"{s.start_time.strftime('%H:%M')} - {s.end_time.strftime('%H:%M')}",
            'room': s.room.name if s.room else 'N/A',
            'teacher': s.substitute_teacher.name if s.substitute_teacher else (s.group.teacher.name if s.group and s.group.teacher else 'N/A')
        } for s in sessions]
        
        return JsonResponse({'success': True, 'sessions': affected})


def export_calendar_feed(request, token):
    """
    Public but cryptographically signed iCal export feed.
    """
    try:
        data = signing.loads(token)
    except signing.BadSignature:
        return HttpResponse("Jeton de sécurité invalide ou expiré.", status=403)
        
    entity_type = data.get('type')
    entity_id = data.get('id')
    
    try:
        ics_str = SchedulingFacade.get_calendar_ics(entity_type, entity_id)
    except Exception as e:
        return HttpResponse(f"Erreur d'exportation : {e}", status=400)
        
    response = HttpResponse(ics_str, content_type="text/calendar; charset=utf-8")
    response['Content-Disposition'] = f'attachment; filename="{entity_type}_{entity_id}_calendar.ics"'
    return response


@login_required
def teacher_workload_dashboard(request):
    """
    Teacher Workload & Analytics dashboard.
    """
    if not request.user.is_superuser and getattr(request.user, 'profile', None) and request.user.profile.role not in ['SCHEDULER', 'ACADEMIC_MANAGER', 'BRANCH_MANAGER']:
        return HttpResponse("Accès interdit", status=403)

    teachers = Teacher.objects.filter(is_active=True)
    selected_teacher_id = request.GET.get('teacher_id')
    
    today = date.today()
    start_date_str = request.GET.get('start_date', str(today - timedelta(days=30)))
    end_date_str = request.GET.get('end_date', str(today + timedelta(days=30)))
    
    from datetime import datetime as dt
    try:
        start_date = dt.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = dt.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        start_date = today - timedelta(days=30)
        end_date = today + timedelta(days=30)
        
    teacher_metrics = None
    selected_teacher = None
    
    if selected_teacher_id:
        selected_teacher = get_object_or_404(Teacher, id=selected_teacher_id)
        teacher_metrics = SchedulingFacade.get_teacher_workload(selected_teacher, start_date, end_date)
        
    # Build list of secure export tokens for all teachers
    teacher_tokens = {}
    for t in teachers:
        teacher_tokens[t.id] = signing.dumps({'type': 'teacher', 'id': t.id})
        
    return render(request, 'core/teacher_workload.html', {
        'teachers': teachers,
        'selected_teacher': selected_teacher,
        'metrics': teacher_metrics,
        'start_date': start_date,
        'end_date': end_date,
        'teacher_tokens': teacher_tokens
    })


@login_required
def schedule_analytics_dashboard(request):
    """
    Advanced Academic Scheduling analytics and utilization statistics.
    """
    if not request.user.is_superuser and getattr(request.user, 'profile', None) and request.user.profile.role not in ['ACADEMIC_MANAGER', 'BRANCH_MANAGER', 'AUDITOR']:
        return HttpResponse("Accès interdit", status=403)

    today = date.today()
    start_date = today - timedelta(days=30)
    end_date = today + timedelta(days=30)
    
    # Calculate global utilization metrics
    total_sessions = Session.objects.filter(date__range=[start_date, end_date]).count()
    cancelled_sessions = Session.objects.filter(date__range=[start_date, end_date], status='CANCELLED').count()
    done_sessions = Session.objects.filter(date__range=[start_date, end_date], status='DONE').count()
    planned_sessions = Session.objects.filter(date__range=[start_date, end_date], status='PLANNED').count()
    
    # Room Utilization: count hours per room
    room_data = []
    rooms = Room.objects.all()
    for rm in rooms:
        sess_list = Session.objects.filter(room=rm, date__range=[start_date, end_date]).exclude(status='CANCELLED')
        total_minutes = 0
        for s in sess_list:
            t1 = dt_class.combine(s.date, s.start_time)
            t2 = dt_class.combine(s.date, s.end_time)
            total_minutes += (t2 - t1).total_seconds() / 60.0
        
        hours = round(total_minutes / 60.0, 1)
        avg_students = Enrollment.objects.filter(course_group__sessions__room=rm).annotate(cnt=Count('id')).aggregate(Avg('cnt'))['cnt__avg'] or 0
        cap_util = round((avg_students / rm.capacity * 100) if rm.capacity > 0 else 0, 1)
        
        room_data.append({
            'room': rm.name,
            'hours': hours,
            'capacity_utilization': cap_util
        })
        
    room_data.sort(key=lambda x: x['hours'], reverse=True)
    
    # Audit log analytics
    change_reasons_qs = SessionChangeHistory.objects.values('change_reason').annotate(count=Count('id')).order_by('-count')[:5]
    
    # Conflict statistics
    conflicts_dict = SchedulingFacade.get_conflicts()
    total_conflicts_count = len(conflicts_dict.get('session_conflicts', [])) + len(conflicts_dict.get('student_conflicts', []))
    
    # Sign tokens for rooms and groups to export in template
    room_tokens = {r.id: signing.dumps({'type': 'room', 'id': r.id}) for r in Room.objects.all()}
    group_tokens = {g.id: signing.dumps({'type': 'group', 'id': g.id}) for g in CourseGroup.objects.all()}

    return render(request, 'core/schedule_analytics.html', {
        'total_sessions': total_sessions,
        'cancellation_rate': round((cancelled_sessions / total_sessions * 100) if total_sessions > 0 else 0, 1),
        'done_sessions': done_sessions,
        'planned_sessions': planned_sessions,
        'room_data': room_data,
        'change_reasons': list(change_reasons_qs),
        'total_conflicts': total_conflicts_count,
        'start_date': start_date,
        'end_date': end_date,
        'room_tokens': room_tokens,
        'group_tokens': group_tokens
    })


@login_required
def student_schedule_portal(request):
    """
    Public student and parent schedule lookup portal.
    """
    profile = getattr(request.user, 'profile', None)
    student = None
    if profile and profile.role == 'TEACHER':
        return HttpResponse("Cette page est réservée aux élèves et parents.", status=403)
        
    if profile and profile.student:
        student = profile.student
    else:
        student = Student.objects.filter(is_active=True).first()
        
    if not student:
        return HttpResponse("Aucun élève associé à ce compte.", status=404)
        
    enrollments = Enrollment.objects.filter(student=student, is_active=True)
    group_ids = enrollments.values_list('course_group_id', flat=True)
    
    today = date.today()
    upcoming_sessions = Session.objects.filter(
        group_id__in=group_ids,
        date__gte=today,
        schedule_status='PUBLISHED'
    ).select_related('group', 'room', 'substitute_teacher', 'group__teacher').order_by('date', 'start_time')
    
    from core.models import MakeupSession
    makeups = MakeupSession.objects.filter(students=student).select_related('makeup_session', 'makeup_session__group', 'makeup_session__room')
    makeup_sessions = [m.makeup_session for m in makeups if m.makeup_session.schedule_status == 'PUBLISHED']
    
    student_token = signing.dumps({'type': 'student', 'id': student.id})
    
    return render(request, 'core/student_schedule.html', {
        'student': student,
        'enrollments': enrollments,
        'upcoming_sessions': upcoming_sessions,
        'makeup_sessions': makeup_sessions,
        'student_token': student_token
    })


@login_required
@require_POST
def restore_history_ajax(request, session_id):
    """
    AJAX endpoint to restore previous session state from audit log.
    """
    if not request.user.is_superuser and getattr(request.user, 'profile', None) and request.user.profile.role not in ['ACADEMIC_MANAGER', 'BRANCH_MANAGER']:
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)
        
    session = get_object_or_404(Session, id=session_id)
    history_id = request.POST.get('history_id')
    if not history_id:
        return JsonResponse({'success': False, 'error': 'history_id parameter is required.'}, status=400)
        
    history_entry = get_object_or_404(SessionChangeHistory, id=history_id, session=session)
    prev_vals = history_entry.previous_values
    if not prev_vals:
        return JsonResponse({'success': False, 'error': 'No previous values recorded in this history entry.'}, status=400)
        
    try:
        from core.services.scheduling.locking import LockingService
        LockingService.check_lock(session.date)
        
        current_vals = {
            'date': str(session.date),
            'start_time': session.start_time.strftime('%H:%M') if session.start_time else '',
            'end_time': session.end_time.strftime('%H:%M') if session.end_time else '',
            'room': session.room.name if session.room else '',
            'substitute_teacher': session.substitute_teacher.name if session.substitute_teacher else ''
        }
        
        if 'date' in prev_vals:
            from datetime import datetime as dt
            session.date = dt.strptime(prev_vals['date'], '%Y-%m-%d').date()
            LockingService.check_lock(session.date)
            
        if 'start_time' in prev_vals:
            from datetime import datetime as dt
            session.start_time = dt.strptime(prev_vals['start_time'], '%H:%M').time()
            
        if 'end_time' in prev_vals:
            from datetime import datetime as dt
            session.end_time = dt.strptime(prev_vals['end_time'], '%H:%M').time()
            
        if 'room' in prev_vals:
            room_name = prev_vals['room']
            session.room = Room.objects.filter(name=room_name).first()
            
        if 'substitute_teacher' in prev_vals:
            sub_name = prev_vals['substitute_teacher']
            if sub_name == '':
                session.substitute_teacher = None
            else:
                session.substitute_teacher = Teacher.objects.filter(name=sub_name).first()
                
        session.is_manually_edited = True
        session.full_clean()
        session.save()
        
        from core.services.scheduling.audit import AuditService
        AuditService.log_change(
            session=session,
            user=request.user,
            action='restore',
            previous_values=current_vals,
            new_values=prev_vals,
            change_reason=f"Restauré à partir de la version de l'historique #{history_id}",
            ip_address=request.META.get('REMOTE_ADDR')
        )
        
        from core.services.scheduling.notifications import NotificationService
        NotificationService.send_session_moved(session)
        
        return JsonResponse({
            'success': True,
            'message': "La séance a été restaurée avec succès."
        })
        
    except ValidationError as ve:
        return JsonResponse({'success': False, 'error': str(ve)}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_http_methods(["GET", "POST"])
def system_settings_view(request):
    """
    Panneau de configuration du centre (simple & intuitif).
    """
    if not request.user.is_authenticated or not (request.user.is_superuser or request.user.is_staff):
        messages.error(request, "Accès réservé aux administrateurs.")
        return redirect('core:cockpit')

    from .forms import SystemSettingsForm
    from .utils import get_setting, set_setting

    keys = [
        'SCHOOL_NAME', 'SCHOOL_SUBTITLE', 'SCHOOL_ADDRESS', 'SCHOOL_PHONE', 'SCHOOL_EMAIL',
        'CURRENCY_SYMBOL', 'RECEIPT_FOOTER_THANK_YOU', 'LATE_PAYMENT_GRACE_DAYS', 'ENABLE_PRORATION',
        'WHATSAPP_AUTO_ABSENCE_NOTIFICATIONS', 'WHATSAPP_SESSION_NOTIFICATIONS_ENABLED',
        'WHATSAPP_AUTO_GROUP_INVITE_ON_FIRST_PAYMENT',
        'KIOSK_TIMEOUT', 'KIOSK_SEARCH_ENABLED',
        'DEFAULT_TEACHER_PAYMENT_METHOD',
    ]

    if request.method == 'POST':
        form = SystemSettingsForm(request.POST)
        if form.is_valid():
            for key in keys:
                val = form.cleaned_data.get(key)
                if isinstance(val, bool):
                    val_str = 'True' if val else 'False'
                elif val is None:
                    val_str = ''
                else:
                    val_str = str(val)
                set_setting(key, val_str)

            messages.success(request, "Paramètres du centre mis à jour avec succès !")
            return redirect('core:system_settings')
        else:
            messages.error(request, "Veuillez vérifier les champs du formulaire.")
    else:
        initial_data = {}
        for key in keys:
            raw_val = get_setting(key)
            if key in ['ENABLE_PRORATION', 'WHATSAPP_SESSION_NOTIFICATIONS_ENABLED', 'WHATSAPP_AUTO_ABSENCE_NOTIFICATIONS', 'WHATSAPP_AUTO_GROUP_INVITE_ON_FIRST_PAYMENT', 'KIOSK_SEARCH_ENABLED']:
                initial_data[key] = str(raw_val).lower() == 'true'
            elif key in ['LATE_PAYMENT_GRACE_DAYS', 'KIOSK_TIMEOUT']:
                try:
                    initial_data[key] = int(raw_val)
                except ValueError:
                    initial_data[key] = 0
            else:
                initial_data[key] = raw_val
        form = SystemSettingsForm(initial=initial_data)

    from .models import Level, Room, CourseGroup, Session, Teacher, Student
    stats = {
        'levels_count': Level.objects.count(),
        'rooms_count': Room.objects.count(),
        'groups_count': CourseGroup.objects.count(),
        'sessions_count': Session.objects.count(),
        'teachers_count': Teacher.objects.count(),
        'students_count': Student.objects.count(),
    }

    return render(request, 'core/system_settings.html', {
        'form': form,
        'stats': stats,
    })


@require_http_methods(["POST"])
def system_quick_action(request):
    """
    Exécute des actions rapides d'initialisation et de maintenance du centre.
    """
    if not request.user.is_authenticated or not (request.user.is_superuser or request.user.is_staff):
        messages.error(request, "Accès réservé aux administrateurs.")
        return redirect('core:cockpit')

    action = request.POST.get('action', '').strip()

    if action == 'setup_levels':
        from .models import Level, LevelCategory
        from .management.commands.setup_levels import Command as SetupLevelsCommand
        cmd = SetupLevelsCommand()
        category_map = {}
        for code, name in cmd.CATEGORIES:
            cat, _ = LevelCategory.objects.get_or_create(code=code, defaults={'name': name})
            category_map[code] = cat

        created_count = 0
        updated_count = 0
        for name, category_code in cmd.LEVELS_DATA:
            cat = category_map[category_code]
            lvl, created = Level.objects.get_or_create(name=name, defaults={'category': cat})
            if created:
                created_count += 1
            elif lvl.category != cat:
                lvl.category = cat
                lvl.save()
                updated_count += 1

        total = Level.objects.count()
        if created_count > 0:
            messages.success(request, f"✨ {created_count} niveaux scolaires créés avec succès ! ({total} niveaux configurés).")
        elif updated_count > 0:
            messages.success(request, f"✨ {updated_count} niveaux mis à jour. Tous les {total} niveaux sont opérationnels.")
        else:
            messages.info(request, f"Tous les {total} niveaux scolaires officiels sont déjà en place.")

    elif action == 'setup_rooms':
        from .models import Room
        default_rooms = [
            {"name": "Salle 1", "capacity": 20, "has_projector": True, "has_air_conditioning": True},
            {"name": "Salle 2", "capacity": 25, "has_projector": True, "has_air_conditioning": False},
            {"name": "Salle 3", "capacity": 30, "has_projector": False, "has_air_conditioning": True},
            {"name": "Salle 4", "capacity": 20, "has_projector": False, "has_air_conditioning": False},
            {"name": "Salle Informatique", "capacity": 20, "has_computer_lab": True, "has_projector": True, "has_air_conditioning": True},
            {"name": "Laboratoire Sciences", "capacity": 24, "has_science_lab": True, "has_projector": True, "has_air_conditioning": True},
        ]
        created_count = 0
        for r_data in default_rooms:
            _, created = Room.objects.get_or_create(
                name=r_data["name"],
                defaults={
                    "capacity": r_data["capacity"],
                    "has_projector": r_data.get("has_projector", False),
                    "has_air_conditioning": r_data.get("has_air_conditioning", False),
                    "has_computer_lab": r_data.get("has_computer_lab", False),
                    "has_science_lab": r_data.get("has_science_lab", False),
                    "is_active": True,
                }
            )
            if created:
                created_count += 1
        total = Room.objects.count()
        if created_count > 0:
            messages.success(request, f"🏫 {created_count} salles créées avec succès ! ({total} salles actives au total).")
        else:
            messages.info(request, f"Toutes les salles types existent déjà ({total} salles au total).")

    elif action == 'generate_sessions':
        from .utils import generate_sessions_from_coursegroups
        from datetime import date, timedelta
        start_date = date.today()
        end_date = start_date + timedelta(weeks=4)
        summary = generate_sessions_from_coursegroups(start_date, end_date, force=False)
        created = summary.get('created', 0)
        updated = summary.get('updated', 0)
        skipped = summary.get('skipped', 0)
        errors = summary.get('errors', [])
        if errors:
            messages.warning(request, f"Planification effectuée avec alertes : {created} créées, {skipped} conservées. Erreurs : {len(errors)}")
        elif created == 0 and skipped == 0:
            messages.warning(request, "Aucun créneau ou groupe de cours actif n'a été trouvé. Veuillez d'abord créer des groupes avec leurs horaires.")
        else:
            messages.success(request, f"📅 Planification réussie : {created} nouvelles séances créées sur les 4 prochaines semaines ({skipped} déjà en place).")

    elif action == 'init_admin':
        from django.core.management import call_command
        from io import StringIO
        buf = StringIO()
        try:
            call_command('initadmin', stdout=buf)
            messages.success(request, "🛡️ Compte super-administrateur 'admin' (mot de passe: 1234) vérifié et opérationnel !")
        except Exception as e:
            messages.error(request, f"Erreur lors de l'initialisation du compte admin : {e}")

    elif action == 'load_demo':
        from django.core.management import call_command
        from io import StringIO
        buf = StringIO()
        try:
            call_command('load_demo_data', force=True, stdout=buf)
            messages.success(request, "🚀 Données de démonstration chargées avec succès ! Les élèves, professeurs, salles, cours et séances sont prêts.")
        except Exception as e:
            messages.error(request, f"Erreur lors du chargement des données démo : {e}")

    else:
        messages.error(request, "Action rapide non reconnue.")

    from django.urls import reverse
    return redirect(reverse('core:system_settings') + '?tab=quick-actions')



def admin_reset_data(request):
    """
    Page d'administration pour réinitialiser / purger toutes les données opérationnelles.
    """
    if not request.user.is_authenticated or not (request.user.is_superuser or request.user.is_staff):
        messages.error(request, "Accès réservé aux administrateurs.")
        return redirect('core:cockpit')

    from .models import (
        SessionChangeHistory, MakeupSession, Attendance, WhatsAppSendLog,
        Payment, TeacherPayment, TeacherLeave, TeacherAvailability,
        Session, Enrollment, CourseGroupSchedule, Holiday,
        Announcement, ScheduleLock, CourseGroup, Student,
        Level, LevelCategory, Teacher, Room
    )

    if request.method == 'POST':
        confirm_text = request.POST.get('confirm_text', '').strip()
        if confirm_text != 'SUPPRIMER':
            messages.error(request, "Veuillez taper exactement le mot 'SUPPRIMER' pour confirmer la suppression définitive.")
            return redirect('core:admin_reset_data')

        # Execute deletions in strict foreign-key order
        deleted_counts = {
            'SessionChangeHistory': SessionChangeHistory.objects.all().delete()[0],
            'MakeupSession': MakeupSession.objects.all().delete()[0],
            'Attendance': Attendance.objects.all().delete()[0],
            'WhatsAppSendLog': WhatsAppSendLog.objects.all().delete()[0],
            'Payment': Payment.objects.all().delete()[0],
            'TeacherPayment': TeacherPayment.objects.all().delete()[0],
            'TeacherLeave': TeacherLeave.objects.all().delete()[0],
            'TeacherAvailability': TeacherAvailability.objects.all().delete()[0],
            'Session': Session.objects.all().delete()[0],
            'Enrollment': Enrollment.objects.all().delete()[0],
            'CourseGroupSchedule': CourseGroupSchedule.objects.all().delete()[0],
            'Holiday': Holiday.objects.all().delete()[0],
            'Announcement': Announcement.objects.all().delete()[0],
            'ScheduleLock': ScheduleLock.objects.all().delete()[0],
            'CourseGroup': CourseGroup.objects.all().delete()[0],
            'Student': Student.objects.all().delete()[0],
            'Teacher': Teacher.objects.all().delete()[0],
            'Room': Room.objects.all().delete()[0],
        }

        total_deleted = sum(deleted_counts.values())
        messages.success(request, f"Toutes les données ont été réinitialisées avec succès ({total_deleted} enregistrements supprimés).")
        return redirect('core:admin_reset_data')

    # Counts for display
    counts = {
        'students': Student.objects.count(),
        'teachers': Teacher.objects.count(),
        'course_groups': CourseGroup.objects.count(),
        'sessions': Session.objects.count(),
        'payments': Payment.objects.count(),
        'attendances': Attendance.objects.count(),
        'rooms': Room.objects.count(),
        'levels': Level.objects.count(),
        'whatsapp_logs': WhatsAppSendLog.objects.count(),
    }
    total_records = sum(counts.values())

    return render(request, 'core/admin_reset_data.html', {
        'counts': counts,
        'total_records': total_records,
    })


def payroll_calculator(request):
    """
    Interactive live payroll and salary calculator supporting:
    - Percentage-based payment (Part des gains / %)
    - Hourly rate payment (Paiement par heure)
    - Fixed salary (Salaire fixe)
    Allows client-side live recalculation without saving to DB.
    Persists to TeacherPayment only on explicit confirmation POST.
    """
    from .models import Teacher, CourseGroup, Level, TeacherPayment
    from dateutil.relativedelta import relativedelta
    from .utils import month_name_fr

    if request.method == 'POST' and request.POST.get('action') == 'save_payment':
        teacher_id = request.POST.get('teacher_id')
        teacher = get_object_or_404(Teacher, pk=teacher_id) if teacher_id else None
        
        if not teacher:
            messages.error(request, "Veuillez sélectionner un enseignant valide pour enregistrer le paiement.")
            return redirect('core:payroll_calculator')

        amount = Decimal(request.POST.get('amount', '0.00'))
        payment_date = request.POST.get('payment_date') or timezone.now().date().strftime('%Y-%m-%d')
        payment_method = request.POST.get('payment_method', 'CASH')
        payment_type = request.POST.get('payment_type', 'SALARY')
        period_month = int(request.POST.get('period_month') or timezone.now().month)
        period_year = int(request.POST.get('period_year') or timezone.now().year)
        notes = request.POST.get('notes', '')

        payment = TeacherPayment.objects.create(
            teacher=teacher,
            amount=amount,
            payment_date=payment_date,
            payment_method=payment_method,
            payment_type=payment_type,
            period_month=period_month,
            period_year=period_year,
            notes=notes
        )
        messages.success(request, f"Paiement de {amount} DH enregistré avec succès pour {teacher.name}.")
        return redirect('core:teacher_payroll')

    today = timezone.now().date()
    # List of months (-5 to +2)
    months_list = []
    for i in range(-5, 3):
        m = today + relativedelta(months=i)
        first_d = m.replace(day=1)
        months_list.append({
            'value': first_d.strftime('%Y-%m-%d'),
            'month': first_d.month,
            'year': first_d.year,
            'label': f"{month_name_fr(first_d.month)} {first_d.year}"
        })

    current_month_str = today.replace(day=1).strftime('%Y-%m-%d')
    teachers = Teacher.objects.filter(is_active=True).order_by('name')
    course_groups = CourseGroup.objects.filter(is_active=True).prefetch_related('levels', 'students').select_related('teacher', 'level').order_by('name')
    levels = Level.objects.all().select_related('category').order_by('category__name', 'order', 'name')

    context = {
        'teachers': teachers,
        'course_groups': course_groups,
        'levels': levels,
        'months_list': months_list,
        'current_month_str': current_month_str,
        'today': today,
    }
    return render(request, 'core/payroll_calculator.html', context)


@require_GET
def payroll_calculator_data_ajax(request):
    """
    API endpoint returning accurate live statistics for groups / teacher / month:
    - total students
    - paid students & unpaid students
    - paid % & unpaid %
    - collected revenue (DH) & theoretical revenue (DH)
    - teacher percentage & hourly rate
    - scheduled / taught hours
    """
    from .models import Teacher, CourseGroup, Payment, Session
    from decimal import Decimal

    teacher_id = request.GET.get('teacher_id')
    month_str = request.GET.get('month')
    group_ids = request.GET.getlist('group_ids[]') or request.GET.getlist('group_ids')
    if not group_ids and request.GET.get('group_ids'):
        group_ids = request.GET.get('group_ids', '').split(',')
    
    clean_group_ids = []
    for gid in group_ids:
        if str(gid).strip().isdigit():
            clean_group_ids.append(int(str(gid).strip()))

    today = timezone.now().date()
    if month_str:
        try:
            target_month = datetime.strptime(month_str, '%Y-%m-%d').date().replace(day=1)
        except (ValueError, TypeError):
            target_month = today.replace(day=1)
    else:
        target_month = today.replace(day=1)

    next_month = (target_month + timedelta(days=32)).replace(day=1)
    end_of_month = next_month - timedelta(days=1)

    teacher = None
    if teacher_id and str(teacher_id).isdigit():
        teacher = Teacher.objects.filter(pk=teacher_id).first()

    # If no groups explicitly chosen, use teacher's assigned groups
    if not clean_group_ids and teacher:
        clean_group_ids = list(CourseGroup.objects.filter(teacher=teacher, is_active=True).values_list('id', flat=True))

    groups = CourseGroup.objects.filter(id__in=clean_group_ids).select_related('teacher', 'level').prefetch_related('levels', 'enrollment_set__student')

    group_data = []
    total_students = 0
    total_paid_students = 0
    total_unpaid_students = 0
    total_collected_revenue = Decimal('0.00')
    total_potential_revenue = Decimal('0.00')
    total_hours_taught = Decimal('0.00')

    for g in groups:
        active_enrollments = list(g.enrollment_set.filter(is_active=True).select_related('student'))
        st_count = len(active_enrollments)
        monthly_price = g.monthly_price or Decimal('0.00')

        # Students payment status in this month for this group
        paid_st_count = 0
        collected_rev = Decimal('0.00')
        students_list = []

        for enr in active_enrollments:
            st = enr.student
            pmts = Payment.objects.filter(
                student=st,
                month_covered=target_month,
                status='PAID'
            ).order_by('-payment_date')
            st_paid = pmts.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            from .utils import calculate_student_monthly_total
            req = calculate_student_monthly_total(st)
            is_paid = (req > 0 and st_paid >= req) or (req == 0 and st_paid > 0)
            is_partial = (req > 0 and 0 < st_paid < req)
            if is_paid:
                paid_st_count += 1
                collected_rev += monthly_price
            elif is_partial:
                ratio = min(st_paid / req, Decimal('1.00'))
                collected_rev += (monthly_price * ratio).quantize(Decimal('0.01'))
                paid_st_count += 1
            elif req == 0 and st_paid > 0:
                paid_st_count += 1
                collected_rev += monthly_price

            latest_p = pmts.first()
            students_list.append({
                'id': st.id,
                'name': st.name,
                'student_id': getattr(st, 'matricule', '') or '',
                'monthly_fee': float(monthly_price),
                'paid_amount': float(st_paid),
                'is_paid': is_paid,
                'is_partial': is_partial,
                'status': 'PAID' if is_paid else ('PARTIAL' if is_partial else 'UNPAID'),
                'payment_date': latest_p.payment_date.strftime('%d/%m/%Y') if latest_p and latest_p.payment_date else None,
                'payment_method': latest_p.get_payment_method_display() if latest_p else None,
            })

        unpaid_st_count = max(0, st_count - paid_st_count)
        paid_pct = round((paid_st_count / st_count * 100), 1) if st_count > 0 else 0.0
        unpaid_pct = round(100.0 - paid_pct, 1) if st_count > 0 else 0.0
        potential_rev = monthly_price * Decimal(st_count)

        # Hours taught in this group during target_month
        sessions = Session.objects.filter(
            group=g,
            date__range=[target_month, end_of_month],
            status='DONE'
        )
        hours = sum(Decimal(str(s.duration_hours())) for s in sessions)

        teacher_pct = teacher.payment_percentage if teacher and teacher.payment_percentage else Decimal('50.00')
        teacher_rate = teacher.hourly_rate if teacher and teacher.hourly_rate else Decimal('100.00')

        group_data.append({
            'id': g.id,
            'name': g.name,
            'subject': g.subject,
            'levels': [lvl.name for lvl in g.levels_list],
            'levels_display': g.levels_display,
            'monthly_price': float(monthly_price),
            'student_count': st_count,
            'paid_count': paid_st_count,
            'unpaid_count': unpaid_st_count,
            'paid_pct': paid_pct,
            'unpaid_pct': unpaid_pct,
            'collected_revenue': float(collected_rev),
            'potential_revenue': float(potential_rev),
            'hours_taught': float(hours),
            'teacher_percentage': float(teacher_pct),
            'hourly_rate': float(teacher_rate),
            'students': students_list,
        })

        total_students += st_count
        total_paid_students += paid_st_count
        total_unpaid_students += unpaid_st_count
        total_collected_revenue += collected_rev
        total_potential_revenue += potential_rev
        total_hours_taught += hours

    global_paid_pct = round((total_paid_students / total_students * 100), 1) if total_students > 0 else 0.0
    global_unpaid_pct = round(100.0 - global_paid_pct, 1) if total_students > 0 else 0.0

    return JsonResponse({
        'teacher': {
            'id': teacher.id if teacher else None,
            'name': teacher.name if teacher else 'Non spécifié / Libre',
            'payment_method': teacher.payment_method if teacher else 'PERCENTAGE',
            'payment_percentage': float(teacher.payment_percentage) if teacher and teacher.payment_percentage else 50.0,
            'hourly_rate': float(teacher.hourly_rate) if teacher and teacher.hourly_rate else 100.0,
            'session_rate': float(teacher.session_rate) if teacher and teacher.session_rate else 100.0,
        } if teacher else None,
        'period': {
            'month': target_month.month,
            'year': target_month.year,
            'month_str': target_month.strftime('%Y-%m-%d'),
        },
        'groups': group_data,
        'totals': {
            'total_students': total_students,
            'paid_students': total_paid_students,
            'unpaid_students': total_unpaid_students,
            'paid_pct': global_paid_pct,
            'unpaid_pct': global_unpaid_pct,
            'collected_revenue': float(total_collected_revenue),
            'potential_revenue': float(total_potential_revenue),
            'hours_taught': float(total_hours_taught),
        }
    })


@require_GET
def print_custom_schedule(request):
    """
    Flexible custom printable schedule filtered by levels, groups, and week.
    Optimized for A4 printing.
    """
    from .models import Level, CourseGroup
    from datetime import timedelta

    raw_level_ids = request.GET.getlist('level_ids[]') or request.GET.getlist('level_ids')
    if not raw_level_ids and request.GET.get('level_ids'):
        raw_level_ids = request.GET.get('level_ids', '').split(',')
    level_ids = [int(x.strip()) for x in raw_level_ids if str(x).strip().isdigit()]

    raw_group_ids = request.GET.getlist('group_ids[]') or request.GET.getlist('group_ids')
    if not raw_group_ids and request.GET.get('group_ids'):
        raw_group_ids = request.GET.get('group_ids', '').split(',')
    group_ids = [int(x.strip()) for x in raw_group_ids if str(x).strip().isdigit()]

    week_param = request.GET.get('week')

    today = timezone.now().date()
    if week_param:
        try:
            parsed = datetime.strptime(week_param, '%Y-%m-%d').date()
            week_start = parsed - timedelta(days=parsed.weekday())
        except (ValueError, TypeError):
            week_start = today - timedelta(days=today.weekday())
    else:
        week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    # Filter CourseGroups
    groups_qs = CourseGroup.objects.filter(is_active=True)
    level_filters = Q()
    if level_ids:
        level_filters = Q(levels__id__in=level_ids) | Q(level_id__in=level_ids)

    if level_ids and group_ids:
        groups_qs = groups_qs.filter(level_filters | Q(id__in=group_ids)).distinct()
    elif level_ids:
        groups_qs = groups_qs.filter(level_filters).distinct()
    elif group_ids:
        groups_qs = groups_qs.filter(id__in=group_ids)
    # If neither is passed, groups_qs is all active groups

    groups = list(groups_qs.select_related('teacher', 'level').prefetch_related('levels', 'schedules__room', 'students').order_by('name'))

    selected_levels = Level.objects.filter(id__in=level_ids) if level_ids else []

    day_order = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN']
    day_labels = {
        'MON': 'Lundi', 'TUE': 'Mardi', 'WED': 'Mercredi',
        'THU': 'Jeudi', 'FRI': 'Vendredi', 'SAT': 'Samedi', 'SUN': 'Dimanche'
    }

    schedules_by_day = {d: [] for d in day_order}
    for g in groups:
        for sch in g.schedules.all():
            schedules_by_day[sch.day].append({
                'group': g,
                'schedule': sch,
                'room': sch.room.name if sch.room else '—',
                'teacher': g.teacher.name if g.teacher else 'Non assigné',
                'levels_display': g.levels_display,
                'students_count': g.students.count(),
                'start_time': sch.start_time,
                'end_time': sch.end_time,
            })

    for d in day_order:
        schedules_by_day[d].sort(key=lambda x: x['start_time'])

    context = {
        'groups': groups,
        'selected_levels': selected_levels,
        'schedules_by_day': schedules_by_day,
        'day_order': day_order,
        'day_labels': day_labels,
        'week_start': week_start,
        'week_end': week_end,
        'print_title': f"Emploi du temps — Semaine du {week_start.strftime('%d/%m/%Y')} au {week_end.strftime('%d/%m/%Y')}",
    }
    return render(request, 'core/print_custom_schedule.html', context)








