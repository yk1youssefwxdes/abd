"""
analytics.py  –  School Management System · Analytics & Reporting Engine
=========================================================================
Drop-in replacement / extension for the existing utils.py analytics functions.

Sections
--------
1.  RevenueAnalytics       – monthly revenue, forecasts, collection rates
2.  AttendanceAnalytics    – absence trends, at-risk scoring, cohort stats
3.  TeacherAnalytics       – payroll summaries, utilisation, load balancing
4.  RoomAnalytics          – occupancy, peak hours, capacity efficiency
5.  StudentAnalytics       – retention, lifetime value, churn signals
6.  OperationalAnalytics   – session completion, cancellation patterns
7.  DashboardSummary       – single call that powers the director cockpit
8.  ReportExporter         – PDF + CSV export helpers (ReportLab-based)

All functions return plain Python dicts / lists so they are trivially
JSON-serialisable and easy to pass into Django templates.
"""

from __future__ import annotations

import calendar
import csv
import io
import math
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from dateutil.relativedelta import relativedelta
from django.db.models import (
    Avg, Case, Count, DecimalField, ExpressionWrapper, F, FloatField,
    IntegerField, Max, Min, Q, Sum, Value, When,
)
from django.db.models.functions import TruncMonth, TruncWeek
from django.utils import timezone

# ---------------------------------------------------------------------------
# Lazy model imports so this module can be imported without a full Django
# application setup during testing.
# ---------------------------------------------------------------------------

def _models():
    from core.models import (
        Attendance, CourseGroup, CourseGroupSchedule, Enrollment,
        Payment, Room, Session, Student, Teacher,
    )
    return (
        Attendance, CourseGroup, CourseGroupSchedule, Enrollment,
        Payment, Room, Session, Student, Teacher,
    )


# ===========================================================================
# 1. REVENUE ANALYTICS
# ===========================================================================

