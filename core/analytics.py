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

        from core.models import Expense, TeacherPayment

        for i in range(months - 1, -1, -1):
            month_start = (today - relativedelta(months=i)).replace(day=1)
            month_end = month_start + relativedelta(months=1) - timedelta(days=1)

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
            expected = (
                Enrollment.objects.filter(
                    is_active=True,
                    enrolled_date__lte=month_end,
                ).aggregate(
                    total=Sum('course_group__monthly_price')
                )['total'] or Decimal('0')
            )

            collection_rate = (
                round(float(revenue_paid / expected) * 100, 1)
                if expected > 0 else 0.0
            )

            # Monthly general expenses
            month_expenses = Expense.objects.filter(
                expense_date__range=[month_start, month_end]
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

            # Monthly teacher payments
            month_teacher_pay = TeacherPayment.objects.filter(
                Q(period_year=month_start.year, period_month=month_start.month) |
                Q(payment_date__range=[month_start, month_end])
            ).distinct().aggregate(total=Sum('amount'))['total'] or Decimal('0')

            total_charges = month_expenses + month_teacher_pay
            net_profit = revenue_paid - total_charges
            profit_margin = round(float(net_profit / revenue_paid) * 100, 1) if revenue_paid > 0 else 0.0

            rows.append({
                'month_label': f"{month_name_fr(month_start.month)} {month_start.year}",
                'month_str': month_start.strftime('%Y-%m'),
                'month_date': month_start,
                'revenue_paid': revenue_paid,
                'revenue_expected': expected,
                'collection_rate': collection_rate,
                'payment_count': payment_count,
                'unique_payers': unique_payers,
                'expenses': month_expenses,
                'teacher_payments': month_teacher_pay,
                'total_charges': total_charges,
                'net_profit': net_profit,
                'profit_margin': profit_margin,
            })

        return rows

    # ------------------------------------------------------------------ #
    @staticmethod
    def current_month_summary() -> dict:
        """
        Snapshot for the current month: collected, expenses, teacher payments, net profit, outstanding, overdue students.
        """
        Attendance, CourseGroup, _, Enrollment, Payment, _, _, Student, _ = _models()
        from core.utils import calculate_student_monthly_total
        from core.models import Expense, TeacherPayment

        today = date.today()
        month_start = today.replace(day=1)
        month_end = month_start + relativedelta(months=1) - timedelta(days=1)

        collected = Payment.objects.filter(
            month_covered=month_start, status='PAID'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        # Month general expenses
        exp_agg = Expense.objects.filter(
            expense_date__range=[month_start, month_end]
        ).aggregate(total=Sum('amount'), count=Count('id'))
        month_expenses = exp_agg['total'] or Decimal('0')
        expenses_count = exp_agg['count'] or 0

        # Month teacher payments
        tp_agg = TeacherPayment.objects.filter(
            Q(period_year=month_start.year, period_month=month_start.month) |
            Q(payment_date__range=[month_start, month_end])
        ).distinct().aggregate(total=Sum('amount'), count=Count('id'))
        month_teacher_pay = tp_agg['total'] or Decimal('0')
        teacher_payments_count = tp_agg['count'] or 0

        total_charges = month_expenses + month_teacher_pay
        net_profit = collected - total_charges
        profit_margin = round(float(net_profit / collected) * 100, 1) if collected > 0 else 0.0

        active_students = Student.objects.filter(is_active=True).prefetch_related(
            'enrollment_set__course_group'
        )

        total_expected = Decimal('0')
        total_outstanding = Decimal('0')
        unpaid_count = 0
        partial_count = 0

        # Check completed exceptions set for current month
        completed_exceptions = set(
            Payment.objects.filter(
                month_covered=month_start,
                status='PAID',
                is_completed=True
            ).values_list('student_id', flat=True)
        )

        for student in active_students:
            required = calculate_student_monthly_total(student)
            if required == 0:
                continue
            paid = Payment.objects.filter(
                student=student, month_covered=month_start, status='PAID'
            ).aggregate(t=Sum('amount'))['t'] or Decimal('0')
            total_expected += required
            
            if student.id in completed_exceptions:
                continue

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
            'expenses': month_expenses,
            'expenses_count': expenses_count,
            'teacher_payments': month_teacher_pay,
            'teacher_payments_count': teacher_payments_count,
            'total_charges': total_charges,
            'net_profit': net_profit,
            'profit_margin': profit_margin,
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

        from core.models import Expense, TeacherPayment
        ytd_expenses = Expense.objects.filter(
            expense_date__range=[ytd_start, today]
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        ytd_teacher_payments = TeacherPayment.objects.filter(
            payment_date__range=[ytd_start, today]
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        ytd_total_charges = ytd_expenses + ytd_teacher_payments
        ytd_net_profit = ytd - ytd_total_charges
        ytd_margin = round(float(ytd_net_profit / ytd) * 100, 1) if ytd > 0 else 0.0

        return {
            'ytd': ytd,
            'ytd_expenses': ytd_expenses,
            'ytd_teacher_payments': ytd_teacher_payments,
            'ytd_total_charges': ytd_total_charges,
            'ytd_net_profit': ytd_net_profit,
            'ytd_margin': ytd_margin,
            'last_year_same_period': ly,
            'growth_pct': growth,
            'ytd_start': ytd_start,
            'today': today,
        }

    # ------------------------------------------------------------------ #
    @staticmethod
    def teacher_payments_summary(month_start: date | None = None) -> dict:
        """Overview of teacher payroll payments for the selected month."""
        from core.models import TeacherPayment
        if month_start is None:
            month_start = date.today().replace(day=1)
        month_end = month_start + relativedelta(months=1) - timedelta(days=1)

        payments = TeacherPayment.objects.filter(
            Q(period_year=month_start.year, period_month=month_start.month) |
            Q(payment_date__range=[month_start, month_end])
        ).distinct().select_related('teacher').order_by('-payment_date', '-id')

        total = sum((p.amount for p in payments), Decimal('0.00'))

        teacher_totals = defaultdict(lambda: {'total': Decimal('0.00'), 'count': 0})
        for p in payments:
            teacher_totals[p.teacher.name]['total'] += p.amount
            teacher_totals[p.teacher.name]['count'] += 1

        return {
            'count': len(payments),
            'total': total,
            'items': [
                {
                    'id': p.id,
                    'teacher_name': p.teacher.name,
                    'teacher_phone': p.teacher.phone,
                    'amount': p.amount,
                    'payment_date': p.payment_date,
                    'payment_method': p.get_payment_method_display(),
                    'payment_type': p.get_payment_type_display(),
                    'period': f"{p.period_month:02d}/{p.period_year}",
                    'notes': p.notes,
                }
                for p in payments
            ],
            'by_teacher': [
                {'teacher_name': k, 'total': v['total'], 'count': v['count']}
                for k, v in sorted(teacher_totals.items(), key=lambda x: x[1]['total'], reverse=True)
            ]
        }

    # ------------------------------------------------------------------ #
    @staticmethod
    def exceptions_summary(month_start: date | None = None) -> dict:
        """Overview of payments completed by exception (discount/waiver granted)."""
        Attendance, CourseGroup, _, Enrollment, Payment, _, _, Student, _ = _models()
        from core.utils import calculate_student_expected_fees_for_month

        if month_start is None:
            month_start = date.today().replace(day=1)

        exception_payments = Payment.objects.filter(
            month_covered=month_start,
            status='PAID',
            is_completed=True
        ).select_related('student')

        items = []
        total_collected = Decimal('0.00')
        total_expected = Decimal('0.00')

        for p in exception_payments:
            exp_fees = calculate_student_expected_fees_for_month(p.student, month_start)
            discount = max(Decimal('0.00'), exp_fees - p.amount)
            total_collected += p.amount
            total_expected += exp_fees
            items.append({
                'payment_id': p.id,
                'receipt_number': p.receipt_number,
                'student_id': p.student.id,
                'student_name': p.student.name,
                'student_matricule': p.student.matricule,
                'amount_collected': p.amount,
                'expected_fees': exp_fees,
                'discount_granted': discount,
                'payment_date': p.payment_date,
                'payment_method': p.get_payment_method_display(),
                'notes': p.notes,
                'created_by': p.created_by,
            })

        total_discount = max(Decimal('0.00'), total_expected - total_collected)

        return {
            'count': len(items),
            'total_collected': total_collected,
            'total_expected': total_expected,
            'total_discount': total_discount,
            'items': items,
        }

    # ------------------------------------------------------------------ #
    @staticmethod
    def expenses_by_category(months: int = 1) -> list[dict]:
        """Expenses categorized breakdown for given period."""
        from core.models import Expense, ExpenseCategory
        today = date.today()
        start = (today - relativedelta(months=months - 1)).replace(day=1)

        qs = (
            Expense.objects.filter(expense_date__gte=start)
            .values('category')
            .annotate(total=Sum('amount'), count=Count('id'))
            .order_by('-total')
        )
        cat_dict = dict(ExpenseCategory.choices)
        grand_total = sum(r['total'] for r in qs) or Decimal('1')

        colors = {
            'RENT': '#6366f1',
            'UTILITIES': '#3b82f6',
            'SALARY': '#10b981',
            'SUPPLIES': '#f59e0b',
            'MAINTENANCE': '#ec4899',
            'MARKETING': '#8b5cf6',
            'TEACHER_PAY': '#06b6d4',
            'REFUND': '#ef4444',
            'OTHER': '#64748b',
        }

        return [
            {
                'category': r['category'],
                'label': cat_dict.get(r['category'], r['category']),
                'total': r['total'],
                'count': r['count'],
                'pct': round(float(r['total'] / grand_total) * 100, 1),
                'color': colors.get(r['category'], '#64748b'),
            }
            for r in qs
        ]


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
# 8. REPORT EXPORTER (PDF + CSV)
# ===========================================================================

from reportlab.pdfgen import canvas

class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas that adds running headers, running footers,
    and accurate 'Page X sur Y' numbering across all document pages.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_decorations(self, page_count):
        from reportlab.lib import colors
        from reportlab.lib.units import mm
        self.saveState()
        self.setFont('Helvetica', 8)
        self.setFillColor(colors.HexColor('#64748b'))
        page_w, page_h = self._pagesize

        # Running header on pages > 1
        if self._pageNumber > 1:
            self.setStrokeColor(colors.HexColor('#e2e8f0'))
            self.setLineWidth(0.6)
            self.line(14 * mm, page_h - 10 * mm, page_w - 14 * mm, page_h - 10 * mm)
            self.drawString(14 * mm, page_h - 8 * mm, "Rapport d'Analyse & Gestion — Document de Synthèse")
            self.drawRightString(page_w - 14 * mm, page_h - 8 * mm, "Direction & Administration")

        # Running footer on all pages
        self.setStrokeColor(colors.HexColor('#e2e8f0'))
        self.setLineWidth(0.6)
        self.line(14 * mm, 12 * mm, page_w - 14 * mm, 12 * mm)
        self.drawString(14 * mm, 7 * mm, "Document Confidentiel — Usage Interne")
        self.drawRightString(page_w - 14 * mm, 7 * mm, f"Page {self._pageNumber} sur {page_count}")
        self.restoreState()


class ReportExporter:
    """
    Static methods that return a BytesIO buffer ready to serve as
    HttpResponse content. Uses ReportLab for PDF, stdlib csv for CSV.
    """

    @staticmethod
    def _base_styles():
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

        styles = getSampleStyleSheet()
        DARK = colors.HexColor('#0f172a')
        ACCENT = colors.HexColor('#1e3a8a')
        PRIMARY = colors.HexColor('#2563eb')
        SUCCESS = colors.HexColor('#059669')
        DANGER = colors.HexColor('#dc2626')
        WARNING = colors.HexColor('#d97706')
        MUTED = colors.HexColor('#64748b')
        BG_ROW_ALT = colors.HexColor('#f8fafc')

        title_style = ParagraphStyle(
            'ReportTitle',
            parent=styles['Heading1'],
            fontSize=17,
            textColor=DARK,
            fontName='Helvetica-Bold',
            spaceAfter=3,
            leading=21,
        )
        subtitle_style = ParagraphStyle(
            'ReportSubtitle',
            parent=styles['Normal'],
            fontSize=9,
            textColor=MUTED,
            fontName='Helvetica',
            spaceAfter=12,
            leading=12,
        )
        section_style = ParagraphStyle(
            'SectionHeader',
            parent=styles['Heading2'],
            fontSize=11,
            textColor=ACCENT,
            fontName='Helvetica-Bold',
            spaceBefore=12,
            spaceAfter=5,
            borderPad=3,
        )
        body_style = ParagraphStyle(
            'Body',
            parent=styles['Normal'],
            fontSize=8,
            textColor=DARK,
            fontName='Helvetica',
            leading=11,
        )

        return {
            'styles': styles,
            'DARK': DARK,
            'ACCENT': ACCENT,
            'PRIMARY': PRIMARY,
            'SUCCESS': SUCCESS,
            'DANGER': DANGER,
            'WARNING': WARNING,
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

        TC = text_color or colors.HexColor('#0f172a')

        return TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), accent_color),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('TOPPADDING', (0, 0), (-1, 0), 6),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, alt_row_color]),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 7.5),
            ('TEXTCOLOR', (0, 1), (-1, -1), TC),
            ('TOPPADDING', (0, 1), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#e2e8f0')),
            ('LINEBELOW', (0, 0), (-1, 0), 1.2, accent_color),
            ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
            ('ALIGN', (0, 1), (0, -1), 'LEFT'),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ])

    @staticmethod
    def revenue_report_pdf(months: int = 12):
        """
        Full financial & profitability report PDF in landscape format.
        Features P&L statement, general expenses, teacher payroll, waivers/exceptions,
        and course group performance.
        """
        import io
        from datetime import date
        from decimal import Decimal
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        )
        from core.utils import get_setting

        S = ReportExporter._base_styles()
        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=landscape(A4),
            topMargin=12*mm, bottomMargin=16*mm,
            leftMargin=14*mm, rightMargin=14*mm,
        )

        monthly = RevenueAnalytics.monthly_series(months=months)
        ytd = RevenueAnalytics.ytd_summary()
        current = RevenueAnalytics.current_month_summary()
        by_group = RevenueAnalytics.revenue_by_course_group()
        methods = RevenueAnalytics.payment_method_breakdown()
        exceptions = RevenueAnalytics.exceptions_summary()
        cat_expenses = RevenueAnalytics.expenses_by_category(months=months)
        teachers_summary = RevenueAnalytics.teacher_payments_summary()

        today = date.today()
        school_name = get_setting('CENTER_NAME') or get_setting('SCHOOL_NAME', 'Établissement')
        elems = []

        # Document Header
        header_table = Table([
            [
                Paragraph(f"<font size=9 color='#64748b'><b>{school_name.upper()}</b></font><br/><font size=16 color='#0f172a'><b>Rapport Financier &amp; Compte de Résultat Consolidé</b></font>", S['title']),
                Paragraph(f"<font color='#64748b'>Édité le : <b>{today.strftime('%d/%m/%Y')}</b><br/>Période d'analyse : <b>{months} derniers mois</b><br/>Devise : <b>MAD (DH)</b></font>", S['body']),
            ]
        ], colWidths=[185*mm, 84*mm])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        elems.append(header_table)
        elems.append(Spacer(1, 3))
        elems.append(HRFlowable(width='100%', thickness=1.5, color=S['ACCENT']))
        elems.append(Spacer(1, 7))

        # Executive KPI Summary Grid (6 Cards)
        tot_rev = sum((r['revenue_paid'] for r in monthly), Decimal('0'))
        tot_exp = sum((r['expenses'] for r in monthly), Decimal('0'))
        tot_teach = sum((r['teacher_payments'] for r in monthly), Decimal('0'))
        tot_charges = tot_exp + tot_teach
        tot_net = tot_rev - tot_charges
        tot_margin = round(float(tot_net / tot_rev) * 100, 1) if tot_rev > 0 else 0.0

        kpi_cells = [
            [
                Paragraph(f"<font size=7 color='#64748b'><b>REVENUS ENCAISSÉS</b></font><br/><font size=12 color='#059669'><b>{tot_rev:,.0f} DH</b></font><br/><font size=7 color='#64748b'>Sur {months} mois</font>", S['body']),
                Paragraph(f"<font size=7 color='#64748b'><b>DÉPENSES GÉNÉRALES</b></font><br/><font size=12 color='#dc2626'><b>{tot_exp:,.0f} DH</b></font><br/><font size=7 color='#64748b'>Charges fixes &amp; matériel</font>", S['body']),
                Paragraph(f"<font size=7 color='#64748b'><b>PAIE ENSEIGNANTS</b></font><br/><font size=12 color='#d97706'><b>{tot_teach:,.0f} DH</b></font><br/><font size=7 color='#64748b'>Rémunérations versées</font>", S['body']),
                Paragraph(f"<font size=7 color='#64748b'><b>CHARGES TOTALES</b></font><br/><font size=12 color='#4b5563'><b>{tot_charges:,.0f} DH</b></font><br/><font size=7 color='#64748b'>Dépenses + Paie profs</font>", S['body']),
                Paragraph(f"<font size=7 color='#64748b'><b>RÉSULTAT NET RÉEL</b></font><br/><font size=12 color='{'#059669' if tot_net >= 0 else '#dc2626'}'><b>{tot_net:,.0f} DH</b></font><br/><font size=7 color='#64748b'>{'Bénéfice net' if tot_net >= 0 else 'Déficit d\'exploitation'}</font>", S['body']),
                Paragraph(f"<font size=7 color='#64748b'><b>MARGE NETTE MOYENNE</b></font><br/><font size=12 color='{'#059669' if tot_margin >= 0 else '#dc2626'}'><b>{tot_margin}%</b></font><br/><font size=7 color='#64748b'>Rentabilité globale</font>", S['body']),
            ]
        ]
        kpi_table = Table(kpi_cells, colWidths=[44.8*mm]*6)
        kpi_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#cbd5e1')),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ]))
        elems.append(kpi_table)
        elems.append(Spacer(1, 9))

        # 1. Compte de Résultat Consolidé (Évolution Mensuelle P&L)
        elems.append(Paragraph("1. Compte de Résultat Consolidé (Évolution Mensuelle)", S['section']))
        pnl_header = [
            'Mois', 'Encaissé (DH)', 'Attendu (DH)', 'Recouvr.',
            'Dépenses Gén.', 'Paie Profs', 'Total Charges', 'Résultat Net', 'Marge %', 'Paiements'
        ]
        pnl_rows = []
        for r in monthly:
            pnl_rows.append([
                r['month_label'],
                f"{r['revenue_paid']:,.0f}",
                f"{r['revenue_expected']:,.0f}",
                f"{r['collection_rate']}%",
                f"{r['expenses']:,.0f}",
                f"{r['teacher_payments']:,.0f}",
                f"{r['total_charges']:,.0f}",
                f"{r['net_profit']:,.0f}",
                f"{r['profit_margin']}%",
                f"{r['payment_count']} ({r['unique_payers']} p.)",
            ])

        tot_exp_calc = sum(r['revenue_expected'] for r in monthly)
        tot_coll_rate = round(float(tot_rev / tot_exp_calc) * 100, 1) if tot_exp_calc > 0 else 0.0
        tot_payments = sum(r['payment_count'] for r in monthly)
        pnl_rows.append([
            'TOTAL PÉRIODE',
            f"{tot_rev:,.0f}",
            f"{tot_exp_calc:,.0f}",
            f"{tot_coll_rate}%",
            f"{tot_exp:,.0f}",
            f"{tot_teach:,.0f}",
            f"{tot_charges:,.0f}",
            f"{tot_net:,.0f}",
            f"{tot_margin}%",
            f"{tot_payments}",
        ])

        col_w = [34*mm, 28*mm, 28*mm, 18*mm, 27*mm, 27*mm, 28*mm, 29*mm, 18*mm, 32*mm]
        pnl_table = Table([pnl_header] + pnl_rows, colWidths=col_w)
        ts = ReportExporter._table_style(S['ACCENT'], S['BG_ROW_ALT'])
        tot_idx = len(pnl_rows)
        ts.add('FONTNAME', (0, tot_idx), (-1, tot_idx), 'Helvetica-Bold')
        ts.add('BACKGROUND', (0, tot_idx), (-1, tot_idx), colors.HexColor('#e2e8f0'))
        ts.add('LINEABOVE', (0, tot_idx), (-1, tot_idx), 1.2, S['ACCENT'])
        pnl_table.setStyle(ts)
        elems.append(pnl_table)
        elems.append(Spacer(1, 10))

        # 2. Répartition des Dépenses Générales & Modes de Paiement (2 colonnes)
        exp_header = ['Catégorie de Dépense', 'Montant (DH)', 'Nb', '% Charges']
        exp_rows = []
        for c in cat_expenses:
            exp_rows.append([
                c['label'],
                f"{c['total']:,.0f}",
                str(c['count']),
                f"{c['pct']}%",
            ])
        if not exp_rows:
            exp_rows = [['Aucune dépense enregistrée sur la période', '0', '0', '0%']]
        
        t_exp = Table([exp_header] + exp_rows, colWidths=[55*mm, 30*mm, 18*mm, 27*mm])
        t_exp.setStyle(ReportExporter._table_style(colors.HexColor('#991b1b'), S['BG_ROW_ALT']))

        meth_header = ['Mode d\'Encaissement', 'Total (DH)', 'Transactions', '% du Total']
        meth_rows = [[
            m['label'],
            f"{m['total']:,.0f}",
            str(m['count']),
            f"{m['pct']}%",
        ] for m in methods] if methods else [['Aucun paiement', '0', '0', '0%']]
        t_meth = Table([meth_header] + meth_rows, colWidths=[55*mm, 30*mm, 25*mm, 20*mm])
        t_meth.setStyle(ReportExporter._table_style(colors.HexColor('#166534'), S['BG_ROW_ALT']))

        side_by_side = Table([
            [
                Paragraph("<b>2. Répartition des Dépenses Générales</b>", S['body']),
                Paragraph("<b>3. Encaissements par Mode de Règlement</b>", S['body']),
            ],
            [t_exp, t_meth]
        ], colWidths=[134*mm, 135*mm])
        side_by_side.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
        ]))
        elems.append(side_by_side)
        elems.append(Spacer(1, 10))

        # 4. Rémunérations & Paie des Enseignants
        elems.append(Paragraph("4. Synthèse des Rémunérations &amp; Règlements Enseignants", S['section']))
        tp_header = ['Enseignant', 'Période', 'Montant Réglé (DH)', 'Mode de Paiement', 'Type / Objet', 'Date']
        tp_rows = []
        if teachers_summary and teachers_summary.get('items'):
            for item in teachers_summary['items'][:15]:
                tp_rows.append([
                    item['teacher_name'],
                    item['period'],
                    f"{item['amount']:,.0f}",
                    item['payment_method'],
                    item['payment_type'],
                    item['payment_date'].strftime('%d/%m/%Y') if item['payment_date'] else '—',
                ])
            tp_tot = teachers_summary.get('total', Decimal('0'))
            tp_rows.append(['TOTAL RÈGLEMENTS ENSEIGNANTS', '', f"{tp_tot:,.0f} DH", '', '', f"{len(teachers_summary['items'])} versement(s)"])
        else:
            tp_rows = [['Aucun règlement enseignant enregistré pour ce mois', '', '0', '', '', '']]

        t_teach = Table([tp_header] + tp_rows, colWidths=[55*mm, 28*mm, 35*mm, 42*mm, 65*mm, 44*mm])
        ts_teach = ReportExporter._table_style(colors.HexColor('#b45309'), S['BG_ROW_ALT'])
        if teachers_summary and teachers_summary.get('items'):
            last_idx = len(tp_rows)
            ts_teach.add('FONTNAME', (0, last_idx), (-1, last_idx), 'Helvetica-Bold')
            ts_teach.add('BACKGROUND', (0, last_idx), (-1, last_idx), colors.HexColor('#fef3c7'))
        t_teach.setStyle(ts_teach)
        elems.append(t_teach)
        elems.append(Spacer(1, 10))

        # 5. Paiements Soldés par Dérogation & Exceptions
        if exceptions and exceptions.get('items'):
            elems.append(Paragraph(f"5. Dérogations &amp; Paiements Soldés par Exception ({exceptions['count']} cas — Total remises : {exceptions['total_discount']:,.0f} DH)", S['section']))
            exc_header = ['N° Reçu', 'Élève', 'Matricule', 'Montant Perçu (DH)', 'Attendu Normal (DH)', 'Remise Accordée (DH)', 'Date & Mode']
            exc_rows = []
            for it in exceptions['items'][:12]:
                exc_rows.append([
                    it['receipt_number'] or f"REC-{it['payment_id']}",
                    it['student_name'],
                    it['student_matricule'] or '—',
                    f"{it['amount_collected']:,.0f}",
                    f"{it['expected_fees']:,.0f}",
                    f"{it['discount_granted']:,.0f}",
                    f"{it['payment_date'].strftime('%d/%m/%Y') if it['payment_date'] else '—'} ({it['payment_method']})",
                ])
            exc_rows.append([
                'TOTAL REMISES CONSENTIES', '', '',
                f"{exceptions['total_collected']:,.0f}",
                f"{exceptions['total_expected']:,.0f}",
                f"{exceptions['total_discount']:,.0f} DH",
                f"{exceptions['count']} élève(s)",
            ])
            t_exc = Table([exc_header] + exc_rows, colWidths=[35*mm, 52*mm, 28*mm, 35*mm, 35*mm, 38*mm, 46*mm])
            ts_exc = ReportExporter._table_style(colors.HexColor('#c2410c'), S['BG_ROW_ALT'])
            last_e = len(exc_rows)
            ts_exc.add('FONTNAME', (0, last_e), (-1, last_e), 'Helvetica-Bold')
            ts_exc.add('BACKGROUND', (0, last_e), (-1, last_e), colors.HexColor('#ffedd5'))
            t_exc.setStyle(ts_exc)
            elems.append(t_exc)
            elems.append(Spacer(1, 10))

        # 6. Revenus par Groupe de Cours
        if by_group:
            elems.append(Paragraph(f"6. Performance &amp; Chiffre d'Affaires par Groupe — {today.strftime('%B %Y')}", S['section']))
            g_header = ['Groupe de Cours', 'Matière', 'Élèves', 'Attendu (DH)', 'Encaissé (DH)', 'Reste à Percevoir (DH)', 'Taux Recouvr.']
            g_rows = []
            for r in by_group[:15]:
                g_rows.append([
                    r['group_name'],
                    r['subject'],
                    str(r['enrolled_count']),
                    f"{r['expected']:,.0f}",
                    f"{r['collected']:,.0f}",
                    f"{r['outstanding']:,.0f}",
                    f"{r['collection_rate']}%",
                ])
            gt = Table([g_header] + g_rows, colWidths=[55*mm, 42*mm, 22*mm, 38*mm, 38*mm, 44*mm, 30*mm])
            gt.setStyle(ReportExporter._table_style(colors.HexColor('#0f3460'), S['BG_ROW_ALT']))
            elems.append(gt)

        doc.build(elems, canvasmaker=NumberedCanvas)
        buf.seek(0)
        return buf

    @staticmethod
    def teacher_payroll_pdf(start_date, end_date):
        """
        Teacher payroll summary PDF in landscape format with hours, remuneration,
        payments made, and outstanding balances.
        """
        import io
        from datetime import date
        from decimal import Decimal
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        )
        from core.utils import get_setting

        S = ReportExporter._base_styles()
        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=landscape(A4),
            topMargin=12*mm, bottomMargin=16*mm,
            leftMargin=14*mm, rightMargin=14*mm,
        )

        payroll = TeacherAnalytics.payroll_summary(start_date, end_date)
        load = TeacherAnalytics.weekly_load()
        subs = TeacherAnalytics.substitution_rate()

        school_name = get_setting('CENTER_NAME') or get_setting('SCHOOL_NAME', 'Établissement')
        elems = []

        header_table = Table([
            [
                Paragraph(f"<font size=9 color='#64748b'><b>{school_name.upper()}</b></font><br/><font size=16 color='#0f172a'><b>Bordereau Récapitulatif de Paie Enseignants</b></font>", S['title']),
                Paragraph(f"<font color='#64748b'>Période : <b>{start_date.strftime('%d/%m/%Y')} → {end_date.strftime('%d/%m/%Y')}</b><br/>Édité le : <b>{date.today().strftime('%d/%m/%Y')}</b><br/>Devise : <b>MAD (DH)</b></font>", S['body']),
            ]
        ], colWidths=[185*mm, 84*mm])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        elems.append(header_table)
        elems.append(Spacer(1, 3))
        elems.append(HRFlowable(width='100%', thickness=1.5, color=S['ACCENT']))
        elems.append(Spacer(1, 7))

        total_due = sum((r.get('salary_taught') or r.get('earnings') or Decimal('0')) for r in payroll)
        total_paid = sum((r.get('total_paid') or Decimal('0')) for r in payroll)
        total_balance = sum((r.get('balance') or Decimal('0')) for r in payroll)
        total_hours = sum((r.get('total_hours') or 0.0) for r in payroll)
        total_sessions = sum((r.get('total_sessions') or 0) for r in payroll)

        kpi_cells = [
            [
                Paragraph(f"<font size=7 color='#64748b'><b>ENSEIGNANTS ACTIFS</b></font><br/><font size=13 color='#0f172a'><b>{len(payroll)}</b></font><br/><font size=7 color='#64748b'>{total_sessions} séances ({total_hours:.1f}h)</font>", S['body']),
                Paragraph(f"<font size=7 color='#64748b'><b>MASSE SALARIALE DUE</b></font><br/><font size=13 color='#1e3a8a'><b>{total_due:,.0f} DH</b></font><br/><font size=7 color='#64748b'>Rémunération calculée</font>", S['body']),
                Paragraph(f"<font size=7 color='#64748b'><b>MONTANT DÉJÀ VERSÉ</b></font><br/><font size=13 color='#059669'><b>{total_paid:,.0f} DH</b></font><br/><font size=7 color='#64748b'>Règlements effectués</font>", S['body']),
                Paragraph(f"<font size=7 color='#64748b'><b>RESTE TOTAL À PAYER</b></font><br/><font size=13 color='{'#dc2626' if total_balance > 0 else '#059669'}'><b>{total_balance:,.0f} DH</b></font><br/><font size=7 color='#64748b'>Solde restant à solder</font>", S['body']),
            ]
        ]
        kpi_t = Table(kpi_cells, colWidths=[67.2*mm]*4)
        kpi_t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#cbd5e1')),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ]))
        elems.append(kpi_t)
        elems.append(Spacer(1, 10))

        elems.append(Paragraph("1. État Détaillé de la Paie par Enseignant", S['section']))
        METHOD_LABEL = {'HOURLY': 'Horaire', 'PERCENTAGE': 'Pourcentage', 'SESSION': 'Par séance'}
        p_header = ['Enseignant', 'Mode', 'Séances', 'Heures', 'Rémunération Due (DH)', 'Déjà Versé (DH)', 'Solde Restant (DH)', 'Statut']
        p_rows = []
        for r in payroll:
            bal = r.get('balance', Decimal('0'))
            paid = r.get('total_paid', Decimal('0'))
            due = r.get('salary_taught') or r.get('earnings') or Decimal('0')
            if bal <= 0 and due > 0:
                statut = '✓ Soldé'
            elif paid > 0:
                statut = '⚡ Partiel'
            elif due > 0:
                statut = '⏳ En attente'
            else:
                statut = '—'
            p_rows.append([
                r['teacher_name'],
                METHOD_LABEL.get(r['payment_method'], r['payment_method']),
                f"{r['total_sessions']} ({r['session_count']}+{r['substitute_count']}r)",
                f"{r.get('total_hours', 0):.1f}h",
                f"{due:,.0f}",
                f"{paid:,.0f}",
                f"{bal:,.0f}",
                statut,
            ])

        p_rows.append([
            'TOTAL GÉNÉRAL', '', f"{total_sessions}", f"{total_hours:.1f}h",
            f"{total_due:,.0f}", f"{total_paid:,.0f}", f"{total_balance:,.0f}",
            '—'
        ])

        pt = Table([p_header] + p_rows, colWidths=[52*mm, 26*mm, 28*mm, 22*mm, 38*mm, 36*mm, 36*mm, 31*mm])
        ts = ReportExporter._table_style(S['ACCENT'], S['BG_ROW_ALT'])
        last_p = len(p_rows)
        ts.add('FONTNAME', (0, last_p), (-1, last_p), 'Helvetica-Bold')
        ts.add('BACKGROUND', (0, last_p), (-1, last_p), colors.HexColor('#e2e8f0'))
        pt.setStyle(ts)
        elems.append(pt)
        elems.append(Spacer(1, 10))

        l_header = ['Enseignant', 'Heures/semaine', 'Séances', 'Statut']
        FLAG_LABEL = {'OVERLOADED': '⚠ Surchargé', 'UNDERUTILISED': '↓ Sous-utilisé', 'NORMAL': '✓ Normal'}
        l_rows = [[
            r['teacher_name'],
            f"{r['weekly_hours']}h",
            str(r['session_count']),
            FLAG_LABEL.get(r['load_flag'], r['load_flag']),
        ] for r in load]
        lt = Table([l_header] + l_rows, colWidths=[48*mm, 30*mm, 22*mm, 34*mm])
        lt.setStyle(ReportExporter._table_style(colors.HexColor('#166534'), S['BG_ROW_ALT']))

        sub_data = [s for s in subs if s['total_sessions'] > 0]
        su_header = ['Enseignant', 'Séances', 'Remplacé', 'Taux Remplacement']
        su_rows = [[
            r['teacher_name'],
            str(r['total_sessions']),
            str(r['substituted_sessions']),
            f"{r['substitution_rate']}%",
        ] for r in sub_data] if sub_data else [['Aucun remplacement enregistré', '—', '—', '0%']]
        sut = Table([su_header] + su_rows, colWidths=[48*mm, 24*mm, 24*mm, 38*mm])
        sut.setStyle(ReportExporter._table_style(colors.HexColor('#7e22ce'), S['BG_ROW_ALT']))

        split_table = Table([
            [Paragraph("<b>2. Charge Hebdomadaire Planifiée</b>", S['body']), Paragraph("<b>3. Taux de Remplacement</b>", S['body'])],
            [lt, sut]
        ], colWidths=[134*mm, 135*mm])
        split_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        elems.append(split_table)

        doc.build(elems, canvasmaker=NumberedCanvas)
        buf.seek(0)
        return buf

    @staticmethod
    def attendance_report_pdf(start_date, end_date):
        """Absence & attendance analytics PDF report."""
        import io
        from datetime import date
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        )
        from core.utils import get_setting

        S = ReportExporter._base_styles()
        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            topMargin=15*mm, bottomMargin=16*mm,
            leftMargin=15*mm, rightMargin=15*mm,
        )

        students = AttendanceAnalytics.student_absence_summary(start_date, end_date)
        weekly = AttendanceAnalytics.weekly_trend(weeks=8)
        groups = AttendanceAnalytics.group_attendance_matrix(start_date.replace(day=1))

        school_name = get_setting('CENTER_NAME') or get_setting('SCHOOL_NAME', 'Établissement')
        elems = []

        header_table = Table([
            [
                Paragraph(f"<font size=9 color='#64748b'><b>{school_name.upper()}</b></font><br/><font size=16 color='#0f172a'><b>Rapport de Présences &amp; Absences</b></font>", S['title']),
                Paragraph(f"<font color='#64748b'>Période : <b>{start_date.strftime('%d/%m/%Y')} → {end_date.strftime('%d/%m/%Y')}</b><br/>Édité le : <b>{date.today().strftime('%d/%m/%Y')}</b></font>", S['body']),
            ]
        ], colWidths=[115*mm, 65*mm])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        elems.append(header_table)
        elems.append(Spacer(1, 3))
        elems.append(HRFlowable(width='100%', thickness=1.5, color=S['ACCENT']))
        elems.append(Spacer(1, 8))

        total_students = len(students)
        at_risk = sum(1 for s in students if s['is_at_risk'])
        high_risk = sum(1 for s in students if s['risk_level'] == 'HIGH_RISK')
        kpi_data = [
            ['Élèves analysés', 'À risque (>20%)', 'Critique (>35%)', "Seuil d'alerte"],
            [str(total_students), str(at_risk), str(high_risk), '20%'],
        ]
        kt = Table(kpi_data, colWidths=[45*mm, 45*mm, 45*mm, 45*mm])
        kt.setStyle(ReportExporter._table_style(S['ACCENT'], S['BG_ROW_ALT']))
        elems.append(kt)
        elems.append(Spacer(1, 10))

        elems.append(Paragraph("1. Élèves à Risque d'Échec ou d'Abandon", S['section']))
        at_risk_students = [s for s in students if s['is_at_risk']]
        if at_risk_students:
            s_header = ['Élève', 'Séances', 'Absences', 'Taux', 'Risque', 'Abs. Conséc.']
            s_rows = [[
                s['student_name'],
                str(s['total_sessions']),
                str(s['absences']),
                f"{s['absence_rate']}%",
                {'HIGH_RISK': '🔴 Critique', 'AT_RISK': '🟠 À risque'}.get(s['risk_level'], ''),
                str(s['consecutive_absences']),
            ] for s in at_risk_students[:25]]
            st = Table([s_header] + s_rows, colWidths=[55*mm, 22*mm, 22*mm, 22*mm, 32*mm, 27*mm])
            st.setStyle(ReportExporter._table_style(colors.HexColor('#dc2626'), S['BG_ROW_ALT']))
            elems.append(st)
        else:
            elems.append(Paragraph("Aucun élève en situation d'alerte sur cette période. ✓", S['body']))
        elems.append(Spacer(1, 10))

        elems.append(Paragraph("2. Tendance Hebdomadaire des Absences", S['section']))
        w_header = ['Semaine', 'Total Séances', 'Absences', "Taux d'Absence"]
        w_rows = [[
            r['week_label'],
            str(r['total']),
            str(r['absences']),
            f"{r['absence_rate']}%",
        ] for r in weekly]
        wt = Table([w_header] + w_rows, colWidths=[60*mm, 40*mm, 40*mm, 40*mm])
        wt.setStyle(ReportExporter._table_style(colors.HexColor('#2563eb'), S['BG_ROW_ALT']))
        elems.append(wt)
        elems.append(Spacer(1, 10))

        elems.append(Paragraph("3. Assiduité par Groupe de Cours", S['section']))
        g_header = ['Groupe', 'Matière', 'Séances', 'Absences', "Taux d'Absence"]
        g_rows = [[
            r['group_name'],
            r['subject_name'],
            str(r['total']),
            str(r['absences']),
            f"{r['absence_rate']}%",
        ] for r in weekly]
        wt = Table([w_header] + w_rows, colWidths=[60*mm, 40*mm, 40*mm, 40*mm])
        wt.setStyle(ReportExporter._table_style(colors.HexColor('#2563eb'), S['BG_ROW_ALT']))
        elems.append(wt)
        elems.append(Spacer(1, 10))

        elems.append(Paragraph("3. Assiduité par Groupe de Cours", S['section']))
        g_header = ['Groupe', 'Matière', 'Séances', 'Absences', "Taux d'Absence"]
        g_rows = [[
            r['group_name'],
            r['subject'],
            str(r['total_records']),
            str(r['absences']),
            f"{r['absence_rate']}%",
        ] for r in groups if r['total_records'] > 0][:15]
        if g_rows:
            gt = Table([g_header] + g_rows, colWidths=[55*mm, 40*mm, 25*mm, 25*mm, 35*mm])
            gt.setStyle(ReportExporter._table_style(colors.HexColor('#7c3aed'), S['BG_ROW_ALT']))
            elems.append(gt)

        doc.build(elems, canvasmaker=NumberedCanvas)
        buf.seek(0)
        return buf

    @staticmethod
    def churn_report_pdf():
        """At-risk / churn signals PDF report."""
        import io
        from datetime import date
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        )
        from core.utils import get_setting

        S = ReportExporter._base_styles()
        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            topMargin=15*mm, bottomMargin=16*mm,
            leftMargin=15*mm, rightMargin=15*mm,
        )

        churn = StudentAnalytics.churn_signals()
        ltv = StudentAnalytics.lifetime_value()
        multi = StudentAnalytics.multi_group_students()

        school_name = get_setting('CENTER_NAME') or get_setting('SCHOOL_NAME', 'Établissement')
        elems = []

        header_table = Table([
            [
                Paragraph(f"<font size=9 color='#64748b'><b>{school_name.upper()}</b></font><br/><font size=16 color='#0f172a'><b>Rapport Rétention Élèves &amp; Signaux d'Alerte</b></font>", S['title']),
                Paragraph(f"<font color='#64748b'>Édité le : <b>{date.today().strftime('%d/%m/%Y')}</b><br/>Module : <b>Fidélisation &amp; Rétention</b></font>", S['body']),
            ]
        ], colWidths=[115*mm, 65*mm])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        elems.append(header_table)
        elems.append(Spacer(1, 3))
        elems.append(HRFlowable(width='100%', thickness=1.5, color=S['LIGHT_ACCENT']))
        elems.append(Spacer(1, 8))

        elems.append(Paragraph(f"1. Signaux de Départ Détectés ({len(churn)} élèves)", S['section']))
        if churn:
            c_header = ['Élève', 'Groupes Inscrits', "Signaux d'Alerte"]
            c_rows = [[
                r['student_name'],
                ', '.join(r['groups'][:2]) + ('…' if len(r['groups']) > 2 else ''),
                ' | '.join(r['signals']),
            ] for r in churn[:25]]
            ct = Table([c_header] + c_rows, colWidths=[45*mm, 45*mm, 90*mm])
            ct.setStyle(ReportExporter._table_style(S['LIGHT_ACCENT'], S['BG_ROW_ALT']))
            elems.append(ct)
        else:
            elems.append(Paragraph("Aucun signal de désengagement critique détecté. ✓", S['body']))
        elems.append(Spacer(1, 10))

        elems.append(Paragraph("2. Top 20 Valeur Vie Client (LTV)", S['section']))
        l_header = ['Élève', 'Total Payé (DH)', 'Mois Actifs', 'Moy./Mois', 'Dernier Paiement']
        l_rows = [[
            r['student_name'],
            f"{r['total_paid']:,.0f}",
            str(r['months_active']),
            f"{r['avg_per_month']:,.0f}",
            r['last_payment'].strftime('%d/%m/%Y') if r['last_payment'] else '—',
        ] for r in ltv[:20]]
        lt = Table([l_header] + l_rows, colWidths=[55*mm, 35*mm, 25*mm, 30*mm, 35*mm])
        lt.setStyle(ReportExporter._table_style(colors.HexColor('#059669'), S['BG_ROW_ALT']))
        elems.append(lt)
        elems.append(Spacer(1, 10))

        elems.append(Paragraph("3. Élèves Multi-Groupes (Fidélisés)", S['section']))
        m_header = ['Élève', 'Nombre de Groupes Inscrits']
        m_rows = [[r['student_name'], str(r['group_count'])] for r in multi[:20]]
        if m_rows:
            mt = Table([m_header] + m_rows, colWidths=[110*mm, 70*mm])
            mt.setStyle(ReportExporter._table_style(S['ACCENT'], S['BG_ROW_ALT']))
            elems.append(mt)

        doc.build(elems, canvasmaker=NumberedCanvas)
        buf.seek(0)
        return buf

    @staticmethod
    def export_csv(data: list[dict], filename_hint: str = 'export'):
        """
        Generic CSV export with UTF-8 BOM encoding for seamless Microsoft Excel compatibility.
        Returns a BytesIO object ready for HTTP transmission.
        """
        import io, csv, codecs
        from decimal import Decimal
        from datetime import date

        buf = io.BytesIO()
        buf.write(codecs.BOM_UTF8)

        if not data:
            buf.write("Aucune donnée disponible\n".encode('utf-8'))
            buf.seek(0)
            return buf

        text_wrapper = io.TextIOWrapper(buf, encoding='utf-8', newline='')
        writer = csv.DictWriter(text_wrapper, fieldnames=list(data[0].keys()))
        writer.writeheader()

        for row in data:
            clean = {}
            for k, v in row.items():
                if isinstance(v, Decimal):
                    clean[k] = f"{float(v):.2f}"
                elif isinstance(v, date):
                    clean[k] = v.strftime('%Y-%m-%d')
                elif isinstance(v, list):
                    clean[k] = '; '.join(str(x) for x in v)
                elif v is None:
                    clean[k] = ''
                else:
                    clean[k] = v
            writer.writerow(clean)

        text_wrapper.flush()
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