"""
Utilitaires pour le système de gestion d'école
"""
from reportlab.platypus import Paragraph
from .models import Session, CourseGroup  # Import necessary models
from django.db.models import Sum
from django.utils import timezone
from django.conf import settings
from decimal import Decimal
from datetime import date
from typing import List, Dict, Tuple, Optional
import calendar
from io import BytesIO
from reportlab.lib.pagesizes import A5
from reportlab.pdfgen import canvas
from .models import Student, Payment

PAID_STATUSES = ('PAID', 'OK', 'CONFIRMED', 'COMPLETED', 'SETTLED')

ROUNDING_INCREMENT = Decimal("10")
OVERPAY_LIMIT = Decimal("1.5")

class SafeDict(dict):
    def __missing__(self, key):
        return f"{{{key}}}"

DEFAULT_SETTINGS = {
    'SCHOOL_NAME': 'Centre',
    'SCHOOL_SUBTITLE': 'Soutien Scolaire & Langues',
    'SCHOOL_ADDRESS': 'Rue Marrakech, Im 16, Ap N 3, 2ème Étage, Khouribga',
    'SCHOOL_PHONE': '0707477911 / 0661569522',
    'SCHOOL_EMAIL': 'contact@centre-tonaroz.com',
    'SCHOOL_LOGO_PATH': 'images/tonaroz_logo.svg',
    'CURRENCY_SYMBOL': 'DH',
    'ENABLE_PRORATION': 'True',
    'LATE_PAYMENT_GRACE_DAYS': '5',
    'RECEIPT_FOOTER_THANK_YOU': 'Merci pour votre confiance ! - شكراً لثقتكم',
    'WHATSAPP_API_KEY': '',
    'WHATSAPP_SERVICE_PORT': '3000',
    'WHATSAPP_SESSION_NOTIFICATIONS_ENABLED': 'True',
    'WHATSAPP_AUTO_ABSENCE_NOTIFICATIONS': 'True',
    'WHATSAPP_AUTO_GROUP_INVITE_ON_FIRST_PAYMENT': 'True',
    'KIOSK_TIMEOUT': '45',
    'KIOSK_SEARCH_ENABLED': 'True',
    'CONFLICT_CACHE_TTL': '120',
    'RESCHEDULING_SEARCH_HORIZON': '21',
    'CAPACITY_WARNING_MARGIN': '2',
    'CAPACITY_NEAR_LIMIT_RATIO': '0.9',
    'DEFAULT_TEACHER_PAYMENT_METHOD': 'SESSION',
}

def get_setting(key: str, default=None):
    """
    Retrieves a runtime system setting from DB with cache fallback.
    """
    from django.core.cache import cache
    cache_key = f'sys_setting_{key}'
    val = cache.get(cache_key)
    if val is not None:
        return val

    try:
        from .models import SystemSetting
        item = SystemSetting.objects.filter(key=key).first()
        if item and item.value is not None:
            val = str(item.value)
        else:
            val = str(getattr(settings, key, DEFAULT_SETTINGS.get(key, default if default is not None else '')))
    except Exception:
        val = str(getattr(settings, key, DEFAULT_SETTINGS.get(key, default if default is not None else '')))

    cache.set(cache_key, val, 60)
    return val

def set_setting(key: str, value: str, label: str = '', group: str = 'GENERAL'):
    from django.core.cache import cache
    from .models import SystemSetting
    item, _ = SystemSetting.objects.get_or_create(key=key)
    item.value = str(value)
    if label:
        item.label = label
    if group:
        item.group = group
    item.save()
    cache.delete(f'sys_setting_{key}')
    cache.delete('school_info_context')


from decimal import ROUND_UP

def is_paid_status(status: str) -> bool:
    return status in PAID_STATUSES


def calculate_payment_status(required: Decimal, paid: Decimal) -> str:
    if required <= 0:
        return "OK"
    if paid >= required:
        return "OK"
    if paid > 0:
        return "PARTIAL"
    return "UNPAID"


def round_to_next_10(amount: Decimal) -> Decimal:
    if amount <= 0:
        return Decimal("0.00")

    return (
        (amount / ROUNDING_INCREMENT)
        .quantize(Decimal("1"), rounding=ROUND_UP)
        * ROUNDING_INCREMENT
    ).quantize(Decimal("0.01"))

# ==================== GESTION DES DATES ====================

FRENCH_MONTHS = {
    1: "janvier", 2: "février", 3: "mars", 4: "avril",
    5: "mai", 6: "juin", 7: "juillet", 8: "août",
    9: "septembre", 10: "octobre", 11: "novembre", 12: "décembre"
}

FRENCH_DAYS = {
    "Monday": "Lundi",
    "Tuesday": "Mardi",
    "Wednesday": "Mercredi",
    "Thursday": "Jeudi",
    "Friday": "Vendredi",
    "Saturday": "Samedi",
    "Sunday": "Dimanche",
}

def format_date_fr(date):
    return f"{FRENCH_MONTHS[date.month]} {date.year}"

def get_current_month_period() -> Tuple[date, date]:
    """Retourne le premier et dernier jour du mois en cours"""
    today = timezone.now().date()
    first_day = today.replace(day=1)
    last_day = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
    return first_day, last_day


def get_month_period(year: int, month: int) -> Tuple[date, date]:
    """Retourne le premier et dernier jour d'un mois donné"""
    first_day = date(year, month, 1)
    last_day = date(year, month, calendar.monthrange(year, month)[1])
    return first_day, last_day


def get_next_month(reference_date: date) -> date:
    """Retourne le premier jour du mois suivant"""
    if reference_date.month == 12:
        return date(reference_date.year + 1, 1, 1)
    return date(reference_date.year, reference_date.month + 1, 1)


def get_previous_month(reference_date: date) -> date:
    """Retourne le premier jour du mois précédent"""
    if reference_date.month == 1:
        return date(reference_date.year - 1, 12, 1)
    return date(reference_date.year, reference_date.month - 1, 1)


def month_name_fr(month_number: int) -> str:
    """Retourne le nom du mois en français"""
    months = {
        1: "Janvier", 2: "Février", 3: "Mars", 4: "Avril",
        5: "Mai", 6: "Juin", 7: "Juillet", 8: "Août",
        9: "Septembre", 10: "Octobre", 11: "Novembre", 12: "Décembre"
    }
    return months.get(month_number, "")


# ==================== CALCULS FINANCIERS ====================

def count_scheduled_sessions_in_month(group, year: int, month: int) -> int:
    """Determine the total scheduled sessions in that calendar month using CourseGroupSchedule"""
    schedules = group.schedules.all()
    if not schedules:
        return 0
    
    cal_weekday_map = {0: 'MON', 1: 'TUE', 2: 'WED', 3: 'THU', 4: 'FRI', 5: 'SAT', 6: 'SUN'}
    num_days = calendar.monthrange(year, month)[1]
    
    total_sessions = 0
    for day in range(1, num_days + 1):
        d = date(year, month, day)
        wday_code = cal_weekday_map[d.weekday()]
        total_sessions += sum(1 for s in schedules if s.day == wday_code)
        
    return total_sessions


def count_remaining_sessions_in_month(group, start_date: date) -> int:
    """Counts the remaining scheduled sessions in a month starting from start_date (inclusive)"""
    schedules = group.schedules.all()
    if not schedules:
        return 0
    
    year = start_date.year
    month = start_date.month
    num_days = calendar.monthrange(year, month)[1]
    
    cal_weekday_map = {0: 'MON', 1: 'TUE', 2: 'WED', 3: 'THU', 4: 'FRI', 5: 'SAT', 6: 'SUN'}
    
    remaining_sessions = 0
    for day in range(start_date.day, num_days + 1):
        d = date(year, month, day)
        wday_code = cal_weekday_map[d.weekday()]
        remaining_sessions += sum(1 for s in schedules if s.day == wday_code)
        
    return remaining_sessions


def calculate_enrollment_expected_fee(enrollment, month_date: date) -> Decimal:
    """Returns the expected monthly fee for an enrollment, pro-rated if registered mid-month"""
    group = enrollment.course_group
    # If enrolled date is in a future month compared to month_date, they owe nothing
    if enrollment.enrolled_date.year > month_date.year or (
        enrollment.enrolled_date.year == month_date.year and enrollment.enrolled_date.month > month_date.month
    ):
        return Decimal('0.00')

    # Check if enrolled date matches month_date
    if enrollment.enrolled_date.year == month_date.year and enrollment.enrolled_date.month == month_date.month:
        if enrollment.enrolled_date.day > 1:
            total_sessions = count_scheduled_sessions_in_month(group, month_date.year, month_date.month)
            if total_sessions == 0:
                return Decimal('0.00')
            session_price = (group.monthly_price / Decimal(total_sessions)).quantize(Decimal('0.01'))
            remaining_sessions = count_remaining_sessions_in_month(group, enrollment.enrolled_date)
            prorated_price = (Decimal(remaining_sessions) * session_price).quantize(Decimal('0.01'))
            return round_to_next_10(prorated_price)    
    return group.monthly_price



def calculate_student_expected_fees_for_month(student, month_date: date) -> Decimal:
    """Calculates student's expected total fees for a given month, accounting for pro-rating"""
    active_enrollments = student.enrollment_set.filter(is_active=True).select_related('course_group')
    total = Decimal('0.00')
    for enrollment in active_enrollments:
        total += calculate_enrollment_expected_fee(enrollment, month_date)
    return total


def calculate_student_monthly_total(student) -> Decimal:
    """
    Calcule le total mensuel qu'un élève doit payer
    Basé sur ses inscriptions actives et les pro-rations éventuelles pour le mois en cours
    """
    current_month = timezone.now().date().replace(day=1)
    return calculate_student_expected_fees_for_month(student, current_month)