class RevenueAnalytics:
    """Everything money-related."""

    # ------------------------------------------------------------------ #
    @staticmethod
    def monthly_series(months: int = 12) -> list[dict]:
        """
        Return one dict per month for the last `months` months.

        Keys
        ----
        month_label      French label  e.g. "Juin 2025"
        month_str        ISO prefix    e.g. "2025-06"
        revenue_paid     Decimal – total payments with status PAID
        revenue_expected Decimal – sum of all active enrollments × monthly_price
        collection_rate  float  – revenue_paid / revenue_expected × 100  (%)
        payment_count    int    – number of Payment rows
        unique_payers    int    – distinct students who paid
        """
        from core.utils import month_name_fr
        Attendance, CourseGroup, _, Enrollment, Payment, _, _, Student, _ = _models()

        today = date.today()
        rows = []

        for i in range(months - 1, -1, -1):
            month_start = (today - relativedelta(months=i)).replace(day=1)

            agg = Payment.objects.filter(
                month_covered=month_start, status='PAID'
            ).aggregate(
                revenue_paid=Sum('amount'),
                payment_count=Count('id'),
                unique_payers=Count('student_id', distinct=True),
            )

            revenue_paid = agg['revenue_paid'] or Decimal('0')
            payment_count = agg['payment_count'] or 0
            unique_payers = agg['unique_payers'] or 0

            # Expected = enrolled students × price at that month
            # Approximation: active enrollments as of today (good enough for trend)
            expected = (
                Enrollment.objects.filter(
                    is_active=True,
                    enrolled_date__lte=month_start + relativedelta(months=1) - timedelta(days=1),
                ).aggregate(
                    total=Sum('course_group__monthly_price')
                )['total'] or Decimal('0')
            )

            collection_rate = (
                round(float(revenue_paid / expected) * 100, 1)
                if expected > 0 else 0.0
            )

            rows.append({
                'month_label': f"{month_name_fr(month_start.month)} {month_start.year}",
                'month_str': month_start.strftime('%Y-%m'),
                'month_date': month_start,
                'revenue_paid': revenue_paid,
                'revenue_expected': expected,
                'collection_rate': collection_rate,
                'payment_count': payment_count,
                'unique_payers': unique_payers,
            })

        return rows

    # ------------------------------------------------------------------ #
    @staticmethod
    def current_month_summary() -> dict:
        """
        Snapshot for the current month: collected, outstanding, overdue students.
        """
        Attendance, CourseGroup, _, Enrollment, Payment, _, _, Student, _ = _models()
        from core.utils import calculate_student_monthly_total

        today = date.today()
        month_start = today.replace(day=1)

        collected = Payment.objects.filter(
            month_covered=month_start, status='PAID'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        active_students = Student.objects.filter(is_active=True).prefetch_related(
            'enrollment_set__course_group'
        )

        total_expected = Decimal('0')
        total_outstanding = Decimal('0')
        unpaid_count = 0
        partial_count = 0

        for student in active_students:
            required = calculate_student_monthly_total(student)
            if required == 0:
                continue
            paid = Payment.objects.filter(
                student=student, month_covered=month_start, status='PAID'
            ).aggregate(t=Sum('amount'))['t'] or Decimal('0')
            total_expected += required
            outstanding = max(required - paid, Decimal('0'))
            total_outstanding += outstanding
            if paid == 0:
                unpaid_count += 1
            elif paid < required:
                partial_count += 1

        return {
            'month_start': month_start,
            'collected': collected,
            'expected': total_expected,
            'outstanding': total_outstanding,
            'collection_rate': (
                round(float(collected / total_expected) * 100, 1)
                if total_expected > 0 else 0.0
            ),
            'unpaid_students': unpaid_count,
            'partial_students': partial_count,
        }

    # ------------------------------------------------------------------ #
    @staticmethod
    def revenue_by_course_group(month_start: date | None = None) -> list[dict]:
        """Revenue breakdown per course group for a given month."""
        Attendance, CourseGroup, _, Enrollment, Payment, _, _, Student, _ = _models()

        if month_start is None:
            month_start = date.today().replace(day=1)

        groups = CourseGroup.objects.filter(is_active=True).annotate(
            enrolled_count=Count(
                'enrollment',
                filter=Q(enrollment__is_active=True)
            )
        ).select_related('teacher')

        results = []
        for grp in groups:
            paid = Payment.objects.filter(
                student__enrollment__course_group=grp,
                student__enrollment__is_active=True,
                month_covered=month_start,
                status='PAID',
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

            expected = grp.monthly_price * grp.enrolled_count
            results.append({
                'group_id': grp.id,
                'group_name': grp.name,
                'subject': grp.subject,
                'teacher': grp.teacher.name,
                'enrolled_count': grp.enrolled_count,
                'monthly_price': grp.monthly_price,
                'expected': expected,
                'collected': paid,
                'outstanding': max(expected - paid, Decimal('0')),
                'collection_rate': (
                    round(float(paid / expected) * 100, 1) if expected > 0 else 0.0
                ),
            })

        results.sort(key=lambda r: r['collected'], reverse=True)
        return results

    # ------------------------------------------------------------------ #
    @staticmethod
    def payment_method_breakdown(months: int = 3) -> list[dict]:
        """Cash vs Transfer vs Cheque breakdown for recent months."""
        Attendance, CourseGroup, _, Enrollment, Payment, _, _, Student, _ = _models()

        today = date.today()
        month_start = (today - relativedelta(months=months - 1)).replace(day=1)

        qs = (
            Payment.objects.filter(payment_date__gte=month_start, status='PAID')
            .values('payment_method')
            .annotate(total=Sum('amount'), count=Count('id'))
            .order_by('-total')
        )

        METHOD_LABELS = {'CASH': 'Espèces', 'TRANSFER': 'Virement', 'CHECK': 'Chèque'}
        grand_total = sum(r['total'] for r in qs) or Decimal('1')

        return [
            {
                'method': r['payment_method'],
                'label': METHOD_LABELS.get(r['payment_method'], r['payment_method']),
                'total': r['total'],
                'count': r['count'],
                'pct': round(float(r['total'] / grand_total) * 100, 1),
            }
            for r in qs
        ]

    # ------------------------------------------------------------------ #
    @staticmethod
    def ytd_summary() -> dict:
        """Year-to-date revenue vs same period last year."""
        Attendance, CourseGroup, _, Enrollment, Payment, _, _, Student, _ = _models()

        today = date.today()
        ytd_start = today.replace(month=1, day=1)
        last_year_start = ytd_start.replace(year=ytd_start.year - 1)
        last_year_end = today.replace(year=today.year - 1)

        ytd = Payment.objects.filter(
            payment_date__range=[ytd_start, today], status='PAID'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        ly = Payment.objects.filter(
            payment_date__range=[last_year_start, last_year_end], status='PAID'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        growth = (
            round(float((ytd - ly) / ly) * 100, 1) if ly > 0 else None
        )

        return {
            'ytd': ytd,
            'last_year_same_period': ly,
            'growth_pct': growth,
            'ytd_start': ytd_start,
            'today': today,
        }


# ===========================================================================
# 2. ATTENDANCE ANALYTICS
# ===========================================================================

class AttendanceAnalytics:
    """Absence patterns, at-risk detection, cohort statistics."""

    AT_RISK_THRESHOLD = 20.0   # absence rate % above which a student is "at risk"
    HIGH_RISK_THRESHOLD = 35.0  # critical

    # ------------------------------------------------------------------ #
    @staticmethod
    def student_absence_summary(
        start_date: date,
        end_date: date,
        group_id: int | None = None,
        student_q: str = '',
        min_absences: int = 0,
    ) -> list[dict]:
        """
        Full per-student absence breakdown with risk scoring.

        Each dict includes:
            student_id, student_name, parent_phone, parent_name
            total_sessions, absences, presences
            absence_rate (%), risk_level ('OK' | 'AT_RISK' | 'HIGH_RISK')
            groups  – list of (group_name, absences) tuples
            consecutive_absences  – longest current streak of absences
        """
        Attendance, CourseGroup, _, _, _, _, _, Student, _ = _models()
        from core.utils import WhatsAppUtils

        AT = AttendanceAnalytics.AT_RISK_THRESHOLD
        HT = AttendanceAnalytics.HIGH_RISK_THRESHOLD

        qs = Attendance.objects.filter(date__range=[start_date, end_date])
        if group_id:
            qs = qs.filter(course_group_id=group_id)
        if student_q:
            qs = qs.filter(student__name__icontains=student_q)

        # Aggregate per student
        student_agg = (
            qs.values(
                'student_id',
                'student__name',
                'student__parent_contact',
                'student__parent_contact_2',
                'student__parent_name',
            )
            .annotate(
                total_sessions=Count('id'),
                absences=Count('id', filter=Q(is_present=False)),
            )
            .order_by('-absences')
        )

        # Per-student, per-group breakdown
        group_agg = (
            qs.filter(is_present=False)
            .values('student_id', 'course_group__name')
            .annotate(grp_absences=Count('id'))
        )
        group_map: dict[int, list] = defaultdict(list)
        for row in group_agg:
            group_map[row['student_id']].append(
                (row['course_group__name'], row['grp_absences'])
            )

        # Consecutive absence streaks (per student, across all groups)
        streak_qs = (
            qs.values('student_id', 'date', 'is_present')
            .order_by('student_id', '-date')
        )
        streak_map: dict[int, int] = defaultdict(int)
        current_student = None
        streak = 0
        for row in streak_qs:
            sid = row['student_id']
            if sid != current_student:
                current_student = sid
                streak = 0
            if not row['is_present']:
                streak += 1
                streak_map[sid] = max(streak_map[sid], streak)
            else:
                streak = 0  # Reset on presence

        results = []
        for item in student_agg:
            total = item['total_sessions']
            absences = item['absences']
            if absences < min_absences:
                continue
            absence_rate = round((absences / total * 100) if total > 0 else 0.0, 1)

            if absence_rate >= HT:
                risk_level = 'HIGH_RISK'
            elif absence_rate >= AT:
                risk_level = 'AT_RISK'
            else:
                risk_level = 'OK'

            parent_phone = item['student__parent_contact'] or item['student__parent_contact_2'] or ''
            parent_name = item['student__parent_name'] or 'Parent'
            student_name = item['student__name']

            wa_link = ''
            if parent_phone and risk_level != 'OK':
                msg = (
                    f"Bonjour {parent_name},\n\n"
                    f"Nous vous contactons au sujet de {student_name}.\n"
                    f"Taux d'absence : {absence_rate}% "
                    f"({absences}/{total} séances) du "
                    f"{start_date.strftime('%d/%m/%Y')} au {end_date.strftime('%d/%m/%Y')}.\n\n"
                    f"Merci de nous contacter pour en discuter.\n\n"
                    f"Cordialement,\nL'équipe pédagogique"
                )
                wa_link = WhatsAppUtils.generate_chat_link(parent_phone, msg)

            results.append({
                'student_id': item['student_id'],
                'student_name': student_name,
                'parent_phone': parent_phone,
                'parent_name': parent_name,
                'total_sessions': total,
                'absences': absences,
                'presences': total - absences,
                'absence_rate': absence_rate,
                'risk_level': risk_level,
                'is_at_risk': risk_level in ('AT_RISK', 'HIGH_RISK'),
                'consecutive_absences': streak_map.get(item['student_id'], 0),
                'groups': sorted(
                    group_map.get(item['student_id'], []),
                    key=lambda x: x[1], reverse=True
                ),
                'wa_link': wa_link,
            })

        results.sort(key=lambda r: (r['risk_level'] == 'OK', -r['absence_rate']))
        return results

    # ------------------------------------------------------------------ #
    @staticmethod
    def weekly_trend(weeks: int = 8) -> list[dict]:
        """
        Absence rate per week for the last `weeks` weeks.
        Good for spotting seasonal dips (exam periods, holidays, etc.)
        """
        Attendance, _, _, _, _, _, _, _, _ = _models()

        today = date.today()
        rows = []

        for i in range(weeks - 1, -1, -1):
            week_end = today - timedelta(days=today.weekday()) - timedelta(weeks=i - 1) - timedelta(days=1)
            week_start = week_end - timedelta(days=6)

            agg = Attendance.objects.filter(
                date__range=[week_start, week_end]
            ).aggregate(
                total=Count('id'),
                absences=Count('id', filter=Q(is_present=False)),
            )
            total = agg['total'] or 0
            absences = agg['absences'] or 0
            rows.append({
                'week_label': f"{week_start.strftime('%d/%m')} – {week_end.strftime('%d/%m')}",
                'week_start': week_start,
                'week_end': week_end,
                'total': total,
                'absences': absences,
                'presences': total - absences,
                'absence_rate': round(absences / total * 100, 1) if total > 0 else 0.0,
            })

        return rows

    # ------------------------------------------------------------------ #
    @staticmethod
    def group_attendance_matrix(month_start: date | None = None) -> list[dict]:
        """
        Per course-group attendance summary for a month.
        Returns list sorted by absence_rate desc.
        """
        Attendance, CourseGroup, _, _, _, _, _, _, _ = _models()

        if month_start is None:
            month_start = date.today().replace(day=1)
        _, last_day = calendar.monthrange(month_start.year, month_start.month)
        month_end = month_start.replace(day=last_day)

        groups = CourseGroup.objects.filter(is_active=True).annotate(
            enrolled=Count('enrollment', filter=Q(enrollment__is_active=True))
        )

        results = []
        for grp in groups:
            agg = Attendance.objects.filter(
                course_group=grp,
                date__range=[month_start, month_end],
            ).aggregate(
                total=Count('id'),
                absences=Count('id', filter=Q(is_present=False)),
            )
            total = agg['total'] or 0
            absences = agg['absences'] or 0
            results.append({
                'group_id': grp.id,
                'group_name': grp.name,
                'subject': grp.subject,
                'enrolled': grp.enrolled,
                'total_records': total,
                'absences': absences,
                'presences': total - absences,
                'absence_rate': round(absences / total * 100, 1) if total > 0 else 0.0,
            })

        results.sort(key=lambda r: r['absence_rate'], reverse=True)
        return results

    # ------------------------------------------------------------------ #
    @staticmethod
    def daily_absence_heatmap(month_start: date | None = None) -> dict:
        """
        Returns a dict keyed by ISO date string with absence counts.
        Frontend can render this as a calendar heatmap.
        """
        Attendance, _, _, _, _, _, _, _, _ = _models()

        if month_start is None:
            month_start = date.today().replace(day=1)
        _, last_day = calendar.monthrange(month_start.year, month_start.month)
        month_end = month_start.replace(day=last_day)

        qs = (
            Attendance.objects.filter(
                date__range=[month_start, month_end],
                is_present=False,
            )
            .values('date')
            .annotate(count=Count('id'))
        )

        return {row['date'].isoformat(): row['count'] for row in qs}


# ===========================================================================
# 3. TEACHER ANALYTICS
# ===========================================================================

class TeacherAnalytics:
    """Payroll, session loads, substitution patterns."""

    # ------------------------------------------------------------------ #
    @staticmethod
    def payroll_summary(start_date: date, end_date: date) -> list[dict]:
        """
        Full payroll for every active teacher over a date range.
        Uses the existing calculate_teacher_hours util internally.
        """
        from core.utils import calculate_teacher_hours, get_months_in_range
        from django.db.models import Q, Sum
        _, _, _, _, _, _, Session, _, Teacher = _models()

        # Import TeacherPayment lazily
        from core.models import TeacherPayment

        teachers = Teacher.objects.filter(is_active=True)
        results = []

        # Pre-build list of target period months for payment lookups
        target_months = get_months_in_range(start_date, end_date)

        for teacher in teachers:
            data = calculate_teacher_hours(teacher, start_date, end_date)
            session_count = Session.objects.filter(
                group__teacher=teacher,
                status='DONE',
                date__range=[start_date, end_date],
            ).count()
            substitute_count = Session.objects.filter(
                substitute_teacher=teacher,
                status='DONE',
                date__range=[start_date, end_date],
            ).count()

            # Calculate amount already paid in the matching period months
            total_paid = Decimal('0.00')
            if target_months:
                q_filter = Q()
                for m in target_months:
                    q_filter |= Q(period_month=m.month, period_year=m.year)
                paid_agg = TeacherPayment.objects.filter(
                    Q(teacher=teacher) & q_filter
                ).aggregate(s=Sum('amount'))['s']
                total_paid = paid_agg or Decimal('0.00')

            salary_taught = data.get('salary_taught', Decimal('0.00')) or Decimal('0.00')
            balance = salary_taught - total_paid

            results.append({
                'teacher_id': teacher.id,
                'teacher_name': teacher.name,
                'payment_method': teacher.payment_method,
                'session_count': session_count,
                'substitute_count': substitute_count,
                'total_sessions': session_count + substitute_count,
                'total_paid': total_paid,
                'balance': balance,
                **data,  # total_hours, earnings, salary_taught, etc. from existing util
            })

        results.sort(key=lambda r: r.get('earnings', 0) or 0, reverse=True)
        return results

    # ------------------------------------------------------------------ #
    @staticmethod
    def weekly_load() -> list[dict]:
        """
        Scheduled weekly hours per teacher (from CourseGroupSchedule).
        Flags teachers above 30h/week or below 10h/week.
        """
        _, _, CourseGroupSchedule, _, _, _, _, _, Teacher = _models()

        teachers = Teacher.objects.filter(is_active=True)
        results = []

        for teacher in teachers:
            schedules = CourseGroupSchedule.objects.filter(
                course_group__teacher=teacher,
                course_group__is_active=True,
            )
            weekly_hours = sum(sch.duration_hours() for sch in schedules)
            session_count = schedules.count()

            results.append({
                'teacher_id': teacher.id,
                'teacher_name': teacher.name,
                'weekly_hours': round(weekly_hours, 2),
                'session_count': session_count,
                'load_flag': (
                    'OVERLOADED' if weekly_hours > 30
                    else 'UNDERUTILISED' if weekly_hours < 10
                    else 'NORMAL'
                ),
            })

        results.sort(key=lambda r: r['weekly_hours'], reverse=True)
        return results

    # ------------------------------------------------------------------ #
    @staticmethod
    def substitution_rate(months: int = 3) -> list[dict]:
        """
        How often each teacher needed a substitute.
        High rate may indicate availability or commitment issues.
        """
        _, _, _, _, _, _, Session, _, Teacher = _models()

        today = date.today()
        since = (today - relativedelta(months=months)).replace(day=1)

        teachers = Teacher.objects.filter(is_active=True)
        results = []

        for teacher in teachers:
            total = Session.objects.filter(
                group__teacher=teacher,
                date__gte=since,
            ).exclude(status='CANCELLED').count()

            substituted = Session.objects.filter(
                group__teacher=teacher,
                substitute_teacher__isnull=False,
                date__gte=since,
            ).exclude(status='CANCELLED').count()

            results.append({
                'teacher_id': teacher.id,
                'teacher_name': teacher.name,
                'total_sessions': total,
                'substituted_sessions': substituted,
                'substitution_rate': (
                    round(substituted / total * 100, 1) if total > 0 else 0.0
                ),
            })

        results.sort(key=lambda r: r['substitution_rate'], reverse=True)
        return results

    @staticmethod
    def workload_dashboard_stats(teacher, start_date: date, end_date: date) -> dict:
        """
        Detailed workload stats for a single teacher over a date range.
        """
        from core.models import CourseGroupSchedule, Session, TeacherAvailability, CourseGroup
        from datetime import datetime, timedelta
        from django.db.models import Q
        from collections import defaultdict
        
        # 1. Weekly schedules hours & groups
        schedules = CourseGroupSchedule.objects.filter(
            course_group__teacher=teacher,
            course_group__is_active=True
        ).select_related('course_group', 'room')
        
        weekly_hours = sum((datetime.combine(date.today(), sch.end_time) - datetime.combine(date.today(), sch.start_time)).total_seconds() / 3600.0 for sch in schedules)
        session_count = schedules.count()
        group_count = CourseGroup.objects.filter(teacher=teacher, is_active=True).distinct().count()

        # 2. Availability hours
        availabilities = TeacherAvailability.objects.filter(teacher=teacher, is_available=True)
        avail_hours = sum((datetime.combine(date.today(), av.end_time) - datetime.combine(date.today(), av.start_time)).total_seconds() / 3600.0 for av in availabilities)
        
        utilization_pct = (weekly_hours / avail_hours * 100) if avail_hours > 0 else 0.0
        free_hours = max(0.0, float(avail_hours) - float(weekly_hours))

        # 3. Date range sessions & actual teaching hours
        sessions = Session.objects.filter(
            Q(group__teacher=teacher) | Q(substitute_teacher=teacher),
            date__range=[start_date, end_date]
        ).exclude(status='CANCELLED').select_related('group', 'room')
        
        total_sessions = sessions.count()
        total_hours = sum((datetime.combine(date.today(), s.end_time) - datetime.combine(date.today(), s.start_time)).total_seconds() / 3600.0 for s in sessions)

        # 4. Peak working day
        day_map_fr = {
            'MON': 'Lundi', 'TUE': 'Mardi', 'WED': 'Mercredi', 'THU': 'Jeudi',
            'FRI': 'Vendredi', 'SAT': 'Samedi', 'SUN': 'Dimanche'
        }
        day_hours = defaultdict(float)
        for sch in schedules:
            hours = (datetime.combine(date.today(), sch.end_time) - datetime.combine(date.today(), sch.start_time)).total_seconds() / 3600.0
            day_hours[sch.day] += hours
        
        peak_day_code = max(day_hours, key=day_hours.get) if day_hours else None
        peak_working_day = day_map_fr.get(peak_day_code, "Aucun")

        # 5. Average sessions per day
        unique_dates_count = len(set(s.date for s in sessions))
        avg_sessions_per_day = round(total_sessions / unique_dates_count, 1) if unique_dates_count > 0 else 0.0

        # 6. Weekly calendar heatmap (MON-SUN, 08:00 to 21:00 hourly)
        heatmap = {day: [0]*14 for day in ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN']}
        for sch in schedules:
            start_h = sch.start_time.hour
            end_h = sch.end_time.hour
            for h in range(start_h, end_h):
                if 8 <= h <= 21:
                    heatmap[sch.day][h - 8] = 1

        return {
            'weekly_hours': round(weekly_hours, 1),
            'monthly_hours': round(total_hours, 1),
            'total_sessions': total_sessions,
            'group_count': group_count,
            'utilization_pct': round(utilization_pct, 1),
            'free_hours': round(free_hours, 1),
            'peak_working_day': peak_working_day,
            'avg_sessions_per_day': avg_sessions_per_day,
            'heatmap': heatmap,
        }


# ===========================================================================
# 4. ROOM ANALYTICS
# ===========================================================================

class RoomAnalytics:
    """Occupancy, capacity efficiency, peak hour analysis."""

    WEEK_AVAILABLE_HOURS = Decimal('84')  # Mon–Sat 08:00–22:00 = 14h × 6

    # ------------------------------------------------------------------ #
    @staticmethod
    def occupancy_summary() -> list[dict]:
        """
        Per-room weekly scheduled hours + occupancy %.
        Also flags rooms over-capacity.
        """
        _, CourseGroup, CourseGroupSchedule, _, _, Room, _, _, _ = _models()

        rooms = Room.objects.filter(is_active=True)
        results = []

        for room in rooms:
            schedules = CourseGroupSchedule.objects.filter(
                room=room,
                course_group__is_active=True,
            ).select_related('course_group')

            weekly_hours = sum(sch.duration_hours() for sch in schedules)
            group_count = (
                CourseGroup.objects.filter(
                    schedules__room=room, is_active=True
                ).distinct().count()
            )

            # Capacity violations: groups whose enrolled count > room.capacity
            violations = []
            for sch in schedules:
                enrolled = sch.course_group.enrollment_set.filter(is_active=True).count()
                if enrolled > room.capacity:
                    violations.append({
                        'group_name': sch.course_group.name,
                        'enrolled': enrolled,
                        'capacity': room.capacity,
                        'overflow': enrolled - room.capacity,
                    })

            occupancy_pct = min(
                round(weekly_hours / float(RoomAnalytics.WEEK_AVAILABLE_HOURS) * 100, 1),
                100.0
            )

            results.append({
                'room_id': room.id,
                'room_name': room.name,
                'capacity': room.capacity,
                'weekly_hours': round(weekly_hours, 1),
                'group_count': group_count,
                'occupancy_pct': occupancy_pct,
                'occupancy_flag': (
                    'HIGH' if occupancy_pct >= 80
                    else 'MEDIUM' if occupancy_pct >= 50
                    else 'LOW'
                ),
                'capacity_violations': violations,
                'has_violations': bool(violations),
            })

        results.sort(key=lambda r: r['occupancy_pct'], reverse=True)
        return results

    # ------------------------------------------------------------------ #
    @staticmethod
    def class_size_distribution() -> dict:
        """Group active course groups by size brackets."""
        from core.models import CourseGroup
        from django.db.models import Count, Q
        groups = CourseGroup.objects.filter(is_active=True).annotate(
            enrolled=Count('enrollment', filter=Q(enrollment__is_active=True))
        )
        dist = {'from_1_to_5': 0, 'from_6_to_10': 0, 'from_11_to_15': 0, 'from_16_to_20': 0, 'more_than_20': 0}
        for g in groups:
            c = g.enrolled
            if c <= 5:
                dist['from_1_to_5'] += 1
            elif c <= 10:
                dist['from_6_to_10'] += 1
            elif c <= 15:
                dist['from_11_to_15'] += 1
            elif c <= 20:
                dist['from_16_to_20'] += 1
            else:
                dist['more_than_20'] += 1
        return dist

    # ------------------------------------------------------------------ #
    @staticmethod
    def class_usage_list() -> list[dict]:
        """List active course groups with their filling rate details."""
        from core.models import CourseGroup
        from django.db.models import Count, Q
        groups = CourseGroup.objects.filter(is_active=True).annotate(
            enrolled=Count('enrollment', filter=Q(enrollment__is_active=True))
        ).select_related('teacher')
        
        results = []
        for g in groups:
            schedules = g.schedules.all().select_related('room')
            room_name = schedules[0].room.name if schedules.exists() else "Non assignée"
            room_cap = schedules[0].room.capacity if schedules.exists() else 1
            efficiency = round((g.enrolled / room_cap * 100), 1) if room_cap > 0 else 0
            
            slots = []
            for s in schedules:
                slots.append(f"{s.get_day_display()} {s.start_time.strftime('%H:%M')}-{s.end_time.strftime('%H:%M')}")
            
            results.append({
                'group_id': g.id,
                'group_name': g.name,
                'subject': g.subject,
                'teacher': g.teacher.name,
                'enrolled_count': g.enrolled,
                'room_name': room_name,
                'room_capacity': room_cap,
                'capacity_efficiency': efficiency,
                'slots': slots,
            })
            
        results.sort(key=lambda x: x['capacity_efficiency'], reverse=True)
        return results

    # ------------------------------------------------------------------ #
    @staticmethod
    def peak_hour_matrix() -> dict:
        """
        Returns a dict: {day_code: {hour: session_count}} for the schedule.
        Useful for rendering a heatmap grid of when rooms are busiest.
        """
        _, _, CourseGroupSchedule, _, _, _, _, _, _ = _models()

        DAY_ORDER = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN']
        matrix: dict[str, dict[int, int]] = {d: defaultdict(int) for d in DAY_ORDER}

        for sch in CourseGroupSchedule.objects.filter(course_group__is_active=True):
            start_h = sch.start_time.hour
            end_h = sch.end_time.hour + (1 if sch.end_time.minute > 0 else 0)
            for h in range(start_h, end_h):
                matrix[sch.day][h] += 1

        return {day: dict(hours) for day, hours in matrix.items()}

    @staticmethod
    def utilization_dashboard_stats(room, start_date: date, end_date: date) -> dict:
        """
        Detailed occupancy stats for a single room over a date range.
        """
        from core.models import CourseGroupSchedule, Session
        from datetime import datetime, time
        from collections import defaultdict
        
        # 1. Weekly schedule load
        schedules = CourseGroupSchedule.objects.filter(
            room=room,
            course_group__is_active=True
        ).select_related('course_group')
        
        weekly_hours = sum((datetime.combine(date.today(), sch.end_time) - datetime.combine(date.today(), sch.start_time)).total_seconds() / 3600.0 for sch in schedules)
        
        # Room total weekly available hours = 84 (Mon-Sat 08:00-22:00 = 14h x 6 days)
        total_avail_weekly = 84.0
        occupancy_pct = (weekly_hours / total_avail_weekly * 100) if total_avail_weekly > 0 else 0.0
        free_hours = max(0.0, total_avail_weekly - float(weekly_hours))

        # 2. Date range sessions
        sessions = Session.objects.filter(
            room=room,
            date__range=[start_date, end_date]
        ).exclude(status='CANCELLED')
        
        total_sessions = sessions.count()
        total_hours = sum((datetime.combine(date.today(), s.end_time) - datetime.combine(date.today(), s.start_time)).total_seconds() / 3600.0 for s in sessions)

        # 3. Peak usage hour/day
        day_map_fr = {
            'MON': 'Lundi', 'TUE': 'Mardi', 'WED': 'Mercredi', 'THU': 'Jeudi',
            'FRI': 'Vendredi', 'SAT': 'Samedi', 'SUN': 'Dimanche'
        }
        day_hours = defaultdict(float)
        for sch in schedules:
            hours = (datetime.combine(date.today(), sch.end_time) - datetime.combine(date.today(), sch.start_time)).total_seconds() / 3600.0
            day_hours[sch.day] += hours
        
        peak_day_code = max(day_hours, key=day_hours.get) if day_hours else None
        peak_usage_day = day_map_fr.get(peak_day_code, "Aucun")

        # 4. Average daily utilization
        unique_dates_count = len(set(s.date for s in sessions))
        avg_daily_utilization = round(total_hours / unique_dates_count, 1) if unique_dates_count > 0 else 0.0

        # 5. Idle periods calculation (gaps)
        idle_hours = 0.0
        for day in ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN']:
            day_schedules = sorted(
                [sch for sch in schedules if sch.day == day],
                key=lambda s: s.start_time
            )
            if not day_schedules:
                idle_hours += 14.0
                continue
            
            first_start = datetime.combine(date.today(), day_schedules[0].start_time)
            day_start = datetime.combine(date.today(), time(8, 0))
            if first_start > day_start:
                idle_hours += (first_start - day_start).total_seconds() / 3600.0
            
            for idx in range(len(day_schedules) - 1):
                curr_end = datetime.combine(date.today(), day_schedules[idx].end_time)
                next_start = datetime.combine(date.today(), day_schedules[idx+1].start_time)
                if next_start > curr_end:
                    idle_hours += (next_start - curr_end).total_seconds() / 3600.0
            
            last_end = datetime.combine(date.today(), day_schedules[-1].end_time)
            day_end = datetime.combine(date.today(), time(22, 0))
            if day_end > last_end:
                idle_hours += (day_end - last_end).total_seconds() / 3600.0

        # 6. Heatmap grid (MON-SUN, 08:00 to 21:00 hourly)
        heatmap = {day: [0]*14 for day in ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN']}
        for sch in schedules:
            start_h = sch.start_time.hour
            end_h = sch.end_time.hour
            for h in range(start_h, end_h):
                if 8 <= h <= 21:
                    heatmap[sch.day][h - 8] = 1

        # Classify loading status
        if occupancy_pct > 75.0:
            status = 'OVERLOADED'
        elif occupancy_pct < 25.0:
            status = 'UNDERUTILIZED'
        else:
            status = 'NORMAL'

        return {
            'occupancy_pct': round(occupancy_pct, 1),
            'weekly_hours': round(weekly_hours, 1),
            'monthly_hours': round(total_hours, 1),
            'free_hours': round(free_hours, 1),
            'peak_usage_day': peak_usage_day,
            'idle_hours_weekly': round(idle_hours, 1),
            'total_sessions': total_sessions,
            'avg_daily_utilization': avg_daily_utilization,
            'status': status,
            'heatmap': heatmap,
        }


# ===========================================================================
# 5. STUDENT ANALYTICS
# ===========================================================================

class StudentAnalytics:
    """Retention, churn signals, lifetime value, enrolment trends."""

    # ------------------------------------------------------------------ #
    @staticmethod
    def enrollment_trend(months: int = 12) -> list[dict]:
        """New enrolments per month."""
        _, _, _, Enrollment, _, _, _, _, _ = _models()
        from core.utils import month_name_fr

        today = date.today()
        rows = []

        for i in range(months - 1, -1, -1):
            month_start = (today - relativedelta(months=i)).replace(day=1)
            month_end = month_start + relativedelta(months=1) - timedelta(days=1)

            count = Enrollment.objects.filter(
                enrolled_date__range=[month_start, month_end]
            ).count()

            rows.append({
                'month_label': f"{month_name_fr(month_start.month)} {month_start.year}",
                'month_str': month_start.strftime('%Y-%m'),
                'new_enrollments': count,
            })

        return rows

    # ------------------------------------------------------------------ #
    @staticmethod
    def churn_signals() -> list[dict]:
        """
        Students flagged as churn risks:
        - Unpaid for 2+ consecutive months
        - Absence rate > 30% in the last 30 days
        - No attendance record in the last 14 days (may have quietly left)
        """
        _, _, _, Enrollment, Payment, _, _, Student, _ = _models()
        from core.utils import calculate_student_monthly_total

        today = date.today()
        current_month = today.replace(day=1)
        prev_month = (current_month - timedelta(days=1)).replace(day=1)
        cutoff_14d = today - timedelta(days=14)
        cutoff_30d = today - timedelta(days=30)

        active_students = Student.objects.filter(is_active=True).prefetch_related(
            'enrollment_set__course_group',
            'payments',
        )

        results = []
        for student in active_students:
            signals = []

            # Signal 1: consecutive unpaid months
            unpaid_months = 0
            for m in [current_month, prev_month]:
                required = calculate_student_monthly_total(student)
                if required == 0:
                    continue
                paid = student.payments.filter(
                    month_covered=m, status='PAID'
                ).aggregate(t=Sum('amount'))['t'] or Decimal('0')
                if paid < required:
                    unpaid_months += 1

            if unpaid_months >= 2:
                signals.append(f"Impayé {unpaid_months} mois consécutifs")

            # Signal 2: high absence rate (last 30 days)
            from core.models import Attendance
            att_qs = Attendance.objects.filter(
                student=student, date__gte=cutoff_30d
            )
            total_att = att_qs.count()
            absent_att = att_qs.filter(is_present=False).count()
            if total_att > 0:
                absence_rate = round(absent_att / total_att * 100, 1)
                if absence_rate > 30:
                    signals.append(f"Absence {absence_rate}% (30 derniers jours)")

            # Signal 3: no attendance in 14 days
            last_att = att_qs.filter(
                date__gte=cutoff_14d
            ).count()
            enrolled = student.enrollment_set.filter(is_active=True).count()
            if enrolled > 0 and last_att == 0:
                signals.append("Aucune présence enregistrée depuis 14 jours")

            if signals:
                results.append({
                    'student_id': student.id,
                    'student_name': student.name,
                    'parent_contact': student.parent_contact,
                    'parent_contact_2': student.parent_contact_2,
                    'signals': signals,
                    'signal_count': len(signals),
                    'groups': [e.course_group.name for e in student.enrollment_set.filter(is_active=True)],
                })

        results.sort(key=lambda r: r['signal_count'], reverse=True)
        return results

    # ------------------------------------------------------------------ #
    @staticmethod
    def lifetime_value() -> list[dict]:
        """
        Total payments per student since inception.
        Top 20 returned for 'best customers' display.
        """
        _, _, _, _, Payment, _, _, Student, _ = _models()

        qs = (
            Payment.objects.filter(status='PAID')
            .values('student_id', 'student__name')
            .annotate(
                total_paid=Sum('amount'),
                payment_count=Count('id'),
                first_payment=Min('payment_date'),
                last_payment=Max('payment_date'),
            )
            .order_by('-total_paid')[:20]
        )

        results = []
        for row in qs:
            months_active = (
                (row['last_payment'] - row['first_payment']).days // 30 + 1
                if row['first_payment'] and row['last_payment'] else 1
            )
            results.append({
                'student_id': row['student_id'],
                'student_name': row['student__name'],
                'total_paid': row['total_paid'],
                'payment_count': row['payment_count'],
                'months_active': months_active,
                'avg_per_month': (
                    row['total_paid'] / months_active
                ).quantize(Decimal('0.01')),
                'first_payment': row['first_payment'],
                'last_payment': row['last_payment'],
            })

        return results

    # ------------------------------------------------------------------ #
    @staticmethod
    def multi_group_students() -> list[dict]:
        """Students enrolled in 2+ groups — highest-value customers."""
        _, _, _, Enrollment, _, _, _, Student, _ = _models()

        qs = (
            Enrollment.objects.filter(is_active=True)
            .values('student_id', 'student__name')
            .annotate(group_count=Count('id'))
            .filter(group_count__gte=2)
            .order_by('-group_count')
        )

        return [
            {
                'student_id': r['student_id'],
                'student_name': r['student__name'],
                'group_count': r['group_count'],
            }
            for r in qs
        ]

    # ------------------------------------------------------------------ #
    @staticmethod
    def level_distribution() -> list[dict]:
        """Academic category and level student distribution."""
        from core.models import Level, Student
        from django.db.models import Count, Q
        levels = Level.objects.select_related('category').annotate(
            student_count=Count('students', filter=Q(students__is_active=True))
        ).order_by('category__name', 'name')
        
        total_students = sum(l.student_count for l in levels)
        results = []
        for l in levels:
            pct = round((l.student_count / total_students * 100), 1) if total_students > 0 else 0.0
            results.append({
                'level_name': l.name,
                'category': l.get_category_display(),
                'count': l.student_count,
                'pct': pct,
            })
        return results

    # ------------------------------------------------------------------ #
    @staticmethod
    def enrollment_stats() -> dict:
        """Compute average enrollments and class density stats."""
        from core.models import Enrollment, Student
        active_enrollments = Enrollment.objects.filter(is_active=True).count()
        active_students = Student.objects.filter(is_active=True).count()
        avg_classes = round(active_enrollments / active_students, 2) if active_students > 0 else 0.0
        
        return {
            'avg_classes_per_student': avg_classes,
            'total_active_students': active_students,
            'total_active_enrollments': active_enrollments,
        }


# ===========================================================================
# 6. OPERATIONAL ANALYTICS
# ===========================================================================

class OperationalAnalytics:
    """Session completion rates, cancellation patterns, scheduling health."""

    # ------------------------------------------------------------------ #
    @staticmethod
    def session_completion_rate(months: int = 3) -> list[dict]:
        """
        Per-month: planned vs done vs cancelled.
        Returns a list suitable for a stacked bar chart.
        """
        _, _, _, _, _, _, Session, _, _ = _models()
        from core.utils import month_name_fr

        today = date.today()
        rows = []

        for i in range(months - 1, -1, -1):
            month_start = (today - relativedelta(months=i)).replace(day=1)
            _, last_day = calendar.monthrange(month_start.year, month_start.month)
            month_end = month_start.replace(day=last_day)

            agg = Session.objects.filter(
                date__range=[month_start, month_end]
            ).aggregate(
                total=Count('id'),
                done=Count('id', filter=Q(status='DONE')),
                cancelled=Count('id', filter=Q(status='CANCELLED')),
                planned=Count('id', filter=Q(status='PLANNED')),
            )

            total = agg['total'] or 1
            rows.append({
                'month_label': f"{month_name_fr(month_start.month)} {month_start.year}",
                'month_str': month_start.strftime('%Y-%m'),
                'total': agg['total'] or 0,
                'done': agg['done'] or 0,
                'cancelled': agg['cancelled'] or 0,
                'planned': agg['planned'] or 0,
                'completion_rate': round((agg['done'] or 0) / total * 100, 1),
                'cancellation_rate': round((agg['cancelled'] or 0) / total * 100, 1),
            })

        return rows

    # ------------------------------------------------------------------ #
    @staticmethod
    def cancellation_reasons_by_group() -> list[dict]:
        """
        Which groups cancel the most? Useful for scheduling reviews.
        Last 90 days.
        """
        _, _, _, _, _, _, Session, _, _ = _models()

        since = date.today() - timedelta(days=90)
        qs = (
            Session.objects.filter(status='CANCELLED', date__gte=since)
            .values('group__id', 'group__name', 'group__teacher__name')
            .annotate(cancelled=Count('id'))
            .order_by('-cancelled')[:15]
        )

        return [
            {
                'group_id': r['group__id'],
                'group_name': r['group__name'],
                'teacher_name': r['group__teacher__name'],
                'cancelled_sessions': r['cancelled'],
            }
            for r in qs
        ]

    # ------------------------------------------------------------------ #
    @staticmethod
    def uncompleted_sessions() -> dict:
        """
        Past sessions still in PLANNED status — need immediate attention.
        Groups them by how overdue they are.
        """
        _, _, _, _, _, _, Session, _, _ = _models()

        today = date.today()
        qs = Session.objects.filter(
            date__lt=today, status='PLANNED'
        ).select_related('group', 'room', 'group__teacher').order_by('-date')

        buckets = {'week': [], 'month': [], 'older': []}
        week_ago = today - timedelta(days=7)
        month_ago = today - timedelta(days=30)

        for s in qs:
            if s.date >= week_ago:
                buckets['week'].append(s)
            elif s.date >= month_ago:
                buckets['month'].append(s)
            else:
                buckets['older'].append(s)

        return {
            'total': qs.count(),
            'last_7_days': buckets['week'],
            'last_30_days': buckets['month'],
            'older': buckets['older'],
        }

    # ------------------------------------------------------------------ #
    @staticmethod
    def scheduling_health() -> dict:
        """
        Quick-check dict for the operations dashboard:
        - uncompleted_past_sessions
        - upcoming_sessions_no_room (should be 0)
        - groups_with_no_sessions_this_week
        - conflict_count
        """
        from core.utils import detect_all_conflicts
        _, CourseGroup, _, _, _, _, Session, _, _ = _models()

        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)

        uncompleted = Session.objects.filter(date__lt=today, status='PLANNED').count()

        active_groups = CourseGroup.objects.filter(is_active=True)
        groups_with_sessions_this_week = (
            Session.objects.filter(date__range=[week_start, week_end])
            .values_list('group_id', flat=True)
            .distinct()
        )
        groups_no_session = active_groups.exclude(
            id__in=groups_with_sessions_this_week
        ).count()

        try:
            conflicts = detect_all_conflicts()
            conflict_count = len(conflicts.get('schedule_conflicts', []))
        except Exception:
            conflict_count = 0

        return {
            'uncompleted_past_sessions': uncompleted,
            'groups_no_session_this_week': groups_no_session,
            'conflict_count': conflict_count,
            'health_score': _compute_health_score(uncompleted, groups_no_session, conflict_count),
        }


def _compute_health_score(uncompleted: int, no_session: int, conflicts: int) -> int:
    """0–100 operational health score. 100 = perfect."""
    score = 100
    score -= min(uncompleted * 2, 30)   # up to -30 for uncompleted sessions
    score -= min(no_session * 3, 30)    # up to -30 for idle groups
    score -= min(conflicts * 5, 40)     # up to -40 for conflicts
    return max(score, 0)


# ===========================================================================
# 7. DASHBOARD SUMMARY  (single entry-point for the director cockpit)
# ===========================================================================

def director_dashboard() -> dict:
    """
    One call to rule them all. Returns a rich dict powering the cockpit view.
    Designed to be fast: runs ~15 DB queries total via aggregation.
    """
    _, CourseGroup, _, Enrollment, Payment, Room, Session, Student, Teacher = _models()

    today = date.today()
    month_start = today.replace(day=1)
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    # ── Quick counts ─────────────────────────────────────────────────
    counts = {
        'students': Student.objects.filter(is_active=True).count(),
        'teachers': Teacher.objects.filter(is_active=True).count(),
        'groups': CourseGroup.objects.filter(is_active=True).count(),
        'rooms': Room.objects.filter(is_active=True).count(),
    }

    # ── Today's sessions ─────────────────────────────────────────────
    today_sessions = Session.objects.filter(date=today).aggregate(
        total=Count('id'),
        done=Count('id', filter=Q(status='DONE')),
        cancelled=Count('id', filter=Q(status='CANCELLED')),
        planned=Count('id', filter=Q(status='PLANNED')),
    )

    # ── This week ────────────────────────────────────────────────────
    week_sessions = Session.objects.filter(
        date__range=[week_start, week_end]
    ).aggregate(
        total=Count('id'),
        done=Count('id', filter=Q(status='DONE')),
        cancelled=Count('id', filter=Q(status='CANCELLED')),
    )

    # ── Revenue snapshot ─────────────────────────────────────────────
    revenue = RevenueAnalytics.current_month_summary()

    # ── Scheduling health ────────────────────────────────────────────
    health = OperationalAnalytics.scheduling_health()

    # ── Top-level monthly series (last 6 months, lightweight) ────────
    monthly_series = RevenueAnalytics.monthly_series(months=6)

    # ── At-risk students (quick top-5) ───────────────────────────────
    cutoff = today - timedelta(days=30)
    at_risk_preview = AttendanceAnalytics.student_absence_summary(
        start_date=cutoff, end_date=today, min_absences=2
    )[:5]

    # ── Churn signals ────────────────────────────────────────────────
    churn_preview = StudentAnalytics.churn_signals()[:5]

    return {
        'today': today,
        'counts': counts,
        'today_sessions': today_sessions,
        'week_sessions': week_sessions,
        'revenue': revenue,
        'health': health,
        'monthly_series': monthly_series,
        'at_risk_students': at_risk_preview,
        'churn_signals': churn_preview,
    }


# ===========================================================================
# 8. REPORT EXPORTER  (PDF + CSV)
# ===========================================================================

class ReportExporter:
    """
    Static methods that return a BytesIO buffer ready to serve as
    HttpResponse content. Uses ReportLab for PDF, stdlib csv for CSV.
    """

    # ── Shared ReportLab styles ───────────────────────────────────────────
    @staticmethod
    def _base_styles():
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

        styles = getSampleStyleSheet()
        DARK = colors.HexColor('#1a1a2e')
        ACCENT = colors.HexColor('#0f3460')
        LIGHT_ACCENT = colors.HexColor('#e94560')
        MUTED = colors.HexColor('#718096')
        BG_ROW_ALT = colors.HexColor('#f7fafc')

        title_style = ParagraphStyle(
            'ReportTitle',
            parent=styles['Heading1'],
            fontSize=20,
            textColor=DARK,
            fontName='Helvetica-Bold',
            spaceAfter=4,
            leading=24,
        )
        subtitle_style = ParagraphStyle(
            'ReportSubtitle',
            parent=styles['Normal'],
            fontSize=10,
            textColor=MUTED,
            fontName='Helvetica',
            spaceAfter=16,
        )
        section_style = ParagraphStyle(
            'SectionHeader',
            parent=styles['Heading2'],
            fontSize=13,
            textColor=ACCENT,
            fontName='Helvetica-Bold',
            spaceBefore=14,
            spaceAfter=6,
            borderPad=4,
        )
        body_style = ParagraphStyle(
            'Body',
            parent=styles['Normal'],
            fontSize=9,
            textColor=DARK,
            fontName='Helvetica',
        )

        return {
            'styles': styles,
            'DARK': DARK,
            'ACCENT': ACCENT,
            'LIGHT_ACCENT': LIGHT_ACCENT,
            'MUTED': MUTED,
            'BG_ROW_ALT': BG_ROW_ALT,
            'title': title_style,
            'subtitle': subtitle_style,
            'section': section_style,
            'body': body_style,
        }

    @staticmethod
    def _table_style(accent_color, alt_row_color, text_color=None):
        from reportlab.lib import colors
        from reportlab.platypus import TableStyle

        TC = text_color or colors.HexColor('#1a1a2e')

        return TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), accent_color),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('TOPPADDING', (0, 0), (-1, 0), 8),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, alt_row_color]),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('TEXTCOLOR', (0, 1), (-1, -1), TC),
            ('TOPPADDING', (0, 1), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 5),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#e2e8f0')),
            ('LINEBELOW', (0, 0), (-1, 0), 1.2, accent_color),
            ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
            ('ALIGN', (0, 1), (0, -1), 'LEFT'),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ])

    # ------------------------------------------------------------------ #
    @staticmethod
    def revenue_report_pdf(months: int = 12) -> io.BytesIO:
        """Full revenue report PDF."""
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import inch, mm
        from reportlab.platypus import (
            HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table,
        )

        S = ReportExporter._base_styles()
        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            topMargin=18*mm, bottomMargin=18*mm,
            leftMargin=18*mm, rightMargin=18*mm,
        )

        monthly = RevenueAnalytics.monthly_series(months=months)
        ytd = RevenueAnalytics.ytd_summary()
        by_group = RevenueAnalytics.revenue_by_course_group()
        methods = RevenueAnalytics.payment_method_breakdown()

        today = date.today()
        elems = []

        # Header
        elems.append(Paragraph("Rapport de Revenus", S['title']))
        elems.append(Paragraph(
            f"Généré le {today.strftime('%d/%m/%Y')}  •  {months} derniers mois",
            S['subtitle']
        ))
        elems.append(HRFlowable(width='100%', thickness=2, color=S['ACCENT']))
        elems.append(Spacer(1, 10))

        # YTD summary boxes (as a 3-col table)
        growth_str = (
            f"{'+' if ytd['growth_pct'] > 0 else ''}{ytd['growth_pct']}%"
            if ytd['growth_pct'] is not None else "N/A"
        )
        summary_data = [
            ['Revenus YTD', 'Même période an dernier', 'Croissance'],
            [
                f"{ytd['ytd']:,.0f} DH",
                f"{ytd['last_year_same_period']:,.0f} DH",
                growth_str,
            ],
        ]
        summary_table = Table(summary_data, colWidths=[55*mm, 65*mm, 45*mm])
        summary_table.setStyle(ReportExporter._table_style(S['ACCENT'], S['BG_ROW_ALT']))
        elems.append(summary_table)
        elems.append(Spacer(1, 14))

        # Monthly series
        elems.append(Paragraph("Évolution mensuelle", S['section']))
        header = ['Mois', 'Encaissé (DH)', 'Attendu (DH)', 'Taux (%)', 'Paiements', 'Payeurs']
        rows = [[
            r['month_label'],
            f"{r['revenue_paid']:,.0f}",
            f"{r['revenue_expected']:,.0f}",
            f"{r['collection_rate']}%",
            str(r['payment_count']),
            str(r['unique_payers']),
        ] for r in monthly]
        col_w = [40*mm, 32*mm, 32*mm, 22*mm, 24*mm, 24*mm]
        t = Table([header] + rows, colWidths=col_w)
        t.setStyle(ReportExporter._table_style(S['ACCENT'], S['BG_ROW_ALT']))
        elems.append(t)
        elems.append(Spacer(1, 14))

        # By group (current month)
        elems.append(Paragraph(
            f"Revenus par groupe — {today.strftime('%B %Y')}", S['section']
        ))
        g_header = ['Groupe', 'Matière', 'Élèves', 'Attendu', 'Encaissé', 'Reste', 'Taux']
        g_rows = [[
            r['group_name'],
            r['subject'],
            str(r['enrolled_count']),
            f"{r['expected']:,.0f}",
            f"{r['collected']:,.0f}",
            f"{r['outstanding']:,.0f}",
            f"{r['collection_rate']}%",
        ] for r in by_group]
        g_col_w = [40*mm, 28*mm, 16*mm, 26*mm, 26*mm, 22*mm, 18*mm]
        gt = Table([g_header] + g_rows, colWidths=g_col_w)
        gt.setStyle(ReportExporter._table_style(colors.HexColor('#0f3460'), S['BG_ROW_ALT']))
        elems.append(gt)
        elems.append(Spacer(1, 14))

        # Payment methods
        elems.append(Paragraph("Répartition des modes de paiement", S['section']))
        m_header = ['Mode', 'Total (DH)', 'Transactions', '% du total']
        m_rows = [[
            r['label'],
            f"{r['total']:,.0f}",
            str(r['count']),
            f"{r['pct']}%",
        ] for r in methods]
        mt = Table([m_header] + m_rows, colWidths=[45*mm, 40*mm, 40*mm, 40*mm])
        mt.setStyle(ReportExporter._table_style(colors.HexColor('#2d6a4f'), S['BG_ROW_ALT']))
        elems.append(mt)

        doc.build(elems)
        buf.seek(0)
        return buf

    # ------------------------------------------------------------------ #
    @staticmethod
    def attendance_report_pdf(start_date: date, end_date: date) -> io.BytesIO:
        """Absence analytics PDF."""
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table,
        )

        S = ReportExporter._base_styles()
        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            topMargin=18*mm, bottomMargin=18*mm,
            leftMargin=18*mm, rightMargin=18*mm,
        )

        students = AttendanceAnalytics.student_absence_summary(start_date, end_date)
        weekly = AttendanceAnalytics.weekly_trend(weeks=8)
        groups = AttendanceAnalytics.group_attendance_matrix(start_date.replace(day=1))

        elems = []
        elems.append(Paragraph("Rapport de Présences & Absences", S['title']))
        elems.append(Paragraph(
            f"Période : {start_date.strftime('%d/%m/%Y')} → {end_date.strftime('%d/%m/%Y')}",
            S['subtitle']
        ))
        elems.append(HRFlowable(width='100%', thickness=2, color=S['ACCENT']))
        elems.append(Spacer(1, 10))

        # Summary KPIs
        total_students = len(students)
        at_risk = sum(1 for s in students if s['is_at_risk'])
        high_risk = sum(1 for s in students if s['risk_level'] == 'HIGH_RISK')
        kpi_data = [
            ['Élèves analysés', 'À risque (>20%)', 'Critique (>35%)', 'Seuil d\'alerte'],
            [str(total_students), str(at_risk), str(high_risk), '20%'],
        ]
        kt = Table(kpi_data, colWidths=[45*mm, 42*mm, 42*mm, 42*mm])
        kt.setStyle(ReportExporter._table_style(S['ACCENT'], S['BG_ROW_ALT']))
        elems.append(kt)
        elems.append(Spacer(1, 14))

        # At-risk students
        elems.append(Paragraph("Élèves à risque", S['section']))
        at_risk_students = [s for s in students if s['is_at_risk']]
        if at_risk_students:
            s_header = ['Élève', 'Séances', 'Absences', 'Taux', 'Niveau de risque', 'Absences consécutives']
            s_rows = [[
                s['student_name'],
                str(s['total_sessions']),
                str(s['absences']),
                f"{s['absence_rate']}%",
                {'HIGH_RISK': '🔴 Critique', 'AT_RISK': '🟠 À risque'}.get(s['risk_level'], ''),
                str(s['consecutive_absences']),
            ] for s in at_risk_students]
            st = Table([s_header] + s_rows, colWidths=[42*mm, 20*mm, 22*mm, 16*mm, 34*mm, 40*mm])
            st.setStyle(ReportExporter._table_style(colors.HexColor('#c0392b'), S['BG_ROW_ALT']))
            elems.append(st)
        else:
            elems.append(Paragraph("Aucun élève à risque sur cette période. ✓", S['body']))
        elems.append(Spacer(1, 14))

        # Weekly trend
        elems.append(Paragraph("Tendance hebdomadaire des absences", S['section']))
        w_header = ['Semaine', 'Total séances', 'Absences', 'Taux d\'absence']
        w_rows = [[
            r['week_label'],
            str(r['total']),
            str(r['absences']),
            f"{r['absence_rate']}%",
        ] for r in weekly]
        wt = Table([w_header] + w_rows, colWidths=[55*mm, 40*mm, 35*mm, 40*mm])
        wt.setStyle(ReportExporter._table_style(colors.HexColor('#2980b9'), S['BG_ROW_ALT']))
        elems.append(wt)
        elems.append(Spacer(1, 14))

        # By group
        elems.append(Paragraph("Absences par groupe de cours", S['section']))
        g_header = ['Groupe', 'Matière', 'Séances', 'Absences', 'Taux']
        g_rows = [[
            r['group_name'],
            r['subject'],
            str(r['total_records']),
            str(r['absences']),
            f"{r['absence_rate']}%",
        ] for r in groups if r['total_records'] > 0]
        if g_rows:
            gt = Table([g_header] + g_rows, colWidths=[48*mm, 35*mm, 28*mm, 28*mm, 28*mm])
            gt.setStyle(ReportExporter._table_style(colors.HexColor('#8e44ad'), S['BG_ROW_ALT']))
            elems.append(gt)

        doc.build(elems)
        buf.seek(0)
        return buf

    # ------------------------------------------------------------------ #
    @staticmethod
    def teacher_payroll_pdf(start_date: date, end_date: date) -> io.BytesIO:
        """Teacher payroll summary PDF."""
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table,
        )

        S = ReportExporter._base_styles()
        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            topMargin=18*mm, bottomMargin=18*mm,
            leftMargin=18*mm, rightMargin=18*mm,
        )

        payroll = TeacherAnalytics.payroll_summary(start_date, end_date)
        load = TeacherAnalytics.weekly_load()
        subs = TeacherAnalytics.substitution_rate()

        elems = []
        elems.append(Paragraph("Rapport de Paie Enseignants", S['title']))
        elems.append(Paragraph(
            f"Période : {start_date.strftime('%d/%m/%Y')} → {end_date.strftime('%d/%m/%Y')}",
            S['subtitle']
        ))
        elems.append(HRFlowable(width='100%', thickness=2, color=S['ACCENT']))
        elems.append(Spacer(1, 10))

        METHOD_LABEL = {'HOURLY': 'Horaire', 'PERCENTAGE': 'Pourcentage', 'SESSION': 'Par séance'}
        p_header = ['Enseignant', 'Mode', 'Séances', 'Heures', 'Rémunération (DH)']
        p_rows = [[
            r['teacher_name'],
            METHOD_LABEL.get(r['payment_method'], r['payment_method']),
            str(r['total_sessions']),
            f"{r.get('total_hours', 0):.1f}h",
            f"{r.get('earnings', 0) or 0:,.0f}",
        ] for r in payroll]

        total_earnings = sum(r.get('earnings', 0) or 0 for r in payroll)
        p_rows.append(['TOTAL', '', '', '', f"{total_earnings:,.0f}"])

        pt = Table([p_header] + p_rows, colWidths=[50*mm, 32*mm, 28*mm, 28*mm, 40*mm])
        ts = ReportExporter._table_style(S['ACCENT'], S['BG_ROW_ALT'])
        ts.add('FONTNAME', (0, len(p_rows)), (-1, len(p_rows)), 'Helvetica-Bold')
        ts.add('BACKGROUND', (0, len(p_rows)), (-1, len(p_rows)), colors.HexColor('#edf2f7'))
        pt.setStyle(ts)
        elems.append(Paragraph("Résumé de paie", S['section']))
        elems.append(pt)
        elems.append(Spacer(1, 14))

        # Weekly load
        elems.append(Paragraph("Charge hebdomadaire planifiée", S['section']))
        l_header = ['Enseignant', 'Heures/semaine', 'Séances', 'Statut']
        FLAG_LABEL = {'OVERLOADED': '⚠ Surchargé', 'UNDERUTILISED': '↓ Sous-utilisé', 'NORMAL': '✓ Normal'}
        l_rows = [[
            r['teacher_name'],
            f"{r['weekly_hours']}h",
            str(r['session_count']),
            FLAG_LABEL.get(r['load_flag'], r['load_flag']),
        ] for r in load]
        lt = Table([l_header] + l_rows, colWidths=[55*mm, 40*mm, 32*mm, 45*mm])
        lt.setStyle(ReportExporter._table_style(colors.HexColor('#2d6a4f'), S['BG_ROW_ALT']))
        elems.append(lt)
        elems.append(Spacer(1, 14))

        # Substitution rates
        elems.append(Paragraph("Taux de remplacement (3 derniers mois)", S['section']))
        sub_data = [s for s in subs if s['total_sessions'] > 0]
        su_header = ['Enseignant', 'Séances totales', 'Remplacé', 'Taux de remplacement']
        su_rows = [[
            r['teacher_name'],
            str(r['total_sessions']),
            str(r['substituted_sessions']),
            f"{r['substitution_rate']}%",
        ] for r in sub_data]
        sut = Table([su_header] + su_rows, colWidths=[55*mm, 38*mm, 32*mm, 48*mm])
        sut.setStyle(ReportExporter._table_style(colors.HexColor('#8e44ad'), S['BG_ROW_ALT']))
        elems.append(sut)

        doc.build(elems)
        buf.seek(0)
        return buf

    # ------------------------------------------------------------------ #
    @staticmethod
    def churn_report_pdf() -> io.BytesIO:
        """At-risk / churn signals PDF report."""
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table,
        )

        S = ReportExporter._base_styles()
        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            topMargin=18*mm, bottomMargin=18*mm,
            leftMargin=18*mm, rightMargin=18*mm,
        )

        churn = StudentAnalytics.churn_signals()
        ltv = StudentAnalytics.lifetime_value()
        multi = StudentAnalytics.multi_group_students()

        elems = []
        elems.append(Paragraph("Rapport Rétention Élèves", S['title']))
        elems.append(Paragraph(
            f"Généré le {date.today().strftime('%d/%m/%Y')}",
            S['subtitle']
        ))
        elems.append(HRFlowable(width='100%', thickness=2, color=S['LIGHT_ACCENT']))
        elems.append(Spacer(1, 10))

        # Churn signals
        elems.append(Paragraph(f"Signaux de départ ({len(churn)} élèves)", S['section']))
        if churn:
            c_header = ['Élève', 'Groupes', 'Signaux détectés']
            c_rows = [[
                r['student_name'],
                ', '.join(r['groups'][:2]) + ('…' if len(r['groups']) > 2 else ''),
                ' | '.join(r['signals']),
            ] for r in churn]
            ct = Table([c_header] + c_rows, colWidths=[40*mm, 45*mm, 85*mm])
            ct.setStyle(ReportExporter._table_style(S['LIGHT_ACCENT'], S['BG_ROW_ALT']))
            elems.append(ct)
        else:
            elems.append(Paragraph("Aucun signal de départ détecté. ✓", S['body']))
        elems.append(Spacer(1, 14))

        # Lifetime value top 20
        elems.append(Paragraph("Valeur vie client – Top 20", S['section']))
        l_header = ['Élève', 'Total payé (DH)', 'Mois actif', 'Moy./mois', 'Dernier paiement']
        l_rows = [[
            r['student_name'],
            f"{r['total_paid']:,.0f}",
            str(r['months_active']),
            f"{r['avg_per_month']:,.0f}",
            r['last_payment'].strftime('%d/%m/%Y') if r['last_payment'] else '',
        ] for r in ltv]
        lt = Table([l_header] + l_rows, colWidths=[45*mm, 35*mm, 25*mm, 30*mm, 33*mm])
        lt.setStyle(ReportExporter._table_style(colors.HexColor('#2d6a4f'), S['BG_ROW_ALT']))
        elems.append(lt)
        elems.append(Spacer(1, 14))

        # Multi-group students
        elems.append(Paragraph("Élèves multi-groupes (fidèles)", S['section']))
        m_header = ['Élève', 'Nombre de groupes']
        m_rows = [[r['student_name'], str(r['group_count'])] for r in multi[:20]]
        if m_rows:
            mt = Table([m_header] + m_rows, colWidths=[100*mm, 70*mm])
            mt.setStyle(ReportExporter._table_style(S['ACCENT'], S['BG_ROW_ALT']))
            elems.append(mt)

        doc.build(elems)
        buf.seek(0)
        return buf

    # ------------------------------------------------------------------ #
    @staticmethod
    def export_csv(data: list[dict], filename_hint: str = 'export') -> io.StringIO:
        """
        Generic CSV export. Pass any list of flat dicts.
        Returns a StringIO object.
        """
        if not data:
            buf = io.StringIO()
            buf.write("No data\n")
            buf.seek(0)
            return buf

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(data[0].keys()))
        writer.writeheader()
        for row in data:
            # Coerce Decimal / date to str for CSV
            clean = {}
            for k, v in row.items():
                if isinstance(v, Decimal):
                    clean[k] = str(v)
                elif isinstance(v, date):
                    clean[k] = v.strftime('%Y-%m-%d')
                elif isinstance(v, list):
                    clean[k] = '; '.join(str(x) for x in v)
                else:
                    clean[k] = v
            writer.writerow(clean)

        buf.seek(0)
        return buf