def get_student_payment_status(student, month_date: Optional[date] = None) -> Dict:
    """
    Retourne le statut de paiement détaillé d'un élève pour un mois
    
    Returns:
        {
            'required': Decimal,
            'paid': Decimal,
            'remaining': Decimal,
            'status': 'OK' | 'PARTIAL' | 'UNPAID',
            'percentage': float
        }
    """
    from .models import Payment
    
    if month_date is None:
        month_date = timezone.now().date().replace(day=1)
    
    required = calculate_student_expected_fees_for_month(student, month_date)
    
    paid = Payment.objects.filter(
        student=student,
        month_covered=month_date,
        status__in=PAID_STATUSES
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    remaining = required - paid
    
    if required > 0:
        percentage = float((paid / required) * 100)
    else:
        percentage = 0.0
    
    status = calculate_payment_status(required, paid)
    
    return {
        'required': required,
        'paid': paid,
        'remaining': remaining,
        'status': status,
        'percentage': percentage
    }



def get_daily_revenue(target_date: Optional[date] = None) -> Decimal:
    """Calcule la recette du jour"""
    from .models import Payment
    
    if target_date is None:
        target_date = timezone.now().date()
    
    revenue = Payment.objects.filter(
        payment_date=target_date,
        status__in=PAID_STATUSES
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    return revenue


def get_monthly_revenue(year: int, month: int) -> Decimal:
    """Calcule la recette du mois"""
    from .models import Payment
    
    first_day, last_day = get_month_period(year, month)
    
    revenue = Payment.objects.filter(
        payment_date__range=[first_day, last_day],
        status__in=PAID_STATUSES
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    return revenue


def get_unpaid_students(month_date: Optional[date] = None) -> List[dict]:
    """
    Retourne la liste des élèves actifs non à jour pour un mois donné
    """
    if month_date is None:
        month_date = timezone.now().date()
    month_date = month_date.replace(day=1)

    from django.db.models import Prefetch, Sum
    from .models import Student, Enrollment, Payment

    enrollments_qs = Enrollment.objects.filter(is_active=True).select_related('course_group').prefetch_related('course_group__schedules')
    students = Student.objects.filter(is_active=True).prefetch_related(
        Prefetch('enrollment_set', queryset=enrollments_qs, to_attr='active_enrollments')
    )

    payments_summary = Payment.objects.filter(
        month_covered=month_date,
        status__in=PAID_STATUSES
    ).values('student_id').annotate(total_paid=Sum('amount'))
    
    paid_map = {p['student_id']: p['total_paid'] for p in payments_summary}

    unpaid_students = []

    for student in students:
        required = Decimal('0.00')
        for enrollment in student.active_enrollments:
            required += calculate_enrollment_expected_fee(enrollment, month_date)

        paid = paid_map.get(student.id, Decimal('0.00'))
        remaining = max(required - paid, Decimal('0'))

        if paid >= required and required > 0:
            status = 'OK'
        elif paid > 0:
            status = 'PARTIAL'
        else:
            status = 'UNPAID'

        if status in ['UNPAID', 'PARTIAL']:
            unpaid_students.append({
                'student': student,
                'required': required,
                'paid': paid,
                'remaining': remaining,
                'status': status,
            })

    return unpaid_students


def populate_student_payment_and_fee_info(students_list, month_date=None):
    """
    Bulk populates payment and monthly fee information in-memory for a list of students
    to avoid running N+1 queries during list views.
    """
    if not students_list:
        return
    
    if month_date is None:
        month_date = timezone.now().date()
    month_date = month_date.replace(day=1)
    
    from .models import Enrollment, Payment
    from django.db.models import Sum
    
    student_ids = [s.id for s in students_list]
    
    enrollments_qs = Enrollment.objects.filter(
        student_id__in=student_ids,
        is_active=True
    ).select_related('course_group').prefetch_related('course_group__schedules')
    
    enrollments_by_student = {}
    for enrollment in enrollments_qs:
        enrollments_by_student.setdefault(enrollment.student_id, []).append(enrollment)
        
    payments_summary = Payment.objects.filter(
        student_id__in=student_ids,
        month_covered=month_date,
        status__in=PAID_STATUSES
    ).values('student_id').annotate(total_paid=Sum('amount'))
    
    paid_map = {p['student_id']: p['total_paid'] for p in payments_summary}
    
    for student in students_list:
        active_enrollments = enrollments_by_student.get(student.id, [])
        student.computed_active_enrollments = active_enrollments
        
        nominal_fees = sum(
            (e.course_group.monthly_price for e in active_enrollments if e.course_group),
            Decimal("0.00"),
        )
        student.computed_total_monthly_fees = nominal_fees
        
        required = Decimal('0.00')
        for enrollment in active_enrollments:
            required += calculate_enrollment_expected_fee(enrollment, month_date)
            
        paid = paid_map.get(student.id, Decimal('0.00'))
        
        status = calculate_payment_status(required, paid)
            
        student.computed_payment_status = status
        student.computed_paid = paid
        student.computed_required = required
        student.computed_remaining = max(required - paid, Decimal('0.00'))


# ==================== CALCULS PROFESSEURS ====================

def get_months_in_range(start_date: date, end_date: date) -> List[date]:
    """Retourne la liste des premiers jours des mois dans l'intervalle donné (inclusif)"""
    months = []
    current = start_date.replace(day=1)
    target_end = end_date.replace(day=1)
    while current <= target_end:
        months.append(current)
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    return months


def calculate_class_gains(course_group, months: List[date]) -> Tuple[Decimal, Decimal, Decimal, Decimal]:
    """
    Calcule le chiffre d'affaires (gains) réel et théorique d'un groupe de cours
    pour une liste de mois donnés, ainsi que la part issue des inscriptions tardives.
    """
    from .models import Enrollment, Payment
    from django.db.models import Sum
    from collections import defaultdict

    active_enrollments = Enrollment.objects.filter(
        course_group=course_group,
        is_active=True
    ).select_related('student')
    students = [e.student for e in active_enrollments]

    if not students:
        return Decimal('0.00'), Decimal('0.00'), Decimal('0.00'), Decimal('0.00')

    payments = Payment.objects.filter(
        student__in=students,
        month_covered__in=months,
        status__in=PAID_STATUSES
    )

    payment_map = defaultdict(lambda: defaultdict(Decimal))
    for p in payments:
        payment_map[p.student_id][p.month_covered] += p.amount

    gains_actual = Decimal('0.00')
    gains_theoretical = Decimal('0.00')
    gains_regular = Decimal('0.00')
    gains_late = Decimal('0.00')

    for enrollment in active_enrollments:
        student = enrollment.student
        for month in months:
            total_expected = calculate_student_expected_fees_for_month(student, month)
            course_expected = calculate_enrollment_expected_fee(enrollment, month)
            gains_theoretical += course_expected

            paid_amount = payment_map[student.id][month]
            if total_expected > 0:
                contribution = paid_amount * (course_expected / total_expected)
            else:
                contribution = Decimal('0.00')
            gains_actual += contribution
            
            # Differentiate late student additions (registered mid-month in this month)
            is_late = False
            if enrollment.enrolled_date.year == month.year and enrollment.enrolled_date.month == month.month:
                if enrollment.enrolled_date.day > 1:
                    is_late = True
            
            if is_late:
                gains_late += contribution
            else:
                gains_regular += contribution
    return (
        gains_actual.quantize(Decimal('0.01')),
        gains_theoretical.quantize(Decimal('0.01')),
        gains_regular.quantize(Decimal('0.01')),
        gains_late.quantize(Decimal('0.01'))
    )


def calculate_teacher_hours(teacher, start_date: date, end_date: date) -> Dict:
    """
    Calcule les heures travaillées et les gains/salaires pour un professeur sur une période
    """
    from .models import CourseGroup, Attendance, Session, Enrollment, Payment
    from django.db.models import Q
    
    courses = CourseGroup.objects.filter(
        teacher=teacher
    )
    
    total_scheduled_hours = Decimal('0.00')
    
    days_count = (end_date - start_date).days + 1
    weeks_count = Decimal(str(days_count)) / Decimal('7.0')
    
    for course in courses.filter(is_active=True):
        weekly_hours = sum(Decimal(str(sch.duration_hours())) for sch in course.schedules.all())
        scheduled = weekly_hours * weeks_count
        total_scheduled_hours += scheduled

    # Filter sessions where the teacher actually taught:
    # 1. Sessions in groups owned by this teacher where there was no substitute teacher
    own_sessions = Session.objects.filter(
        group__teacher=teacher,
        substitute_teacher__isnull=True,
        date__range=[start_date, end_date],
        status='DONE'
    )
    # 2. Sessions in other groups where this teacher was the substitute
    substitute_sessions = Session.objects.filter(
        substitute_teacher=teacher,
        date__range=[start_date, end_date],
        status='DONE'
    )
    
    all_sessions_taught = list(own_sessions) + list(substitute_sessions)
    total_taught_hours = sum(Decimal(str(s.duration_hours())) for s in all_sessions_taught)
    total_taught_sessions = len(all_sessions_taught)
    
    if teacher.payment_method == 'PERCENTAGE':
        months = get_months_in_range(start_date, end_date)
        
        total_gains_actual = Decimal('0.00')
        total_gains_theoretical = Decimal('0.00')
        total_share_regular = Decimal('0.00')
        total_share_late = Decimal('0.00')
        courses_breakdown = []
        
        for course in courses.filter(is_active=True):
            g_act, g_theo, reg_g, late_g = calculate_class_gains(course, months)
            total_gains_actual += g_act
            total_gains_theoretical += g_theo
            
            # Prorating factor based on sessions taught in this group
            course_sessions = Session.objects.filter(
                group=course,
                date__range=[start_date, end_date],
                status='DONE'
            )
            course_sessions_count = course_sessions.count()
            course_sessions_taught = course_sessions.filter(substitute_teacher__isnull=True).count()
            
            if course_sessions_count > 0:
                prorate_factor = Decimal(course_sessions_taught) / Decimal(course_sessions_count)
            else:
                prorate_factor = Decimal('1.00')
            
            share_actual_gross = (g_act * teacher.payment_percentage / Decimal('100.00'))
            share_actual = (share_actual_gross * prorate_factor).quantize(Decimal('0.01'))
            share_theoretical = (g_theo * teacher.payment_percentage / Decimal('100.00')).quantize(Decimal('0.01'))
            share_regular = (reg_g * teacher.payment_percentage / Decimal('100.00') * prorate_factor).quantize(Decimal('0.01'))
            share_late = (late_g * teacher.payment_percentage / Decimal('100.00') * prorate_factor).quantize(Decimal('0.01'))
            
            total_share_regular += share_regular
            total_share_late += share_late
            
            # Detailed per-student breakdown for this course group
            group_students_info = []
            group_paid_count = 0
            monthly_fee = course.monthly_price or Decimal('0.00')

            active_enrollments = list(Enrollment.objects.filter(
                course_group=course,
                is_active=True,
                student__is_active=True
            ).select_related('student', 'student__level'))

            # Fallback if enrollment objects are not marked active but students are active
            if not active_enrollments:
                for st in course.students.filter(is_active=True).select_related('level'):
                    enr, _ = Enrollment.objects.get_or_create(course_group=course, student=st)
                    active_enrollments.append(enr)

            if active_enrollments:
                payments_qs = Payment.objects.filter(
                    student__in=[e.student for e in active_enrollments],
                    month_covered__in=months,
                    status__in=PAID_STATUSES
                ).order_by('-payment_date')
                all_pmts = list(payments_qs)

                pct = teacher.payment_percentage if teacher.payment_percentage is not None else Decimal('50.00')

                for enr in active_enrollments:
                    st = enr.student
                    st_pmts = [p for p in all_pmts if p.student_id == st.id]
                    st_paid = sum((p.amount for p in st_pmts), Decimal('0.00'))

                    st_exp = sum(
                        (calculate_student_expected_fees_for_month(st, m) for m in months),
                        Decimal('0.00')
                    )
                    c_exp = sum(
                        (calculate_enrollment_expected_fee(enr, m) for m in months),
                        Decimal('0.00')
                    )

                    if st_exp > 0:
                        st_contrib = st_paid * (c_exp / st_exp)
                    else:
                        st_contrib = Decimal('0.00')

                    st_share = (st_contrib * pct / Decimal('100.00') * prorate_factor).quantize(Decimal('0.01'))

                    is_paid = (st_exp > 0 and st_paid >= st_exp) or (st_exp == 0 and st_paid > 0)
                    is_partial = (st_exp > 0 and 0 < st_paid < st_exp)

                    if is_paid or is_partial:
                        group_paid_count += 1

                    latest_p = st_pmts[0] if st_pmts else None

                    group_students_info.append({
                        'student': st,
                        'fee': c_exp if c_exp > 0 else monthly_fee,
                        'paid_amount': st_paid,
                        'status': 'PAID' if is_paid else ('PARTIAL' if is_partial else 'UNPAID'),
                        'payment_date': latest_p.payment_date if latest_p else None,
                        'payment_method': latest_p.get_payment_method_display() if latest_p else None,
                        'teacher_share': st_share,
                        'contribution': st_contrib.quantize(Decimal('0.01')),
                    })

            st_count = len(group_students_info) if group_students_info else course.students.filter(is_active=True).count()
            group_unpaid_count = max(0, st_count - group_paid_count)
            group_rec_pct = round((group_paid_count / st_count * 100), 1) if st_count > 0 else 0.0

            courses_breakdown.append({
                'course': course,
                'student_count': st_count,
                'monthly_fee': monthly_fee,
                'paid_count': group_paid_count,
                'unpaid_count': group_unpaid_count,
                'recovery_pct': group_rec_pct,
                'collected_revenue': g_act,
                'students_info': group_students_info,
                'gains_actual': g_act,
                'gains_theoretical': g_theo,
                'share_actual_gross': share_actual_gross.quantize(Decimal('0.01')),
                'share_actual': share_actual,
                'share_theoretical': share_theoretical,
                'share_regular': share_regular,
                'share_late': share_late,
                'gains_regular': reg_g,
                'gains_late': late_g,
                'total_sessions': course_sessions_count,
                'taught_sessions': course_sessions_taught,
                'substituted_sessions': course_sessions_count - course_sessions_taught,
            })
            
        # Substitution earnings for percentage teacher
        substitution_earnings = Decimal('0.00')
        substitution_details = []
        for s in substitute_sessions:
            if teacher.session_rate:
                amount = teacher.session_rate
            elif teacher.hourly_rate:
                amount = (Decimal(str(s.duration_hours())) * teacher.hourly_rate).quantize(Decimal('0.01'))
            else:
                amount = Decimal('100.00')
            substitution_earnings += amount
            substitution_details.append({
                'session': s,
                'amount': amount,
                'hours': s.duration_hours(),
            })

        total_share_actual_net = sum(c['share_actual'] for c in courses_breakdown)
        salary_taught = total_share_actual_net + substitution_earnings
        salary_theoretical = sum(c['share_theoretical'] for c in courses_breakdown)

        total_active_students = sum(c.get('student_count', 0) for c in courses_breakdown)
        total_paid_students = sum(c.get('paid_count', 0) for c in courses_breakdown)
        total_unpaid_students = sum(c.get('unpaid_count', 0) for c in courses_breakdown)
        global_recovery_rate = round((total_paid_students / total_active_students * 100), 1) if total_active_students > 0 else 0.0
        
        return {
            'scheduled_hours': total_scheduled_hours,
            'taught_hours': total_taught_hours,
            'total_hours': total_taught_hours,
            'salary_scheduled': salary_theoretical,
            'salary_taught': salary_taught,
            'earnings': salary_taught,
            'salary_regular': total_share_regular,
            'salary_late': total_share_late,
            'substitution_earnings': substitution_earnings,
            'substitution_details': substitution_details,
            'courses': courses.filter(is_active=True).count(),
            'payment_method': 'PERCENTAGE',
            'payment_percentage': teacher.payment_percentage,
            'gains_actual': total_gains_actual,
            'gains_theoretical': total_gains_theoretical,
            'courses_breakdown': courses_breakdown,
            'months_covered': len(months),
            'own_sessions_count': own_sessions.count(),
            'substitute_sessions_count': substitute_sessions.count(),
            'total_active_students': total_active_students,
            'total_paid_students': total_paid_students,
            'total_unpaid_students': total_unpaid_students,
            'global_recovery_rate': global_recovery_rate,
            'total_group_revenue': total_gains_actual,
        }
    elif teacher.payment_method == 'SESSION':
        total_scheduled_sessions = 0
        
        for course in courses.filter(is_active=True):
            scheduled_sessions_qs = Session.objects.filter(
                group=course,
                date__range=[start_date, end_date]
            ).exclude(status='CANCELLED')
            total_scheduled_sessions += scheduled_sessions_qs.count()
            
        session_rate = teacher.session_rate or Decimal('0.00')
        salary_taught = (Decimal(total_taught_sessions) * session_rate).quantize(Decimal('0.01'))
        salary_scheduled = (Decimal(total_scheduled_sessions) * session_rate).quantize(Decimal('0.01'))
        
        return {
            'scheduled_hours': total_scheduled_hours,
            'taught_hours': total_taught_hours,
            'total_hours': total_taught_hours,
            'scheduled_sessions': total_scheduled_sessions,
            'taught_sessions': total_taught_sessions,
            'salary_scheduled': salary_scheduled,
            'salary_taught': salary_taught,
            'earnings': salary_taught,
            'courses': courses.filter(is_active=True).count(),
            'payment_method': 'SESSION',
            'session_rate': session_rate,
            'own_sessions_count': own_sessions.count(),
            'substitute_sessions_count': substitute_sessions.count(),
        }
    else:
        hourly_rate = teacher.hourly_rate or Decimal('0.00')
        salary_scheduled = (total_scheduled_hours * hourly_rate).quantize(Decimal('0.01'))
        salary_taught = (total_taught_hours * hourly_rate).quantize(Decimal('0.01'))
        
        return {
            'scheduled_hours': total_scheduled_hours,
            'taught_hours': total_taught_hours,
            'total_hours': total_taught_hours,
            'salary_scheduled': salary_scheduled,
            'salary_taught': salary_taught,
            'earnings': salary_taught,
            'courses': courses.filter(is_active=True).count(),
            'payment_method': 'HOURLY',
            'hourly_rate': hourly_rate,
            'own_sessions_count': own_sessions.count(),
            'substitute_sessions_count': substitute_sessions.count(),
        }


def generate_teacher_payslip_data(teacher, month: int, year: int) -> Dict:
    """
    Génère les données complètes pour une fiche de paie professeur
    """
    first_day, last_day = get_month_period(year, month)
    hours_data = calculate_teacher_hours(teacher, first_day, last_day)
    
    return {
        'teacher': teacher,
        'month': month_name_fr(month),
        'year': year,
        'period': f"{first_day.strftime('%d/%m/%Y')} - {last_day.strftime('%d/%m/%Y')}",
        'hourly_rate': teacher.hourly_rate if teacher.payment_method == 'HOURLY' else Decimal('0.00'),
        **hours_data
    }


# ==================== DÉTECTION DE CONFLITS ====================

def check_schedule_conflicts(room, schedule_day: str, start_time, end_time, exclude_schedule_id: Optional[int] = None) -> List:
    """
    Vérifie s'il y a des conflits d'horaire dans une salle pour les schedules
    
    Returns:
        Liste des horaires en conflit
    """
    from .models import CourseGroupSchedule
    
    conflicts = CourseGroupSchedule.objects.filter(
        room=room,
        day=schedule_day,
        course_group__is_active=True
    )
    
    if exclude_schedule_id:
        conflicts = conflicts.exclude(id=exclude_schedule_id)
    
    conflicting_schedules = []
    
    for sch in conflicts:
        # Vérifier chevauchement horaire
        if (start_time < sch.end_time and end_time > sch.start_time):
            conflicting_schedules.append(sch)
    
    return conflicting_schedules


def check_teacher_schedule_conflicts(teacher, schedule_day: str, start_time, end_time, exclude_schedule_id: Optional[int] = None) -> List:
    """
    Vérifie s'il y a des conflits d'horaire pour un professeur dans les schedules
    
    Returns:
        Liste des horaires en conflit
    """
    from .models import CourseGroupSchedule
    if not teacher:
        return []
        
    conflicts = CourseGroupSchedule.objects.filter(
        course_group__teacher=teacher,
        day=schedule_day,
        course_group__is_active=True
    )
    
    if exclude_schedule_id:
        conflicts = conflicts.exclude(id=exclude_schedule_id)
        
    conflicting_schedules = []
    
    for sch in conflicts:
        if (start_time < sch.end_time and end_time > sch.start_time):
            conflicting_schedules.append(sch)
            
    return conflicting_schedules


def _time_overlaps(start_a, end_a, start_b, end_b) -> bool:
    return start_a < end_b and end_a > start_b


def _get_effective_teacher(obj) -> Optional[object]:
    if obj is None:
        return None
    substitute_teacher = getattr(obj, 'substitute_teacher', None)
    if substitute_teacher is not None:
        return substitute_teacher
    group = getattr(obj, 'group', None)
    if group is None:
        return None
    return getattr(group, 'teacher', None)


def _detect_schedule_conflicts(schedules) -> List[dict]:
    conflicts = []
    for i, sch1 in enumerate(schedules):
        for sch2 in schedules[i + 1:]:
            if sch1.day != sch2.day:
                continue
            if not _time_overlaps(sch1.start_time, sch1.end_time, sch2.start_time, sch2.end_time):
                continue

            if sch1.room_id == sch2.room_id:
                conflicts.append({
                    'type': 'ROOM',
                    'severity': 'critical',
                    'entity': sch1.room,
                    'sch1': sch1,
                    'sch2': sch2,
                    'description': f"La salle '{sch1.room.name}' est réservée en double le {sch1.get_day_display()} de {sch1.start_time.strftime('%H:%M')} à {sch1.end_time.strftime('%H:%M')}."
                })

            teacher1 = getattr(sch1.course_group, 'teacher', None)
            teacher2 = getattr(sch2.course_group, 'teacher', None)
            if teacher1 and teacher2 and teacher1.id == teacher2.id:
                conflicts.append({
                    'type': 'TEACHER',
                    'severity': 'critical',
                    'entity': teacher1,
                    'sch1': sch1,
                    'sch2': sch2,
                    'description': f"Le professeur '{teacher1.name}' est affecté à deux cours le {sch1.get_day_display()} de {sch1.start_time.strftime('%H:%M')} à {sch1.end_time.strftime('%H:%M')}."
                })

    return conflicts


def _detect_schedule_availability_conflicts(schedules, availability_map) -> List[dict]:
    conflicts = []
    for sch in schedules:
        teacher = getattr(sch.course_group, 'teacher', None)
        if not teacher:
            continue

        availability_entries = availability_map.get((teacher.id, sch.day), [])
        if not availability_entries:
            continue

        unavailable_entries = [entry for entry in availability_entries if not entry.is_available]
        for availability_entry in unavailable_entries:
            if _time_overlaps(sch.start_time, sch.end_time, availability_entry.start_time, availability_entry.end_time):
                conflicts.append({
                    'type': 'TEACHER_UNAVAILABLE',
                    'severity': 'warning',
                    'entity': teacher,
                    'sch1': sch,
                    'description': f"Le professeur '{teacher.name}' est indisponible le {sch.get_day_display()} de {availability_entry.start_time.strftime('%H:%M')} à {availability_entry.end_time.strftime('%H:%M')}."
                })

        available_entries = [entry for entry in availability_entries if entry.is_available]
        if available_entries and not any(
            sch.start_time >= entry.start_time and sch.end_time <= entry.end_time
            for entry in available_entries
        ):
            conflicts.append({
                'type': 'TEACHER_OUT_OF_BOUNDS',
                'severity': 'warning',
                'entity': teacher,
                'sch1': sch,
                'description': f"L'horaire du groupe '{sch.course_group.name}' est planifié en dehors des heures de disponibilité du professeur '{teacher.name}'."
            })

    return conflicts


def _detect_session_conflicts(sessions) -> List[dict]:
    conflicts = []
    for i, sess1 in enumerate(sessions):
        for sess2 in sessions[i + 1:]:
            if sess1.date != sess2.date:
                continue
            if not _time_overlaps(sess1.start_time, sess1.end_time, sess2.start_time, sess2.end_time):
                continue

            if sess1.room_id == sess2.room_id:
                conflicts.append({
                    'type': 'ROOM',
                    'severity': 'critical',
                    'entity': sess1.room,
                    'session1': sess1,
                    'session2': sess2,
                    'description': f"La salle '{sess1.room.name}' est réservée en double le {sess1.date.strftime('%d/%m/%Y')} de {sess1.start_time.strftime('%H:%M')} à {sess1.end_time.strftime('%H:%M')}."
                })

            teacher1 = _get_effective_teacher(sess1)
            teacher2 = _get_effective_teacher(sess2)
            if teacher1 and teacher2 and teacher1.id == teacher2.id:
                conflicts.append({
                    'type': 'TEACHER',
                    'severity': 'critical',
                    'entity': teacher1,
                    'session1': sess1,
                    'session2': sess2,
                    'description': f"Le professeur '{teacher1.name}' est affecté à deux cours le {sess1.date.strftime('%d/%m/%Y')} de {sess1.start_time.strftime('%H:%M')} à {sess1.end_time.strftime('%H:%M')}.",
                })

    return conflicts


def _detect_session_availability_conflicts(sessions, availability_map, leave_map) -> List[dict]:
    conflicts = []
    day_map = {0: 'MON', 1: 'TUE', 2: 'WED', 3: 'THU', 4: 'FRI', 5: 'SAT', 6: 'SUN'}
    for sess in sessions:
        teacher = _get_effective_teacher(sess)
        if not teacher:
            continue

        for leave in leave_map.get(teacher.id, []):
            if leave.start_date <= sess.date <= leave.end_date:
                conflicts.append({
                    'type': 'TEACHER_LEAVE',
                    'severity': 'critical',
                    'entity': teacher,
                    'session1': sess,
                    'description': f"Le professeur '{teacher.name}' est en congé le {sess.date.strftime('%d/%m/%Y')} (Motif: {leave.get_leave_type_display()})."
                })

        availability_entries = availability_map.get((teacher.id, day_map[sess.date.weekday()]), [])
        if not availability_entries:
            continue

        unavailable_entries = [entry for entry in availability_entries if not entry.is_available]
        for availability_entry in unavailable_entries:
            if _time_overlaps(sess.start_time, sess.end_time, availability_entry.start_time, availability_entry.end_time):
                conflicts.append({
                    'type': 'TEACHER_UNAVAILABLE',
                    'severity': 'warning',
                    'entity': teacher,
                    'session1': sess,
                    'description': f"Le professeur '{teacher.name}' est indisponible le {sess.date.strftime('%d/%m/%Y')} de {availability_entry.start_time.strftime('%H:%M')} à {availability_entry.end_time.strftime('%H:%M')}."
                })

        available_entries = [entry for entry in availability_entries if entry.is_available]
        if available_entries and not any(
            sess.start_time >= entry.start_time and sess.end_time <= entry.end_time
            for entry in available_entries
        ):
            conflicts.append({
                'type': 'TEACHER_OUT_OF_BOUNDS',
                'severity': 'warning',
                'entity': teacher,
                'session1': sess,
                'description': f"La séance du {sess.date.strftime('%d/%m/%Y')} est planifiée en dehors des heures de disponibilité du professeur '{teacher.name}'."
            })

    return conflicts


def _detect_capacity_warnings(schedules, annotated_sessions, student_counts_map) -> List[dict]:
    warnings = []
    for sch in schedules:
        student_count = student_counts_map.get(sch.course_group_id, 0)
        if student_count > sch.room.capacity:
            overflow = student_count - sch.room.capacity
            warnings.append({
                'context': 'SCHEDULE',
                'severity': 'warning',
                'course': sch.course_group,
                'schedule': sch,
                'room': sch.room,
                'enrolled': student_count,
                'capacity': sch.room.capacity,
                'overflow': overflow,
                'description': f"Le groupe '{sch.course_group.name}' compte {student_count} élèves inscrits, ce qui dépasse la capacité de la salle '{sch.room.name}' ({sch.room.capacity} places) le {sch.get_day_display()}."
            })

    for sess in annotated_sessions:
        if getattr(sess, 'has_capacity_alert', False):
            student_count = getattr(sess, 'student_count', student_counts_map.get(sess.group_id, 0))
            overflow = student_count - sess.room.capacity
            warnings.append({
                'context': 'SESSION',
                'severity': 'warning',
                'session': sess,
                'course': sess.group,
                'room': sess.room,
                'enrolled': student_count,
                'capacity': sess.room.capacity,
                'overflow': overflow,
                'description': f"La session du {sess.date.strftime('%d/%m/%Y')} pour '{sess.group.name}' compte {student_count} élèves inscrits, ce qui dépasse la capacité de la salle '{sess.room.name}' ({sess.room.capacity} places)."
            })

    return warnings


def _detect_student_overlap_conflicts(schedules_list) -> List[dict]:
    """
    Detect students enrolled in two groups whose weekly schedules overlap on the same day.
    Returns one conflict entry per (student, sch1, sch2) pair.
    """
    from .models import Enrollment
    conflicts = []
    # Build map: group_id -> list of schedules
    group_schedules = {}
    for sch in schedules_list:
        group_schedules.setdefault(sch.course_group_id, []).append(sch)

    group_ids = list(group_schedules.keys())
    if len(group_ids) < 2:
        return []

    # Fetch active enrollments for these groups
    enrollments = (
        Enrollment.objects
        .filter(course_group_id__in=group_ids, is_active=True, student__is_active=True)
        .select_related('student', 'course_group')
    )

    # Map student -> list of enrolled group_ids
    student_groups: dict = {}
    for enr in enrollments:
        student_groups.setdefault(enr.student_id, {'student': enr.student, 'groups': []})['groups'].append(enr.course_group_id)

    seen = set()
    for student_id, data in student_groups.items():
        student = data['student']
        grp_ids = data['groups']
        if len(grp_ids) < 2:
            continue
        # Pairwise schedule overlap check
        for i in range(len(grp_ids)):
            for j in range(i + 1, len(grp_ids)):
                schs_a = group_schedules.get(grp_ids[i], [])
                schs_b = group_schedules.get(grp_ids[j], [])
                for sch_a in schs_a:
                    for sch_b in schs_b:
                        if sch_a.day != sch_b.day:
                            continue
                        if not _time_overlaps(sch_a.start_time, sch_a.end_time, sch_b.start_time, sch_b.end_time):
                            continue
                        key = (student_id, min(sch_a.id, sch_b.id), max(sch_a.id, sch_b.id))
                        if key in seen:
                            continue
                        seen.add(key)
                        conflicts.append({
                            'type': 'STUDENT_OVERLAP',
                            'severity': 'warning',
                            'entity': student,
                            'sch1': sch_a,
                            'sch2': sch_b,
                            'description': (
                                f"L'élève '{student.name}' est inscrit dans '{sch_a.course_group.name}' "
                                f"et '{sch_b.course_group.name}' qui se chevauchent "
                                f"le {sch_a.get_day_display()} de "
                                f"{max(sch_a.start_time, sch_b.start_time).strftime('%H:%M')} à "
                                f"{min(sch_a.end_time, sch_b.end_time).strftime('%H:%M')}."
                            )
                        })
    return conflicts


def detect_all_conflicts(past_days: int = 14, future_days: int = 30) -> Dict[str, List]:
    """
    Scans the database and returns all schedule, session, capacity, and student overlap conflicts.

    Args:
        past_days: how many days back to scan for PLANNED/DONE sessions (default 14)
        future_days: how many days forward to scan (default 30)
    """
    from collections import defaultdict
    from .models import CourseGroupSchedule, Session, TeacherAvailability, TeacherLeave, Enrollment
    from django.db.models import Count
    from datetime import timedelta

    schedule_conflicts = []
    session_conflicts = []
    capacity_warnings = []
    student_conflicts = []

    schedules = CourseGroupSchedule.objects.filter(course_group__is_active=True).select_related(
        'course_group', 'course_group__teacher', 'room'
    )
    schedules_list = list(schedules)

    schedule_conflicts.extend(_detect_schedule_conflicts(schedules_list))

    # Student enrollment overlap detection (weekly schedule level)
    student_conflicts.extend(_detect_student_overlap_conflicts(schedules_list))

    teacher_ids = {sch.course_group.teacher_id for sch in schedules_list if getattr(sch.course_group, 'teacher_id', None)}
    availability_entries = TeacherAvailability.objects.filter(teacher_id__in=teacher_ids).select_related('teacher')
    availability_map = defaultdict(list)
    for entry in availability_entries:
        availability_map[(entry.teacher_id, entry.day)].append(entry)

    schedule_conflicts.extend(_detect_schedule_availability_conflicts(schedules_list, availability_map))

    # Widen session window: past_days back through future_days forward
    # Also always include any past PLANNED sessions (missed/forgotten sessions)
    today = timezone.now().date()
    window_start = today - timedelta(days=past_days)
    window_end = today + timedelta(days=future_days)

    sessions_qs = (
        Session.objects
        .filter(date__gte=window_start, date__lte=window_end)
        .exclude(status='CANCELLED')
        .select_related('group', 'group__teacher', 'substitute_teacher', 'room')
        .prefetch_related('group__students')
    )
    annotated_sessions = _annotate_conflicts(sessions_qs)

    session_conflicts.extend(_detect_session_conflicts(annotated_sessions))

    # Expand teacher_ids to include substitute teachers in sessions
    session_teacher_ids = set(teacher_ids)
    for sess in annotated_sessions:
        if sess.substitute_teacher_id:
            session_teacher_ids.add(sess.substitute_teacher_id)
        if sess.group and getattr(sess.group, 'teacher_id', None):
            session_teacher_ids.add(sess.group.teacher_id)

    leave_entries = []
    if session_teacher_ids:
        leave_entries = TeacherLeave.objects.filter(teacher_id__in=session_teacher_ids).select_related('teacher')
    leave_map = defaultdict(list)
    for leave in leave_entries:
        leave_map[leave.teacher_id].append(leave)

    # Refresh availability map to include substitute teachers
    if session_teacher_ids - teacher_ids:
        extra_avail = TeacherAvailability.objects.filter(
            teacher_id__in=session_teacher_ids - teacher_ids
        ).select_related('teacher')
        for entry in extra_avail:
            availability_map[(entry.teacher_id, entry.day)].append(entry)

    session_conflicts.extend(_detect_session_availability_conflicts(annotated_sessions, availability_map, leave_map))

    student_counts_map = {}
    group_ids = {sch.course_group_id for sch in schedules_list}
    group_ids.update(getattr(sess.group, 'id', None) for sess in annotated_sessions if getattr(sess, 'group', None) is not None)
    group_ids = {group_id for group_id in group_ids if group_id is not None}
    if group_ids:
        enrollment_counts = (
            Enrollment.objects.filter(course_group_id__in=group_ids, is_active=True, student__is_active=True)
            .values('course_group_id')
            .annotate(count=Count('id'))
        )
        student_counts_map = {item['course_group_id']: item['count'] for item in enrollment_counts}

    capacity_warnings.extend(_detect_capacity_warnings(schedules_list, annotated_sessions, student_counts_map))

    total_count = len(schedule_conflicts) + len(session_conflicts) + len(capacity_warnings) + len(student_conflicts)
    return {
        'schedule_conflicts': schedule_conflicts,
        'session_conflicts': session_conflicts,
        'capacity_warnings': capacity_warnings,
        'student_conflicts': student_conflicts,
        'total_count': total_count,
        'scan_window_start': window_start,
        'scan_window_end': window_end,
    }




def get_room_availability(room, target_day: str) -> List[Dict]:
    """
    Retourne les créneaux occupés d'une salle pour un jour donné
    """
    from .models import CourseGroupSchedule
    
    occupied_schedules = CourseGroupSchedule.objects.filter(
        room=room,
        day=target_day,
        course_group__is_active=True
    ).order_by('start_time')
    
    availability = []
    
    for sch in occupied_schedules:
        availability.append({
            'start': sch.start_time.strftime('%H:%M'),
            'end': sch.end_time.strftime('%H:%M'),
            'available': False,
            'course': sch.course_group
        })
    
    return availability


def generate_sessions_from_coursegroups(start_date: date, end_date: date, force: bool = False, course: Optional[CourseGroup] = None, ignore_academic_calendar: bool = False) -> Dict:
    """Create/update/delete Session objects based on CourseGroup schedules and per-date exceptions.

    Args:
        start_date: inclusive start date
        end_date: inclusive end date
        force: if True, update existing sessions when times/room differ
        course: optional specific CourseGroup to generate/sync sessions for
        ignore_academic_calendar: if True, bypass academic calendar checks

    Returns a summary dict: {'created', 'updated', 'deleted', 'skipped', 'errors'}
    """
    from .models import CourseGroup, Session, CourseGroupSchedule, Holiday, AcademicCalendarPeriod, RecurringException
    from datetime import timedelta
    from django.core.exceptions import ValidationError

    DAY_MAP = {
        'MON': 0, 'TUE': 1, 'WED': 2, 'THU': 3,
        'FRI': 4, 'SAT': 5, 'SUN': 6
    }

    summary = {'created': 0, 'updated': 0, 'deleted': 0, 'skipped': 0, 'errors': []}

    # ------------------------------------------------------------------
    # Pre-load holiday data into memory (one query, zero inner-loop hits)
    # ------------------------------------------------------------------
    holidays_qs = Holiday.objects.filter(
        date__range=[start_date, end_date]
    ).prefetch_related('affected_groups')

    # Dates that block ALL groups
    global_holiday_dates: set = set()
    # Dates that block specific groups: {date: {group_id, ...}}
    group_holiday_dates: dict = {}

    for h in holidays_qs:
        if h.affects_all:
            global_holiday_dates.add(h.date)
        else:
            group_ids = set(h.affected_groups.values_list('id', flat=True))
            if group_ids:
                group_holiday_dates.setdefault(h.date, set()).update(group_ids)

    acad_periods = []
    rec_exceptions = []
    if not ignore_academic_calendar:
        acad_periods = list(AcademicCalendarPeriod.objects.filter(
            start_date__lte=end_date,
            end_date__gte=start_date,
            is_active=True
        ).prefetch_related('affected_groups'))
        rec_exceptions = list(RecurringException.objects.filter(is_available=False))

    # Clean up sessions for inactive groups
    if course:
        courses_to_clean = [course] if not course.is_active else []
    else:
        courses_to_clean = CourseGroup.objects.filter(is_active=False)

    for c in courses_to_clean:
        to_delete = Session.objects.filter(
            group=c,
            date__range=[start_date, end_date],
            status='PLANNED',
            is_manually_edited=False
        )
        for s in to_delete:
            try:
                s.delete()
                summary['deleted'] += 1
            except Exception as e:
                summary['errors'].append(f"Failed to delete session for inactive group {c.name} on {s.date}: {e}")

    # Determine which active courses to generate sessions for
    if course:
        courses = [course] if course.is_active else []
    else:
        courses = CourseGroup.objects.filter(is_active=True).prefetch_related('schedules', 'teacher')

    for active_course in courses:
        # Get active schedules for this course
        schedules = active_course.schedules.all()
        
        # 1. Clean up sessions that don't match any schedule slot (orphaned sessions)
        active_sessions = Session.objects.filter(
            group=active_course,
            date__range=[start_date, end_date],
            status='PLANNED',
            is_manually_edited=False
        )
        
        for s in active_sessions:
            matching_schedule = None
            for sch in schedules:
                if s.schedule == sch:
                    matching_schedule = sch
                    break
                # Fallback matching by weekday and time
                if s.date.weekday() == DAY_MAP.get(sch.day) and s.start_time == sch.start_time and s.end_time == sch.end_time:
                    if not s.schedule:
                        s.schedule = sch
                        s.save()
                    matching_schedule = sch
                    break
            
            if not matching_schedule:
                try:
                    s.delete()
                    summary['deleted'] += 1
                except Exception as e:
                    summary['errors'].append(f"Failed to delete orphaned session for {active_course.name} on {s.date}: {e}")

        # 2. Generate/update sessions for each schedule slot
        for sch in schedules:
            target_weekday = DAY_MAP.get(sch.day)
            if target_weekday is None:
                continue

            # first date in range matching the schedule's weekday
            days_ahead = (target_weekday - start_date.weekday()) % 7
            current = start_date + timedelta(days=days_ahead)

            while current <= end_date:
                # ----------------------------------------------------------
                # Holiday & Academic Period suppression: skip if date is blocked
                # ----------------------------------------------------------
                if current in global_holiday_dates:
                    current += timedelta(days=7)
                    continue
                if active_course.id in group_holiday_dates.get(current, set()):
                    current += timedelta(days=7)
                    continue

                if not ignore_academic_calendar:
                    is_calendar_blocked = False
                    for period in acad_periods:
                        if period.start_date <= current <= period.end_date:
                            if period.affects_all or active_course.id in period.affected_groups.values_list('id', flat=True):
                                is_calendar_blocked = True
                                break
                    if is_calendar_blocked:
                        current += timedelta(days=7)
                        continue

                    is_exception_blocked = False
                    teacher_id = active_course.teacher_id
                    room_id = sch.room_id
                    
                    for exc in rec_exceptions:
                        if exc.target_type == 'TEACHER' and exc.teacher_id == teacher_id:
                            if exc.matches_date_and_time(current, sch.start_time, sch.end_time):
                                is_exception_blocked = True
                                break
                        if exc.target_type == 'ROOM' and exc.room_id == room_id:
                            if exc.matches_date_and_time(current, sch.start_time, sch.end_time):
                                is_exception_blocked = True
                                break
                                
                    if is_exception_blocked:
                        current += timedelta(days=7)
                        continue

                # determine effective values
                eff_room = sch.room
                eff_start = sch.start_time
                eff_end = sch.end_time

                existing = Session.objects.filter(group=active_course, date=current, schedule=sch).first()
                if not existing:
                    existing = Session.objects.filter(group=active_course, date=current, start_time=sch.start_time, end_time=sch.end_time).first()
                    if existing and not existing.schedule:
                        existing.schedule = sch
                        existing.save()

                if existing:
                    if existing.is_manually_edited or existing.status in ['DONE', 'CANCELLED']:
                        summary['skipped'] += 1
                        current += timedelta(days=7)
                        continue

                    needs_update = (
                        existing.start_time != eff_start or
                        existing.end_time != eff_end or
                        existing.room != eff_room
                    )
                    if needs_update and force:
                        existing.start_time = eff_start
                        existing.end_time = eff_end
                        existing.room = eff_room
                        try:
                            existing.save()
                            summary['updated'] += 1
                        except ValidationError as ve:
                            summary['errors'].append(f"{active_course.name} {current}: {ve}")
                    else:
                        summary['skipped'] += 1
                else:
                    # create
                    try:
                        new = Session(
                            group=active_course,
                            schedule=sch,
                            date=current,
                            start_time=eff_start,
                            end_time=eff_end,
                            room=eff_room
                        )
                        new.save()
                        summary['created'] += 1
                    except ValidationError as ve:
                        summary['errors'].append(f"{active_course.name} {current}: {ve}")
                    except Exception as e:
                        summary['errors'].append(f"{active_course.name} {current}: {e}")

                current += timedelta(days=7)

    return summary


def auto_generate_future_sessions():
    """Checks if the maximum future session date is less than 2 weeks away.
    If so, generates sessions for the next 4 weeks to keep the calendar populated.
    Caches the check in-memory for 1 hour to prevent redundant scans on every page load.
    """
    from django.core.cache import cache
    if cache.get('future_sessions_checked'):
        return

    from .models import Session
    from django.db.models import Max
    from datetime import timedelta
    
    today = timezone.now().date()
    max_date = Session.objects.aggregate(Max('date'))['date__max']
    
    # If there are no future sessions or the max date is within 2 weeks, auto-extend by 4 weeks
    if not max_date or max_date < today + timedelta(weeks=2):
        end_date = today + timedelta(weeks=4)
        generate_sessions_from_coursegroups(today, end_date, force=False)

    cache.set('future_sessions_checked', True, 3600)


# ==================== GÉNÉRATION DE STATISTIQUES ====================

def get_dashboard_stats() -> Dict:
    """
    Génère toutes les statistiques pour le dashboard principal
    """
    from .models import Student, Teacher, CourseGroup, Payment, Room, CourseGroupSchedule
    
    today = timezone.now().date()
    current_month = today.replace(day=1)
    
    # Statistiques générales
    active_students = Student.objects.filter(is_active=True).count()
    active_teachers = Teacher.objects.filter(is_active=True).count()
    active_courses = CourseGroup.objects.filter(is_active=True).count()
    active_rooms = Room.objects.filter(is_active=True).count()
    
    # Statistiques financières
    today_revenue = get_daily_revenue(today)
    month_revenue = get_monthly_revenue(today.year, today.month)
    
    # Élèves impayés
    unpaid = get_unpaid_students(current_month)
    unpaid_count = len(unpaid)
    unpaid_amount = sum([u['remaining'] for u in unpaid])
    
    # Conflits de planning (unused on dashboard, set empty to avoid O(N^2) DB queries)
    conflicts = []
            
    # Past planned sessions (uncompleted)
    from .models import Session
    past_planned_count = Session.objects.filter(date__lt=today, status='PLANNED').count()
    
    return {
        'counts': {
            'students': active_students,
            'teachers': active_teachers,
            'courses': active_courses,
            'rooms': active_rooms
        },
        'revenue': {
            'today': today_revenue,
            'month': month_revenue,
        },
        'alerts': {
            'unpaid_count': unpaid_count,
            'unpaid_amount': unpaid_amount,
            'conflicts': conflicts,
            'unpaid_students': unpaid,
            'past_planned_count': past_planned_count,
        }
    }


# ==================== GÉNÉRATION DE REÇUS PDF ====================

def generate_receipt_pdf(payment) -> BytesIO:
    """
    Génère un reçu de paiement en format PDF (A5 ou thermique)
    """
    buffer = BytesIO()
    
    # Créer le PDF en format A5 (148 x 210 mm)
    p = canvas.Canvas(buffer, pagesize=A5)
    width, height = A5
    
    # En-tête
    p.setFont("Helvetica-Bold", 16)
    p.drawCentredString(width/2, height - 30, "REÇU DE PAIEMENT")
    
    # Numéro de reçu
    p.setFont("Helvetica", 10)
    p.drawString(30, height - 60, f"Reçu N° : {payment.receipt_number}")
    p.drawString(30, height - 75, f"Date : {payment.payment_date.strftime('%d/%m/%Y')}")
    
    # Ligne séparatrice
    p.line(30, height - 85, width - 30, height - 85)
    
    # Informations élève
    y_position = height - 110
    p.setFont("Helvetica-Bold", 11)
    p.drawString(30, y_position, "ÉLÈVE :")
    
    p.setFont("Helvetica", 10)
    y_position -= 20
    p.drawString(40, y_position, f"Nom : {payment.student.name}")
    if payment.student.matricule:
        y_position -= 15
        p.drawString(40, y_position, f"Matricule : {payment.student.matricule}")
    y_position -= 15
    p.drawString(40, y_position, f"Contact Parent : {payment.student.parent_contact}")
    
    # Ligne séparatrice
    y_position -= 10
    p.line(30, y_position, width - 30, y_position)
    
    # Détails du paiement
    y_position -= 25
    p.setFont("Helvetica-Bold", 11)
    p.drawString(30, y_position, "DÉTAILS DU PAIEMENT :")
    
    p.setFont("Helvetica", 10)
    y_position -= 20
    p.drawString(40, y_position, f"Mois couvert : {format_date_fr(payment.month_covered)}")
    y_position -= 15
    p.drawString(40, y_position, f"Mode de paiement : {payment.get_payment_method_display()}")
    
    # Montant (en gros)
    y_position -= 30
    p.setFont("Helvetica-Bold", 14)
    p.drawString(30, y_position, "MONTANT PAYÉ :")
    p.setFont("Helvetica-Bold", 18)
    currency = get_setting('CURRENCY_SYMBOL', 'DH')
    p.drawString(width - 150, y_position, f"{payment.amount} {currency}")
    
    # Ligne séparatrice
    y_position -= 15
    p.line(30, y_position, width - 30, y_position)
    
    # Groupes inscrits
    y_position -= 25
    p.setFont("Helvetica-Bold", 10)
    p.drawString(30, y_position, "Groupes inscrits :")
    
    p.setFont("Helvetica", 9)
    enrollments = payment.student.enrollment_set.filter(is_active=True)
    month_covered = payment.month_covered
    for enrollment in enrollments[:5]:  # Max 5 pour ne pas déborder
        y_position -= 12
        is_prorated = False
        if month_covered and enrollment.enrolled_date.year == month_covered.year and enrollment.enrolled_date.month == month_covered.month:
            if enrollment.enrolled_date.day > 1:
                is_prorated = False if get_setting('ENABLE_PRORATION', 'True').lower() == 'false' else True
                
        if is_prorated:
            total_sess = count_scheduled_sessions_in_month(enrollment.course_group, month_covered.year, month_covered.month)
            rem_sess = count_remaining_sessions_in_month(enrollment.course_group, enrollment.enrolled_date)
            if total_sess > 0:
                sess_price = (enrollment.course_group.monthly_price / Decimal(total_sess)).quantize(Decimal('0.01'))
                prorated_price = (Decimal(rem_sess) * sess_price).quantize(Decimal('0.01'))
                import math
                prorated_price = Decimal(str(math.ceil(prorated_price / Decimal('10')))) * Decimal('10')
            else:
                sess_price = Decimal('0.00')
                prorated_price = Decimal('0.00')
            p.drawString(40, y_position, f"• {enrollment.course_group.name} (Proratisé: {rem_sess} séance{'' if rem_sess == 1 else 's'}) - {prorated_price} {currency}")
        else:
            p.drawString(40, y_position, f"• {enrollment.course_group.name} - {enrollment.course_group.monthly_price} {currency}")
    
    # Pied de page
    p.setFont("Helvetica-Oblique", 8)
    thank_you_note = get_setting('RECEIPT_FOOTER_THANK_YOU', 'Merci pour votre confiance ! - شكراً لثقتكم')
    p.drawCentredString(width/2, 40, thank_you_note)
    school_name = get_setting('SCHOOL_NAME', 'Centre')
    school_phone = get_setting('SCHOOL_PHONE', '')
    school_subtitle = get_setting('SCHOOL_SUBTITLE', 'Soutien Scolaire & Langues')
    p.drawCentredString(width/2, 28, f"{school_name} - {school_subtitle} - Tél: {school_phone}")

    
    # Finaliser
    p.showPage()
    p.save()
    
    buffer.seek(0)
    return buffer


def generate_schedule_pdf(sessions_list, title: str = "Planification") -> BytesIO:
    """
    Génère un PDF A4 listant les sessions fournies.
    sessions_list: iterable of Session objects (assumed ordered by date/time)
    """
    # Use ReportLab Platypus to build nicer tables
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    elements = []

    # Title
    elements.append(Paragraph(f"<b>{title}</b>", styles['Title']))
    elements.append(Paragraph(f"Généré le: {timezone.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal']))
    elements.append(Spacer(1, 12))

    # Group sessions by date
    from collections import defaultdict
    grouped = defaultdict(list)
    for s in sessions_list:
        grouped[s.date].append(s)

    header_style = ['Heure', 'Groupe', 'Professeur', 'Salle', 'Élèves']

    for date in sorted(grouped.keys()):
        day_name = FRENCH_DAYS[date.strftime("%A")]
        date_str = f"{day_name} {date.strftime('%d/%m/%Y')}"
        elements.append(Paragraph(f"<b>{date_str}</b>", styles['Heading3']))
        data = [header_style]
        day_sessions = sorted(grouped[date], key=lambda x: (x.start_time, x.end_time))
        for s in day_sessions:
            time_range = f"{s.start_time.strftime('%H:%M')}-{s.end_time.strftime('%H:%M')}"
            group_name = s.group.name if s.group else ''
            teacher = s.group.teacher.name if s.group and s.group.teacher else (s.group.teacher.name if getattr(s, 'group', None) and getattr(s.group, 'teacher', None) else '')
            room = s.room.name if s.room else ''
            try:
                students_count = s.group.students.count() if s.group else 0
            except Exception:
                students_count = ''
            status = s.status
            row = [time_range, group_name, teacher, room, str(students_count)]
            data.append(row)

        table = Table(data, colWidths=[80, 170, 140, 90, 60])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f0f0f0')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.black),
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('FONTSIZE', (0,0), (-1,-1), 9),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ]))

        elements.append(table)
        elements.append(Spacer(1, 12))

    doc.build(elements)
    buffer.seek(0)
    return buffer

def generate_student_schedule_pdf(sessions_list, student_name: str, title: str = None) -> BytesIO:
    """
    Génère un PDF A4 listant l'emploi du temps d'un élève.
    sessions_list: iterable of Session objects (assumed ordered by date/time)
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet
    from collections import defaultdict

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36
    )
    styles = getSampleStyleSheet()
    elements = []

    # Title
    display_title = title or f"Planification — {student_name}"
    elements.append(Paragraph(f"<b>{display_title}</b>", styles['Title']))
    elements.append(Paragraph(f"Généré le: {timezone.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal']))
    elements.append(Spacer(1, 12))

    if not sessions_list:
        elements.append(Paragraph("Aucune séance prévue pour cette période.", styles['Normal']))
        doc.build(elements)
        buffer.seek(0)
        return buffer

    grouped = defaultdict(list)
    for s in sessions_list:
        grouped[s.date].append(s)

    header_row = ['Heure', 'Cours', 'Professeur', 'Salle']

    for date in sorted(grouped.keys()):
        day_name = FRENCH_DAYS[date.strftime("%A")]
        date_str = f"{day_name} {date.strftime('%d/%m/%Y')}"
        elements.append(Paragraph(f"<b>{date_str}</b>", styles['Heading3']))

        data = [header_row]
        row_styles = []  # extra TableStyle commands per row (e.g. cancelled sessions)
        day_sessions = sorted(grouped[date], key=lambda x: (x.start_time, x.end_time))

        for i, s in enumerate(day_sessions, start=1):
            time_range = f"{s.start_time.strftime('%H:%M')}-{s.end_time.strftime('%H:%M')}"
            group_name = s.group.name if s.group else ''
            teacher = s.group.teacher.name if s.group and s.group.teacher else ''
            room = s.room.name if s.room else 'À définir'

            is_cancelled = getattr(s, 'status', None) == 'cancelled'
            if is_cancelled:
                group_name = f"{group_name} (Annulé)"
                row_styles.append(('TEXTCOLOR', (0, i), (-1, i), colors.red))

            data.append([time_range, group_name, teacher, room])

        table = Table(data, colWidths=[80, 190, 140, 90])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f0f0f0')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            *row_styles,
        ]))

        elements.append(table)
        elements.append(Spacer(1, 12))

    doc.build(elements)
    buffer.seek(0)
    return buffer


def generate_teacher_payslip_pdf(teacher, start_date, end_date, result) -> BytesIO:
    """
    Génère un bulletin de paie détaillé au format PDF pour un enseignant
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from django.conf import settings
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=40, rightMargin=40, topMargin=40, bottomMargin=40
    )
    styles = getSampleStyleSheet()
    
    # Custom styles
    DARK = colors.HexColor('#1a1a2e')
    ACCENT = colors.HexColor('#0f3460')
    
    title_style = ParagraphStyle(
        'PayslipTitle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=DARK,
        fontName='Helvetica-Bold',
        spaceAfter=4,
        leading=22,
        alignment=1, # Center
    )
    section_style = ParagraphStyle(
        'PayslipSection',
        parent=styles['Heading2'],
        fontSize=11,
        textColor=ACCENT,
        fontName='Helvetica-Bold',
        spaceBefore=10,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        'PayslipBody',
        parent=styles['Normal'],
        fontSize=9,
        textColor=DARK,
        fontName='Helvetica',
        leading=13,
    )
    bold_body_style = ParagraphStyle(
        'PayslipBoldBody',
        parent=body_style,
        fontName='Helvetica-Bold',
    )
    
    elements = []
    
    # 1. School Information & Header
    school_name = getattr(settings, 'SCHOOL_NAME', 'Centre')
    school_address = getattr(settings, 'SCHOOL_ADDRESS', '')
    school_phone = getattr(settings, 'SCHOOL_PHONE', '')
    school_email = getattr(settings, 'SCHOOL_EMAIL', '')
    
    header_data = [
        [
            Paragraph(f"<b>{school_name}</b><br/>{school_address}<br/>Tél: {school_phone}<br/>Email: {school_email}", body_style),
            Paragraph(f"<b>BULLETIN DE PAIE</b><br/>Période : {start_date.strftime('%d/%m/%Y')} au {end_date.strftime('%d/%m/%Y')}<br/>Date d'émission: {timezone.now().strftime('%d/%m/%Y')}", body_style)
        ]
    ]
    header_table = Table(header_data, colWidths=[260, 250])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
    ]))
    elements.append(header_table)
    elements.append(HRFlowable(width='100%', thickness=1.5, color=ACCENT, spaceBefore=4, spaceAfter=10))
    
    # 2. Teacher Profile info
    method_labels = {
        'PERCENTAGE': 'Part des gains (%)',
        'HOURLY': 'Taux horaire',
        'SESSION': 'Tarif par session'
    }
    rate_str = ""
    if teacher.payment_method == 'PERCENTAGE':
        rate_str = f"{teacher.payment_percentage}% de part des gains"
    elif teacher.payment_method == 'SESSION':
        rate_str = f"{teacher.session_rate} DH par session"
    else:
        rate_str = f"{teacher.hourly_rate} DH par heure"
        
    profile_data = [
        [
            Paragraph(f"<b>Enseignant :</b> {teacher.name}", body_style),
            Paragraph(f"<b>Téléphone :</b> {teacher.phone}", body_style)
        ],
        [
            Paragraph(f"<b>Mode de paiement :</b> {method_labels.get(teacher.payment_method, teacher.payment_method)}", body_style),
            Paragraph(f"<b>Taux/Tarif configuré :</b> {rate_str}", body_style)
        ]
    ]
    profile_table = Table(profile_data, colWidths=[260, 250])
    profile_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    elements.append(profile_table)
    elements.append(Spacer(1, 10))
    
    # 3. Calculations Details
    elements.append(Paragraph("DÉTAIL DU CALCUL DE LA RÉMUNÉRATION", section_style))
    
    calc_header = ['Élément', 'Quantité / Base', 'Taux / Part', 'Montant Brut']
    calc_rows = []
    
    if teacher.payment_method == 'PERCENTAGE':
        # List breakdown per group
        for item in result.get('courses_breakdown', []):
            course_name = item['course'].name
            total_gains = item['gains_actual']
            sessions_taught = item['taught_sessions']
            total_sess = item['total_sessions']
            share_net = item['share_actual']
            
            label = f"Part gains - {course_name} ({sessions_taught}/{total_sess} séances)"
            calc_rows.append([
                Paragraph(label, body_style),
                f"{total_gains:.2f} DH",
                f"{teacher.payment_percentage}%",
                f"{share_net:.2f} DH"
            ])
            
        # Substitution work
        sub_earnings = result.get('substitution_earnings', Decimal('0.00'))
        if sub_earnings > Decimal('0.00'):
            sub_count = result.get('substitute_sessions_count', 0)
            calc_rows.append([
                Paragraph(f"Remplacements effectués ({sub_count} séances)", body_style),
                f"{sub_count} séances",
                "—",
                f"{sub_earnings:.2f} DH"
            ])
    elif teacher.payment_method == 'SESSION':
        own_count = result.get('own_sessions_count', 0)
        sub_count = result.get('substitute_sessions_count', 0)
        rate = result.get('session_rate', Decimal('0.00'))
        
        calc_rows.append([
            Paragraph(f"Séances propres enseignées", body_style),
            f"{own_count} séances",
            f"{rate:.2f} DH",
            f"{(Decimal(own_count)*rate):.2f} DH"
        ])
        if sub_count > 0:
            calc_rows.append([
                Paragraph(f"Séances de remplacement enseignées", body_style),
                f"{sub_count} séances",
                f"{rate:.2f} DH",
                f"{(Decimal(sub_count)*rate):.2f} DH"
            ])
    else: # HOURLY
        hours = result.get('total_hours', Decimal('0.00'))
        rate = result.get('hourly_rate', Decimal('0.00'))
        calc_rows.append([
            Paragraph(f"Heures enseignées (Séances propres + Remplacements)", body_style),
            f"{hours:.1f} heures",
            f"{rate:.2f} DH/h",
            f"{(hours*rate):.2f} DH"
        ])
        
    # Build calculation table
    calc_table_data = [calc_header] + calc_rows
    calc_table = Table(calc_table_data, colWidths=[240, 100, 80, 90])
    calc_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#edf2f7')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.black),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (1,0), (-1,-1), 'RIGHT'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
    ]))
    elements.append(calc_table)
    elements.append(Spacer(1, 12))
    
    # 4. Payments Logged (Advances/Salary payouts)
    elements.append(Paragraph("HISTORIQUE DES PAIEMENTS ET AVANCES ENREGISTRÉS", section_style))
    
    pay_header = ['Date', 'Type de versement', 'Mode', 'Notes', 'Montant']
    pay_rows = []
    
    payments_qs = result.get('logged_payments', [])
    total_paid = Decimal('0.00')
    
    type_labels = {
        'ADVANCE': 'Avance / Acompte',
        'SALARY': 'Règlement de salaire',
        'ADJUSTMENT': 'Régularisation'
    }
    method_labels_fr = {
        'CASH': 'Espèces',
        'TRANSFER': 'Virement',
        'CHECK': 'Chèque'
    }
    
    for p in payments_qs:
        total_paid += p.amount
        pay_rows.append([
            p.payment_date.strftime('%d/%m/%Y'),
            type_labels.get(p.payment_type, p.payment_type),
            method_labels_fr.get(p.payment_method, p.payment_method),
            Paragraph(p.notes or "—", body_style),
            f"{p.amount:.2f} DH"
        ])
        
    if not pay_rows:
        pay_rows.append([Paragraph("Aucun paiement enregistré pour cette période.", body_style), "", "", "", "0.00 DH"])
        
    pay_table_data = [pay_header] + pay_rows
    pay_table = Table(pay_table_data, colWidths=[70, 110, 70, 170, 90])
    pay_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#edf2f7')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.black),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (0,0), (2,-1), 'CENTER'),
        ('ALIGN', (4,0), (4,-1), 'RIGHT'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
    ]))
    elements.append(pay_table)
    elements.append(Spacer(1, 15))
    
    # 5. Summary Block (Net, Paid, Balance)
    salary_taught = result.get('salary_taught', Decimal('0.00'))
    balance = salary_taught - total_paid
    
    summary_data = [
        [
            Paragraph("TOTAL DES GAINS CALCULÉS (BRUT/NET) :", bold_body_style),
            Paragraph(f"{salary_taught:.2f} DH", bold_body_style),
        ],
        [
            Paragraph("TOTAL DÉJÀ PAYÉ (AVANCES & RÈGLEMENTS) :", bold_body_style),
            Paragraph(f"{total_paid:.2f} DH", bold_body_style),
        ],
    ]

    if balance >= 0:
        summary_data.append([
            Paragraph("SOLDE DÛ À L'ENSEIGNANT (RESTE À PAYER) :", bold_body_style),
            Paragraph(f"{balance:.2f} DH", bold_body_style),
        ])
    else:
        summary_data.append([
            Paragraph("SOLDE NÉGATIF (TROP-PERÇU / À RETENIR) :", bold_body_style),
            Paragraph(f"{-balance:.2f} DH", bold_body_style),
        ])
    summary_table = Table(summary_data, colWidths=[380, 130])
    summary_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor('#d1fae5') if balance >= 0 else colors.HexColor('#fee2e2')),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 30))
    
    # 6. Signatures
    sig_data = [
        [
            Paragraph("<b>Signature de l'Enseignant</b><br/><br/><br/><br/>_________________________", body_style),
            Paragraph("<b>Signature et Cache du Centre</b><br/><br/><br/><br/>_________________________", body_style)
        ]
    ]
    sig_table = Table(sig_data, colWidths=[250, 260])
    sig_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    elements.append(sig_table)
    
    doc.build(elements)
    buffer.seek(0)
    return buffer


def generate_course_group_pdf(group) -> BytesIO:
    """
    Génère une fiche PDF A4 complète pour un groupe de cours (CourseGroup)
    contenant les informations de l'enseignant, des élèves inscrits, des horaires
    et le jour et la date d'impression.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from xml.sax.saxutils import escape

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36
    )
    styles = getSampleStyleSheet()

    # Color tokens
    PRIMARY = colors.HexColor('#1e3a8a')    # Deep blue
    DARK = colors.HexColor('#0f172a')       # Slate 900
    MUTED = colors.HexColor('#64748b')      # Slate 500
    BG_LIGHT = colors.HexColor('#f8fafc')   # Slate 50
    BORDER = colors.HexColor('#e2e8f0')     # Slate 200

    section_style = ParagraphStyle(
        'GroupSectionHeading',
        parent=styles['Heading2'],
        fontSize=10,
        leading=13,
        textColor=PRIMARY,
        fontName='Helvetica-Bold',
        spaceBefore=8,
        spaceAfter=4,
    )
    body_style = ParagraphStyle(
        'GroupBody',
        parent=styles['Normal'],
        fontSize=8.5,
        leading=11.5,
        textColor=DARK,
        fontName='Helvetica',
    )
    bold_body_style = ParagraphStyle(
        'GroupBoldBody',
        parent=body_style,
        fontName='Helvetica-Bold',
    )
    small_style = ParagraphStyle(
        'GroupSmall',
        parent=styles['Normal'],
        fontSize=7.5,
        leading=10,
        textColor=MUTED,
        fontName='Helvetica',
    )
    header_col_style = ParagraphStyle(
        'GroupTableHead',
        parent=styles['Normal'],
        fontSize=8,
        leading=10,
        textColor=colors.white,
        fontName='Helvetica-Bold',
        alignment=1,  # Center
    )

    elements = []

    # 1. School Information & Document Header
    school_name = get_setting('SCHOOL_NAME', 'Centre')
    school_subtitle = get_setting('SCHOOL_SUBTITLE', 'Soutien Scolaire & Langues')
    school_address = get_setting('SCHOOL_ADDRESS', '')
    school_phone = get_setting('SCHOOL_PHONE', '')
    school_email = get_setting('SCHOOL_EMAIL', '')

    now = timezone.now()
    day_name_fr = FRENCH_DAYS.get(now.strftime('%A'), now.strftime('%A'))
    month_name_fr_val = FRENCH_MONTHS.get(now.month, now.strftime('%B'))
    printed_at_str = f"{day_name_fr} {now.strftime('%d')} {month_name_fr_val} {now.strftime('%Y')} à {now.strftime('%H:%M')}"

    header_left = (
        f"<b>{escape(school_name)}</b><br/>"
        f"<font color='{MUTED.hexval()}'>{escape(school_subtitle)}</font><br/>"
        f"<font size='7.5'>{escape(school_address)}</font><br/>"
        f"<font size='7.5'>Tél: {escape(school_phone)} | Email: {escape(school_email)}</font>"
    )
    header_right = (
        f"<font size='14' color='{PRIMARY.hexval()}'><b>FICHE DU GROUPE</b></font><br/>"
        f"<b>{escape(group.name)}</b><br/>"
        f"<font size='8' color='{MUTED.hexval()}'><b>Imprimé le :</b> {printed_at_str}</font>"
    )

    header_table = Table(
        [[Paragraph(header_left, body_style), Paragraph(header_right, body_style)]],
        colWidths=[270, 250]
    )
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('ALIGN', (1,0), (1,0), 'RIGHT'),
    ]))
    elements.append(header_table)
    elements.append(HRFlowable(width='100%', thickness=1.5, color=PRIMARY, spaceBefore=4, spaceAfter=8))

    # 2. Group & Teacher Information Boxes
    teacher_name = group.teacher.name if group.teacher else 'Non assigné'
    teacher_phone = group.teacher.phone if group.teacher and group.teacher.phone else '—'
    teacher_email = group.teacher.email if group.teacher and group.teacher.email else '—'
    payment_method = group.teacher.get_payment_method_display() if group.teacher else '—'

    levels_display = group.levels_display if hasattr(group, 'levels_display') else (group.level.name if group.level else 'Tous niveaux')
    status_label = "Actif" if group.is_active else "Inactif"

    info_card_left = [
        [Paragraph("<b>INFORMATIONS DU GROUPE</b>", bold_body_style), ""],
        [Paragraph("Matière :", small_style), Paragraph(f"<b>{escape(group.subject)}</b>", body_style)],
        [Paragraph("Niveau(x) :", small_style), Paragraph(f"<b>{escape(levels_display)}</b>", body_style)],
        [Paragraph("Tarif mensuel :", small_style), Paragraph(f"<b>{group.monthly_price} DH</b> / mois", body_style)],
        [Paragraph("Statut :", small_style), Paragraph(f"<b>{status_label}</b>", body_style)],
    ]
    table_group_info = Table(info_card_left, colWidths=[80, 170])
    table_group_info.setStyle(TableStyle([
        ('SPAN', (0,0), (1,0)),
        ('BACKGROUND', (0,0), (1,0), BG_LIGHT),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 2),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
        ('BOX', (0,0), (-1,-1), 0.5, BORDER),
        ('LINEBELOW', (0,0), (1,0), 0.5, BORDER),
    ]))

    info_card_right = [
        [Paragraph("<b>PROFESSEUR / ENSEIGNANT</b>", bold_body_style), ""],
        [Paragraph("Nom :", small_style), Paragraph(f"<b>{escape(teacher_name)}</b>", body_style)],
        [Paragraph("Téléphone :", small_style), Paragraph(escape(teacher_phone), body_style)],
        [Paragraph("Email :", small_style), Paragraph(escape(teacher_email), body_style)],
        [Paragraph("Rémunération :", small_style), Paragraph(escape(payment_method), body_style)],
    ]
    table_teacher_info = Table(info_card_right, colWidths=[85, 165])
    table_teacher_info.setStyle(TableStyle([
        ('SPAN', (0,0), (1,0)),
        ('BACKGROUND', (0,0), (1,0), BG_LIGHT),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 2),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
        ('BOX', (0,0), (-1,-1), 0.5, BORDER),
        ('LINEBELOW', (0,0), (1,0), 0.5, BORDER),
    ]))

    info_row_table = Table([[table_group_info, table_teacher_info]], colWidths=[255, 265])
    info_row_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    elements.append(info_row_table)

    # 3. Weekly Schedules Section
    schedules = list(group.schedules.select_related('room').all())
    elements.append(Paragraph("<b>HORAIRES HEBDOMADAIRES</b>", section_style))
    if schedules:
        sch_header = [
            Paragraph("Jour", header_col_style),
            Paragraph("Heure de début", header_col_style),
            Paragraph("Heure de fin", header_col_style),
            Paragraph("Durée", header_col_style),
            Paragraph("Salle", header_col_style),
        ]
        sch_rows = [sch_header]
        for sch in schedules:
            dur = f"{sch.duration_hours():.1f}h" if hasattr(sch, 'duration_hours') else ""
            room_name = sch.room.name if sch.room else "À définir"
            sch_rows.append([
                Paragraph(f"<b>{escape(sch.get_day_display())}</b>", body_style),
                Paragraph(sch.start_time.strftime('%H:%M'), body_style),
                Paragraph(sch.end_time.strftime('%H:%M'), body_style),
                Paragraph(dur, body_style),
                Paragraph(escape(room_name), body_style),
            ])
        sch_table = Table(sch_rows, colWidths=[110, 100, 100, 80, 130])
        sch_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), PRIMARY),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('GRID', (0,0), (-1,-1), 0.5, BORDER),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, BG_LIGHT]),
            ('TOPPADDING', (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ]))
        elements.append(sch_table)
    else:
        elements.append(Paragraph("<i>Aucun horaire défini pour ce groupe.</i>", body_style))

    elements.append(Spacer(1, 6))

    # 4. Enrolled Students Section
    students = list(group.students.select_related('level').order_by('name'))
    total_students = len(students)
    elements.append(Paragraph(f"<b>LISTE DES ÉLÈVES INSCRITS ({total_students} élève{'s' if total_students > 1 else ''})</b>", section_style))

    if students:
        stud_header = [
            Paragraph("N°", header_col_style),
            Paragraph("Matricule", header_col_style),
            Paragraph("Nom et Prénom", header_col_style),
            Paragraph("Niveau", header_col_style),
            Paragraph("Contact Parent", header_col_style),
            Paragraph("Statut", header_col_style),
            Paragraph("Émargement", header_col_style),
        ]
        stud_rows = [stud_header]
        for idx, student in enumerate(students, start=1):
            matricule = escape(student.matricule) if student.matricule else "—"
            stud_name = f"<b>{escape(student.name)}</b>"
            level_str = escape(student.level.name) if student.level else "—"
            parent_contact = escape(student.parent_contact or student.phone or "—")
            if student.parent_name:
                parent_contact = f"{escape(student.parent_name)}<br/><font size='7' color='{MUTED.hexval()}'>{parent_contact}</font>"
            status_text = "Actif" if student.is_active else "Inactif"

            stud_rows.append([
                Paragraph(str(idx), body_style),
                Paragraph(matricule, body_style),
                Paragraph(stud_name, body_style),
                Paragraph(level_str, body_style),
                Paragraph(parent_contact, body_style),
                Paragraph(status_text, body_style),
                Paragraph("", body_style),  # Empty for teacher attendance/signature
            ])

        # Width sum: 25 + 55 + 155 + 75 + 85 + 55 + 75 = 520pt
        stud_table = Table(stud_rows, colWidths=[25, 55, 155, 75, 85, 55, 75], repeatRows=1)
        stud_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), PRIMARY),
            ('ALIGN', (0,0), (1,-1), 'CENTER'),
            ('ALIGN', (3,0), (3,-1), 'CENTER'),
            ('ALIGN', (5,0), (5,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('GRID', (0,0), (-1,-1), 0.5, BORDER),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, BG_LIGHT]),
            ('TOPPADDING', (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
            ('LEFTPADDING', (0,0), (-1,-1), 4),
            ('RIGHTPADDING', (0,0), (-1,-1), 4),
        ]))
        elements.append(stud_table)
    else:
        elements.append(Paragraph("<i>Aucun élève inscrit dans ce groupe actuellement.</i>", body_style))

    elements.append(Spacer(1, 10))

    # 5. Footer note & signatures
    footer_data = [
        [
            Paragraph(f"<font size='7.5' color='{MUTED.hexval()}'>{escape(school_name)} — Document pédagogique généré le {printed_at_str}</font>", small_style),
            Paragraph("<b>Signature / Visa de l'enseignant :</b><br/><br/><br/>______________________", body_style),
        ]
    ]
    footer_table = Table(footer_data, colWidths=[330, 190])
    footer_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ALIGN', (1,0), (1,0), 'RIGHT'),
    ]))
    elements.append(footer_table)

    doc.build(elements)
    buffer.seek(0)
    return buffer


def generate_thermal_receipt(payment) -> str:
    """
    Génère un reçu format texte pour imprimante thermique (58mm)
    Format simple pour WhatsApp ou impression ticket
    """
    receipt = f"""
{'='*32}
   REÇU DE PAIEMENT
{'='*32}
Reçu N° : {payment.receipt_number}
Date    : {payment.payment_date.strftime('%d/%m/%Y %H:%M')}
{'='*32}