# ===========================================================================
# CONVENIENCE VIEW HELPERS
# (paste these into views.py or a dedicated analytics_views.py)
# ===========================================================================

ANALYTICS_VIEW_HELPERS = '''
# ── Paste into views.py ──────────────────────────────────────────────────────

from django.http import HttpResponse
from datetime import date
from dateutil.relativedelta import relativedelta
from core.analytics import (
    RevenueAnalytics, AttendanceAnalytics, TeacherAnalytics,
    StudentAnalytics, OperationalAnalytics, director_dashboard,
    ReportExporter,
)


def analytics_dashboard(request):
    """Main analytics hub."""
    data = director_dashboard()
    return render(request, 'core/analytics_dashboard.html', data)


def analytics_revenue(request):
    months = int(request.GET.get('months', 12))
    context = {
        'monthly_series': RevenueAnalytics.monthly_series(months),
        'ytd': RevenueAnalytics.ytd_summary(),
        'by_group': RevenueAnalytics.revenue_by_course_group(),
        'methods': RevenueAnalytics.payment_method_breakdown(),
        'current_month': RevenueAnalytics.current_month_summary(),
        'months': months,
    }
    return render(request, 'core/analytics_revenue.html', context)


def analytics_attendance(request):
    today = date.today()
    start_str = request.GET.get('start_date', today.replace(day=1).isoformat())
    end_str = request.GET.get('end_date', today.isoformat())
    from datetime import datetime
    start = datetime.strptime(start_str, '%Y-%m-%d').date()
    end = datetime.strptime(end_str, '%Y-%m-%d').date()
    context = {
        'students': AttendanceAnalytics.student_absence_summary(start, end),
        'weekly': AttendanceAnalytics.weekly_trend(),
        'groups': AttendanceAnalytics.group_attendance_matrix(start.replace(day=1)),
        'heatmap': AttendanceAnalytics.daily_absence_heatmap(start.replace(day=1)),
        'start_date': start_str, 'end_date': end_str,
    }
    return render(request, 'core/analytics_attendance.html', context)


def analytics_operational(request):
    context = {
        'completion': OperationalAnalytics.session_completion_rate(months=6),
        'cancellations': OperationalAnalytics.cancellation_reasons_by_group(),
        'uncompleted': OperationalAnalytics.uncompleted_sessions(),
        'health': OperationalAnalytics.scheduling_health(),
    }
    return render(request, 'core/analytics_operational.html', context)


def analytics_students(request):
    context = {
        'enrollment_trend': StudentAnalytics.enrollment_trend(),
        'churn': StudentAnalytics.churn_signals(),
        'ltv': StudentAnalytics.lifetime_value(),
        'multi_group': StudentAnalytics.multi_group_students(),
    }
    return render(request, 'core/analytics_students.html', context)


# ── PDF export views ─────────────────────────────────────────────────────────

def export_revenue_pdf(request):
    months = int(request.GET.get('months', 12))
    buf = ReportExporter.revenue_report_pdf(months=months)
    resp = HttpResponse(buf.read(), content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="revenus_{date.today()}.pdf"'
    return resp


def export_attendance_pdf(request):
    today = date.today()
    start = (today - relativedelta(months=1)).replace(day=1)
    end = today
    buf = ReportExporter.attendance_report_pdf(start, end)
    resp = HttpResponse(buf.read(), content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="absences_{date.today()}.pdf"'
    return resp


def export_payroll_pdf(request):
    today = date.today()
    start = today.replace(day=1)
    end = today
    buf = ReportExporter.teacher_payroll_pdf(start, end)
    resp = HttpResponse(buf.read(), content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="paie_{date.today()}.pdf"'
    return resp


def export_churn_pdf(request):
    buf = ReportExporter.churn_report_pdf()
    resp = HttpResponse(buf.read(), content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="retention_{date.today()}.pdf"'
    return resp


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
        data = TeacherAnalytics.payroll_summary(today.replace(day=1), today)
        fname = f'paie_{today}.csv'
    else:
        data = []
        fname = 'export.csv'

    buf = ReportExporter.export_csv(data)
    resp = HttpResponse(buf.read(), content_type='text/csv; charset=utf-8')
    resp['Content-Disposition'] = f'attachment; filename="{fname}"'
    return resp
'''