ÉLÈVE : {payment.student.name}
Parent: {payment.student.parent_contact}

{'='*32}
Mois   : {payment.month_covered.strftime('%B %Y')}
Mode   : {payment.get_payment_method_display()}

{'='*32}
MONTANT : {payment.amount} DH
{'='*32}

Groupes inscrits :
"""
    
    enrollments = payment.student.enrollment_set.filter(is_active=True)
    for enrollment in enrollments:
        receipt += f"• {enrollment.course_group.name}\n"
        receipt += f"  {enrollment.course_group.monthly_price} DH/mois\n"
    
    receipt += f"""
{'='*32}
Merci pour votre confiance!
{'='*32}
"""
    
    return receipt


# ==================== NOTIFICATIONS ====================

import os

def load_message_template(filename: str, default_content: str) -> str:
    """
    Loads a message template from the customer messages directory.
    If the directory or file does not exist, it creates them with default_content.
    """
    from core.paths import get_messages_dir
    messages_dir = str(get_messages_dir())
    
    if not os.path.exists(messages_dir):
        try:
            os.makedirs(messages_dir, exist_ok=True)
        except Exception:
            pass
            
    file_path = os.path.join(messages_dir, filename)
    
    if not os.path.exists(file_path):
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(default_content)
        except Exception:
            pass
        return default_content
        
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return default_content


class DynamicTemplateDict(dict):
    def __init__(self, prefix, defaults):
        super().__init__(defaults)
        self.prefix = prefix
        self.defaults = defaults

    def __getitem__(self, key):
        if key in self.defaults:
            filename = f"{self.prefix}_{key}.txt"
            return load_message_template(filename, self.defaults[key])
        return super().__getitem__(key)
    
    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default


DEFAULT_TEMPLATES = {
    'sms_payment_reminder.txt': (
        "Bonjour,\n"
        "Rappel : Un montant de {amount} DH reste à régler pour {student_name}.\n"
        "{school_name}"
    ),
    'whatsapp_customer_service_welcome.txt': (
        "Bonjour {name} 👋\n"
        "Bienvenue chez {business_name} ! Nous sommes ravis de vous accueillir. "
        "Comment pouvons-nous vous aider aujourd'hui ?"
    ),
    'whatsapp_customer_service_order_confirmation.txt': (
        "Bonjour {name},\n"
        "Votre commande n°{order_id} a bien été confirmée ✅.\n"
        "Date de livraison estimée : {delivery_date}.\n"
        "Suivez votre commande ici : {tracking_url}"
    ),
    'whatsapp_customer_service_payment_reminder.txt': (
        "Bonjour {name},\n"
        "Nous vous rappelons qu'un paiement de {amount} concernant la facture n°{invoice_id} est toujours en attente.\n"
        "N'hésitez pas à nous contacter si vous avez besoin d'assistance."
    ),
    'whatsapp_customer_service_appointment_reminder.txt': (
        "Bonjour {name},\n"
        "Nous vous rappelons votre rendez-vous prévu le {date} à {time}.\n"
        "Répondez « CONFIRMER » pour confirmer votre présence ou « REPORTER » pour modifier le rendez-vous."
    ),
    'whatsapp_education_class_reminder.txt': (
        "Bonjour {student_name},\n"
        "Petit rappel : votre cours de {subject} est prévu le {date}."
    ),
    'whatsapp_education_assignment_due.txt': (
        "Bonjour {student_name},\n"
        "Votre devoir « {assignment_name} » doit être remis avant le {due_date}.\n"
        "N'oubliez pas de le soumettre à temps !"
    ),
    'whatsapp_education_grade_notification.txt': (
        "Bonjour {student_name},\n"
        "Votre note pour la matière {subject} a été publiée 📚.\n"
        "Consultez votre espace étudiant pour voir les détails."
    ),
    'whatsapp_absence_notification.txt': (
        "Bonjour {name} 👋,\n\n"
        "📢 Nous vous informons que {student_name} n'a pas assisté au cours de {course_name}{time_info} le 📅 {date}.\n\n"
        "ℹ️ Si cette absence est due à une raison particulière ou si vous souhaitez obtenir "
        "plus d'informations, n'hésitez pas à nous contacter.\n\n"
        "🤝 Merci de votre confiance.\n\n"
        "Cordialement,\n"
        "🎓 L'équipe pédagogique"
    ),
    'whatsapp_payment_confirmation.txt': (
        "Bonjour {name},\n\n"
        "Nous confirmons la réception de votre paiement:\n\n"
        "Montant: {amount} DH\n"
        "Date: {date}\n"
        "Reçu N°: {receipt_number}\n"
        "Pour le mois de: {month}\n\n"
        "Merci pour votre confiance!\n\n"
        "Cordialement,\n"
        "L'équipe administrative"
    ),
    'whatsapp_group_invite.txt': (
        "Bonjour {name} 👋,\n\n"
        "Bienvenue chez {school_name} !\n\n"
        "Voici le(s) lien(s) pour rejoindre le(s) groupe(s) WhatsApp de {student_name} :\n\n"
        "{group_links}\n\n"
        "Merci de rejoindre vos groupes pour recevoir les annonces et le suivi des cours.\n\n"
        "Cordialement,\n"
        "L'équipe administrative"
    ),
    'whatsapp_session_cancellation.txt': (
        "Séance annulée\n\n"
        "Groupe : {group_name}\n"
        "Date : {date}\n"
        "Heure : {start_time} - {end_time}\n\n"
        "La séance du {date} a été annulée. "
        "Nous nous excusons pour la gêne occasionnée."
    ),
    'whatsapp_session_change.txt': (
        "Modification de séance\n\n"
        "Groupe : {group_name}\n"
        "Date : {date}\n"
        "Heure : {start_time} - {end_time}\n"
        "Salle : {room_name}\n\n"
        "Les informations suivantes ont change :\n{change_lines}"
    ),
    'whatsapp_bulk_general.txt': (
        "Bonjour {name}, message général pour tous les parents..."
    ),
    'whatsapp_bulk_event.txt': (
        "Bonjour {name}, nous organisons un événement le [DATE]. Votre enfant {student_name} est invité à participer."
    ),
    'whatsapp_bulk_closure.txt': (
        "Bonjour {name}, l'établissement sera fermé du [DATE] au [DATE]. Les cours reprendront le [DATE]."
    )
}

# Auto-generate templates on import so the messages/ folder is populated immediately
for filename, content in DEFAULT_TEMPLATES.items():
    load_message_template(filename, content)


def send_payment_reminder_sms(student, amount: Decimal) -> bool:
    """
    Envoie un SMS de rappel de paiement (à intégrer avec API SMS)
    """
    school_name = getattr(settings, 'SCHOOL_NAME', 'Afnane center')
    default_template = (
        "Bonjour,\n"
        "Rappel : Un montant de {amount} DH reste à régler pour {student_name}.\n"
        "{school_name}"
    )
    template_str = load_message_template('sms_payment_reminder.txt', default_template)
    message = template_str.format_map(SafeDict({
        'amount': str(amount),
        'student_name': student.name,
        'school_name': school_name,
    })).strip()
    
    # TODO: Intégrer avec une API SMS (Twilio, etc.)
    print(f"SMS envoyé à {student.parent_contact}: {message}")
    
    return True


# generate_whatsapp_link() removed — use WhatsAppUtils.generate_chat_link() instead


# ==================== VALIDATION ====================

def validate_payment_amount(student, amount: Decimal, month_date: date) -> Dict:
    """
    Valide qu'un montant de paiement est cohérent
    
    Returns:
        {'valid': bool, 'message': str, 'suggestion': Decimal}
    """
    required = calculate_student_expected_fees_for_month(
        student,
        month_date
    )
    status = get_student_payment_status(student, month_date)
    
    if amount <= 0:
        return {
            'valid': False,
            'message': "Le montant doit être supérieur à 0",
            'suggestion': required
        }
    
    if amount > (status['remaining'] * Decimal('1.5')):  # 50% de marge
        return {
            'valid': False,
            'message': f"Le montant semble trop élevé. Reste à payer : {status['remaining']} DH",
            'suggestion': status['remaining']
        }
    
    return {
        'valid': True,
        'message': "Montant valide",
        'suggestion': required
    }


# ==================== SESSIONS ====================


def _annotate_conflicts(sessions_qs):
    """
    Evaluates QuerySet and annotates session objects with conflicts & capacity alerts in-memory.
    """
    from .models import Enrollment
    from django.db.models import Count

    sessions_list = list(sessions_qs)

    # Pre-calculate active student counts for each group to avoid N+1 queries
    group_ids = {s.group_id for s in sessions_list}
    enrollment_counts = (
        Enrollment.objects.filter(course_group_id__in=group_ids, is_active=True, student__is_active=True)
        .values('course_group_id')
        .annotate(count=Count('id'))
    )
    counts_map = {item['course_group_id']: item['count'] for item in enrollment_counts}

    for s in sessions_list:
        s.has_conflict = False
        s.conflict_message = ""
        s.has_capacity_alert = False
        s.student_count = counts_map.get(s.group_id, 0)
        s.effective_teacher = getattr(s, 'substitute_teacher', None) or (s.group.teacher if s.group else None)

        if s.student_count > s.room.capacity:
            s.has_capacity_alert = True

    # Check room and teacher overlaps
    for i, s1 in enumerate(sessions_list):
        if s1.status == 'CANCELLED':
            continue
        for s2 in sessions_list[i + 1:]:
            if s2.status == 'CANCELLED':
                continue
            if s1.date == s2.date and s1.id != s2.id:
                if _time_overlaps(s1.start_time, s1.end_time, s2.start_time, s2.end_time):
                    if s1.room_id == s2.room_id:
                        s1.has_conflict = True
                        s2.has_conflict = True
                        s1.conflict_message = f"Conflit de salle avec {s2.group.name}"
                        s2.conflict_message = f"Conflit de salle avec {s1.group.name}"

                    teacher1 = getattr(s1, 'effective_teacher', None)
                    teacher2 = getattr(s2, 'effective_teacher', None)
                    if teacher1 and teacher2 and teacher1.id == teacher2.id:
                        s1.has_conflict = True
                        s2.has_conflict = True
                        s1.conflict_message = f"Conflit de professeur avec {s2.group.name}"
                        s2.conflict_message = f"Conflit de professeur avec {s1.group.name}"

    return sessions_list


def _build_room_schedule(rooms, dates, sessions_list):
    """Build schedule rows organized by room from in-memory list"""
    rows = []
    
    for room in rooms:
        cells = []
        for date in dates:
            # Filter in memory
            day_sessions = [
                s for s in sessions_list 
                if s.room_id == room.id and s.date == date
            ]
            day_sessions.sort(key=lambda x: x.start_time)
            
            cells.append({
                'date': date,
                'sessions': day_sessions,
                'count': len(day_sessions)
            })
        
        if any(cell['count'] > 0 for cell in cells):
            rows.append({
                'entity': room,
                'entity_name': room.name,
                'entity_detail': f"{room.capacity} places",
                'cells': cells,
                'total_sessions': sum(cell['count'] for cell in cells)
            })
    
    return rows


def _build_teacher_schedule(teachers, dates, sessions_list):
    """Build schedule rows organized by teacher from in-memory list.
    Sessions are assigned to the row of the session's effective teacher
    (substitute_teacher if assigned, otherwise group.teacher).
    """
    rows = []

    # Ensure any substitute teacher appearing in sessions_list is included
    known_teacher_ids = {t.id for t in teachers}
    all_teachers = list(teachers)
    for s in sessions_list:
        sub_t = getattr(s, 'substitute_teacher', None)
        if sub_t and sub_t.id not in known_teacher_ids:
            all_teachers.append(sub_t)
            known_teacher_ids.add(sub_t.id)

    for teacher in all_teachers:
        cells = []
        for date in dates:
            # Filter in memory using session's effective teacher
            day_sessions = [
                s for s in sessions_list 
                if (s.substitute_teacher_id or (s.group.teacher_id if s.group else None)) == teacher.id and s.date == date
            ]
            day_sessions.sort(key=lambda x: x.start_time)
            
            cells.append({
                'date': date,
                'sessions': day_sessions,
                'count': len(day_sessions)
            })
        
        if any(cell['count'] > 0 for cell in cells):
            detail_str = ""
            if hasattr(teacher, 'payment_method'):
                detail_str = f"{teacher.payment_percentage}%" if teacher.payment_method == 'PERCENTAGE' else f"{teacher.hourly_rate} DH/h"
            rows.append({
                'entity': teacher,
                'entity_name': teacher.name,
                'entity_detail': detail_str,
                'cells': cells,
                'total_sessions': sum(cell['count'] for cell in cells)
            })
    
    return rows


def _calculate_week_stats(sessions_list, dates):
    """Calculate statistics for the week using in-memory list"""
    total = len(sessions_list)
    planned = sum(1 for s in sessions_list if s.status == 'PLANNED')
    done = sum(1 for s in sessions_list if s.status == 'DONE')
    cancelled = sum(1 for s in sessions_list if s.status == 'CANCELLED')
    
    by_day = []
    for date in dates:
        day_sessions = [s for s in sessions_list if s.date == date]
        by_day.append({
            'date': date,
            'total': len(day_sessions),
            'planned': sum(1 for s in day_sessions if s.status == 'PLANNED'),
            'done': sum(1 for s in day_sessions if s.status == 'DONE'),
            'cancelled': sum(1 for s in day_sessions if s.status == 'CANCELLED'),
        })
    
    return {
        'total': total,
        'planned': planned,
        'done': done,
        'cancelled': cancelled,
        'by_day': by_day
    }



"""
WhatsApp Click-to-Chat Automation Utilities
============================================
Utilities for generating WhatsApp links and automating messaging.
"""

import urllib.parse
from typing import Optional, Dict, List
import re


class WhatsAppUtils:
    """Utility class for WhatsApp Click-to-Chat automation."""
    
    BASE_URL = "https://wa.me/"
    WEB_URL = "https://web.whatsapp.com/send"
    
    @staticmethod
    def clean_phone_number(phone: str) -> str:
        """
        Clean and format phone number for WhatsApp (international format).

        Handles Moroccan local numbers (06x, 07x, 05x) and international
        format (+212 or 00212) transparently.

        Args:
            phone: Phone number in any format

        Returns:
            Phone number as digits-only international string (no leading +)

        Example:
            >>> WhatsAppUtils.clean_phone_number("0612345678")
            '212612345678'
            >>> WhatsAppUtils.clean_phone_number("+212 6 12 34 56 78")
            '212612345678'
        """
        if not phone:
            return ""

        # Handle multiple numbers separated by slash, comma, semicolon, newline, or pipe
        parts = re.split(r'[/,;\n|]', str(phone))
        for part in parts:
            part = part.strip()
            if not part:
                continue

            # Remove all non-digit characters
            cleaned = re.sub(r'\D', '', part)
            if not cleaned:
                continue

            # Morocco: local numbers starting with 06, 07, 05 (10 digits)
            if cleaned.startswith(('06', '07', '05')) and len(cleaned) == 10:
                return '212' + cleaned[1:]  # drop leading 0, prepend 212
            # Morocco: local without leading 0 — 6x, 7x, 5x (9 digits)
            elif cleaned.startswith(('6', '7', '5')) and len(cleaned) == 9:
                return '212' + cleaned
            # Morocco: 00212 prefix — normalise to 212
            elif cleaned.startswith('00212'):
                return cleaned[2:]  # strip leading 00
            # Already international with Morocco prefix (212 followed by 9 digits)
            elif cleaned.startswith('212') and len(cleaned) >= 11:
                return cleaned
            # International numbers (8 to 15 digits)
            elif len(cleaned) >= 8:
                return cleaned.lstrip('0') or cleaned

        return ""
    
    @staticmethod
    def generate_chat_link(
        phone: str,
        message: Optional[str] = None,
        use_web: bool = False
    ) -> str:
        """
        Generate WhatsApp click-to-chat link.
        
        Args:
            phone: Phone number with country code
            message: Pre-filled message (optional)
            use_web: Use WhatsApp Web instead of mobile (default: False)
            
        Returns:
            Complete WhatsApp URL
            
        Example:
            >>> WhatsAppUtils.generate_chat_link(
            ...     "+212612345678",
            ...     "Hello, I'm interested in your services"
            ... )
            'https://wa.me/212612345678?text=Hello%2C%20I%27m%20interested...'
        """
        cleaned_phone = WhatsAppUtils.clean_phone_number(phone)
        
        # Choose base URL
        base_url = WhatsAppUtils.WEB_URL if use_web else WhatsAppUtils.BASE_URL
        
        # Build URL
        if use_web:
            url = f"{base_url}?phone={cleaned_phone}"
        else:
            url = f"{base_url}{cleaned_phone}"
        
        # Add message if provided
        if message:
            separator = "&" if use_web else "?"
            encoded_message = urllib.parse.quote(message)
            url += f"{separator}text={encoded_message}"
        
        return url
    
    @staticmethod
    def generate_group_invite_link(invite_code: str) -> str:
        """
        Generate WhatsApp group invite link.
        
        Args:
            invite_code: Group invite code
            
        Returns:
            Complete group invite URL
            
        Example:
            >>> WhatsAppUtils.generate_group_invite_link("ABC123XYZ")
            'https://chat.whatsapp.com/ABC123XYZ'
        """
        return f"https://chat.whatsapp.com/{invite_code}"
    
    @staticmethod
    def create_template_message(
        template: str,
        variables: Dict[str, str]
    ) -> str:
        """
        Create message from template with variables.
        
        Args:
            template: Message template with {variable} placeholders
            variables: Dictionary of variable values
            
        Returns:
            Formatted message
            
        Example:
            >>> template = "Hello {name}, your order #{order_id} is ready!"
            >>> variables = {"name": "John", "order_id": "12345"}
            >>> WhatsAppUtils.create_template_message(template, variables)
            'Hello John, your order #12345 is ready!'
        """
        return template.format_map(SafeDict(variables))
    
    @staticmethod
    def generate_bulk_links(
        contacts: List[Dict[str, str]],
        message_template: str,
        use_web: bool = False
    ) -> List[Dict[str, str]]:
        """
        Generate multiple WhatsApp links for bulk messaging.
        
        Args:
            contacts: List of contact dicts with 'phone' and other fields
            message_template: Message template with {field} placeholders
            use_web: Use WhatsApp Web links
            
        Returns:
            List of contacts with added 'whatsapp_link' field
            
        Example:
            >>> contacts = [
            ...     {"phone": "+212612345678", "name": "Alice"},
            ...     {"phone": "+212698765432", "name": "Bob"}
            ... ]
            >>> template = "Hi {name}, this is a test message"
            >>> WhatsAppUtils.generate_bulk_links(contacts, template)
            [
                {
                    'phone': '+212612345678',
                    'name': 'Alice',
                    'whatsapp_link': 'https://wa.me/212612345678?text=Hi%20Alice...'
                },
                ...
            ]
        """
        results = []
        
        for contact in contacts:
            # Create personalized message
            message = WhatsAppUtils.create_template_message(
                message_template,
                contact
            )
            
            # Generate link
            link = WhatsAppUtils.generate_chat_link(
                contact['phone'],
                message,
                use_web
            )
            
            # Add link to contact info
            contact_with_link = contact.copy()
            contact_with_link['whatsapp_link'] = link
            contact_with_link['message'] = message
            results.append(contact_with_link)
        
        return results


class WhatsAppMessageTemplates:
    """Pre-built message templates for common use cases."""
    
    _CUSTOMER_SERVICE_DEFAULTS = {
        'welcome':
            "Bonjour {name} 👋\n"
            "Bienvenue chez {business_name} ! Nous sommes ravis de vous accueillir. "
            "Comment pouvons-nous vous aider aujourd'hui ?",

        'order_confirmation':
            "Bonjour {name},\n"
            "Votre commande n°{order_id} a bien été confirmée ✅.\n"
            "Date de livraison estimée : {delivery_date}.\n"
            "Suivez votre commande ici : {tracking_url}",

        'payment_reminder':
            "Bonjour {name},\n"
            "Nous vous rappelons qu'un paiement de {amount} concernant la facture n°{invoice_id} est toujours en attente.\n"
            "N'hésitez pas à nous contacter si vous avez besoin d'assistance.",

        'appointment_reminder':
            "Bonjour {name},\n"
            "Nous vous rappelons votre rendez-vous prévu le {date} à {time}.\n"
            "Répondez « CONFIRMER » pour confirmer votre présence ou « REPORTER » pour modifier le rendez-vous.",
    }

    _EDUCATION_DEFAULTS = {
        'class_reminder':
            "Bonjour {student_name},\n"
            "Petit rappel : votre cours de {subject} est prévu le {date}.",

        'assignment_due':
            "Bonjour {student_name},\n"
            "Votre devoir « {assignment_name} » doit être remis avant le {due_date}.\n"
            "N'oubliez pas de le soumettre à temps !",

        'grade_notification':
            "Bonjour {student_name},\n"
            "Votre note pour la matière {subject} a été publiée 📚.\n"
            "Consultez votre espace étudiant pour voir les détails.",
    }

    CUSTOMER_SERVICE = DynamicTemplateDict('whatsapp_customer_service', _CUSTOMER_SERVICE_DEFAULTS)
    EDUCATION = DynamicTemplateDict('whatsapp_education', _EDUCATION_DEFAULTS)
    
    @classmethod
    def get_template(cls, category: str, template_name: str) -> str:
        """
        Get a specific message template.
        
        Args:
            category: Template category (e.g., 'CUSTOMER_SERVICE')
            template_name: Template name (e.g., 'welcome')
            
        Returns:
            Message template string
        """
        category_templates = getattr(cls, category.upper(), {})
        return category_templates.get(template_name, "")


# DjangoWhatsAppMixin removed — unused dead code
# generate_whatsapp_button_html removed — unused dead code


import urllib.request
import urllib.error
import json

class WhatsAppServiceAPI:
    BASE_URL = f"http://{getattr(settings, 'WHATSAPP_SERVICE_HOST', 'localhost')}:{settings.WHATSAPP_SERVICE_PORT}"

    @classmethod
    def get_status(cls, timeout: float = 0.5):
        """
        Get the current status of the Node.js WhatsApp service.
        Returns:
            dict: { 'offline': False, 'status': 'READY', 'qr': None, 'info': ... }
            or { 'offline': True, 'status': 'OFFLINE' }
        """
        url = f"{cls.BASE_URL}/status"
        try:
            req = urllib.request.Request(url, method='GET')
            with urllib.request.urlopen(req, timeout=timeout) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    data['offline'] = False
                    return data
                else:
                    return {
                        'offline': False,
                        'status': 'ERROR',
                        'error': f"HTTP {response.status}"
                    }
        except Exception as e:
            return {
                'offline': True,
                'status': 'OFFLINE',
                'error': str(e)
            }

    @classmethod
    def send_message(cls, phone: str, message: str = '', attachments: Optional[List[Dict[str, str]]] = None):
        """
        Send a message via the Node.js WhatsApp service.
        Returns:
            dict: { 'success': True, 'messageId': ... }
            or { 'success': False, 'error': ... }
        """
        url = f"{cls.BASE_URL}/send"
        payload_data = {'phone': phone}
        if message:
            payload_data['message'] = message
        if attachments:
            payload_data['attachments'] = attachments
        payload = json.dumps(payload_data).encode('utf-8')
        headers = {'Content-Type': 'application/json'}
        api_key = getattr(settings, 'WHATSAPP_API_KEY', '')
        if api_key:
            headers['X-API-Key'] = api_key
        
        req = urllib.request.Request(
            url, 
            data=payload, 
            headers=headers,
            method='POST'
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                data = json.loads(response.read().decode('utf-8'))
                return data
        except urllib.error.HTTPError as e:
            try:
                # Try to extract the error JSON from response
                data = json.loads(e.read().decode('utf-8'))
                return data
            except Exception:
                return {
                    'success': False,
                    'error': f"HTTP Error {e.code}: {e.reason}"
                }
        except Exception as e:
            return {
                'success': False,
                'error': f"Could not connect to WhatsApp service: {str(e)}"
            }

    @classmethod
    def logout(cls):
        """
        Logs out from the active WhatsApp session.
        """
        url = f"{cls.BASE_URL}/logout"
        headers = {'Content-Type': 'application/json'}
        api_key = getattr(settings, 'WHATSAPP_API_KEY', '')
        if api_key:
            headers['X-API-Key'] = api_key
            
        # Express requires Content-Type for POST body parsing even when body is empty
        req = urllib.request.Request(
            url,
            data=b'{}',
            headers=headers,
            method='POST'
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode('utf-8'))
                return data
        except urllib.error.HTTPError as e:
            try:
                data = json.loads(e.read().decode('utf-8'))
                return data
            except Exception:
                return {'success': False, 'error': f"HTTP Error {e.code}: {e.reason}"}
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    @classmethod
    def restart(cls):
        """
        Restarts the WhatsApp client in the Node.js service.
        """
        url = f"{cls.BASE_URL}/restart"
        headers = {'Content-Type': 'application/json'}
        api_key = getattr(settings, 'WHATSAPP_API_KEY', '')
        if api_key:
            headers['X-API-Key'] = api_key
            
        req = urllib.request.Request(
            url,
            data=b'{}',
            headers=headers,
            method='POST'
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode('utf-8'))
                return data
        except urllib.error.HTTPError as e:
            try:
                data = json.loads(e.read().decode('utf-8'))
                return data
            except Exception:
                return {'success': False, 'error': f"HTTP Error {e.code}: {e.reason}"}
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    @classmethod
    def check_number(cls, phone: str, timeout: float = 5.0) -> dict:
        """
        Verify if a phone number is registered on WhatsApp.
        Returns:
            dict: { 'success': True, 'registered': True/False, 'chatId': ... }
        """
        url = f"{cls.BASE_URL}/check-number"
        payload = json.dumps({'phone': phone}).encode('utf-8')
        headers = {'Content-Type': 'application/json'}
        api_key = getattr(settings, 'WHATSAPP_API_KEY', '')
        if api_key:
            headers['X-API-Key'] = api_key

        req = urllib.request.Request(url, data=payload, headers=headers, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read().decode('utf-8'))
            except Exception:
                return {'success': False, 'error': f"HTTP Error {e.code}: {e.reason}"}
        except Exception as e:
            return {'success': False, 'error': str(e)}


def get_student_pending_group_invites(student, enrollments=None):
    """
    Returns active enrollments for a student that have a whatsapp_group_link
    and where whatsapp_invite_sent is False.
    """
    from .models import Enrollment
    if enrollments is None:
        enrollments = list(
            Enrollment.objects.filter(
                student=student,
                is_active=True,
                whatsapp_invite_sent=False
            ).select_related('course_group')
        )
    else:
        enrollments = [e for e in enrollments if e.is_active and not e.whatsapp_invite_sent]

    return [
        e for e in enrollments
        if e.course_group and e.course_group.whatsapp_group_link and e.course_group.whatsapp_group_link.strip()
    ]


def send_whatsapp_group_invites(student, enrollments=None) -> list:
    """
    Auto-sends WhatsApp group invite links for student's enrolled groups that have
    a whatsapp_group_link set and where whatsapp_invite_sent is False.
    Marks enrollments as whatsapp_invite_sent=True and writes to WhatsAppSendLog.
    Returns list of sent log instances (or empty list if no pending links or disabled).
    """
    from .models import Enrollment, WhatsAppSendLog

    auto_enabled = get_setting('WHATSAPP_AUTO_GROUP_INVITE_ON_FIRST_PAYMENT', 'True')
    if str(auto_enabled).lower() not in ('true', '1', 'yes', 'on'):
        return []

    pending_with_links = get_student_pending_group_invites(student, enrollments=enrollments)
    if not pending_with_links:
        return []

    # Build group link lines
    lines = []
    for e in pending_with_links:
        grp = e.course_group
        subject_info = f" ({grp.subject})" if grp.subject else ""
        lines.append(f"• {grp.name}{subject_info} : {grp.whatsapp_group_link.strip()}")
    group_links_text = "\n".join(lines)

    school_name = get_setting('SCHOOL_NAME', getattr(settings, 'SCHOOL_NAME', 'Centre'))
    parent_name = student.parent_name or "Parent"

    default_template = (
        "Bonjour {name} 👋,\n\n"
        "Bienvenue chez {school_name} !\n\n"
        "Voici le(s) lien(s) pour rejoindre le(s) groupe(s) WhatsApp de {student_name} :\n\n"
        "{group_links}\n\n"
        "Merci de rejoindre vos groupes pour recevoir les annonces et le suivi des cours.\n\n"
        "Cordialement,\n"
        "L'équipe administrative"
    )

    template_str = load_message_template('whatsapp_group_invite.txt', default_template)
    message = template_str.format_map(SafeDict({
        'name': parent_name,
        'student_name': student.name,
        'school_name': school_name,
        'group_links': group_links_text,
    }))

    # Deduplicate recipient phone numbers: parent_contact, parent_contact_2, student.phone
    raw_phones = [student.parent_contact, student.parent_contact_2, student.phone]
    seen_cleaned = set()
    valid_phones = []
    for p in raw_phones:
        if p and p.strip():
            cleaned = WhatsAppUtils.clean_phone_number(p.strip())
            if cleaned and cleaned not in seen_cleaned:
                seen_cleaned.add(cleaned)
                valid_phones.append(p.strip())

    if not valid_phones:
        return []

    logs = []
    for phone in valid_phones:
        res = WhatsAppServiceAPI.send_message(phone, message)
        success = bool(res and res.get('success'))
        error_msg = '' if success else (res.get('error', '') if res else 'No response')

        log = WhatsAppSendLog.objects.create(
            student=student,
            phone=phone,
            message_type='group_invite',
            message_preview=message[:300],
            status='SENT' if success else 'FAILED',
            error_message=error_msg,
        )
        logs.append(log)

    # Mark enrollments as having their invite link sent
    enrollment_ids = [e.id for e in pending_with_links]
    Enrollment.objects.filter(id__in=enrollment_ids).update(whatsapp_invite_sent=True)
    for e in pending_with_links:
        e.whatsapp_invite_sent = True

    return logs


def promote_student_level(student, to_level=None, reason="Progression de niveau", user=None, notes=""):
    """
    Promote student to the next academic level, recording the transition in StudentLevelHistory.
    If to_level is not provided, uses student.level.next_level (or next level by order in category).
    Returns (success: bool, target_level: Level|None, message: str)
    """
    from .models import StudentLevelHistory, Level

    current_level = student.level
    if not to_level:
        if current_level and current_level.next_level:
            to_level = current_level.next_level
        elif current_level:
            next_cand = Level.objects.filter(
                category=current_level.category,
                order__gt=current_level.order
            ).order_by('order').first()
            if next_cand:
                to_level = next_cand

    if not to_level:
        return False, None, "Aucun niveau suivant configuré pour ce niveau."

    if current_level == to_level:
        return False, None, "L'élève est déjà à ce niveau."

    # Record historical transition
    StudentLevelHistory.objects.create(
        student=student,
        from_level=current_level,
        to_level=to_level,
        changed_by=user if user and user.is_authenticated else None,
        reason=reason,
        notes=notes
    )

    student.level = to_level
    student.save(update_fields=['level'])
    return True, to_level, f"Élève promu au niveau « {to_level.name} » avec succès."




