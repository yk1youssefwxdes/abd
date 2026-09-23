from datetime import date, timedelta
from typing import Dict, List, Any, Optional
from collections import defaultdict
from django.db.models import Q
from django.utils import timezone

from core.models import CourseGroup, Session, CourseGroupSchedule, Holiday, TeacherLeave, AcademicCalendarPeriod, RecurringException, Attendance
from .domain import ScheduleDiff, Conflict, ConflictType, ConflictSeverity
from .conflicts import ConflictService
from .locking import LockingService

class SchedulePreviewService:
    @staticmethod
    def preview_bulk_generation(
        start_date: date,
        end_date: date,
        force: bool = False,
        course: Optional[CourseGroup] = None
    ) -> ScheduleDiff:
        """
        Calculates a read-only preview of session regeneration for a date range.
        Does not write to the database.
        """
        diff = ScheduleDiff()
        
        # 1. Load Holidays & Academic Calendar Periods
        holidays_qs = Holiday.objects.filter(
            date__range=[start_date, end_date]
        ).prefetch_related('affected_groups')

        global_holiday_dates = set()
        group_holiday_dates = defaultdict(set)
        holiday_map = {}
        for h in holidays_qs:
            if h.affects_all:
                global_holiday_dates.add(h.date)
                holiday_map[h.date] = h
            else:
                for grp in h.affected_groups.all():
                    group_holiday_dates[h.date].add(grp.id)
                    holiday_map[(h.date, grp.id)] = h

        # Load academic periods and recurring exceptions
        acad_periods = list(AcademicCalendarPeriod.objects.filter(
            start_date__lte=end_date,
            end_date__gte=start_date,
            is_active=True
        ).prefetch_related('affected_groups'))
        
        rec_exceptions = list(RecurringException.objects.filter(is_available=False))

        # 2. Get active and inactive courses
        if course:
            courses_to_clean = [course] if not course.is_active else []
            courses = [course] if course.is_active else []
        else:
            courses_to_clean = list(CourseGroup.objects.filter(is_active=False))
            courses = list(CourseGroup.objects.filter(is_active=True).prefetch_related('schedules', 'teacher'))

        # Track sessions that would be deleted (orphaned)
        sessions_to_remove = []
        
        # Cleanup inactive groups
        for c in courses_to_clean:
            to_delete = Session.objects.filter(
                group=c,
                date__range=[start_date, end_date],
                status='PLANNED',
                is_manually_edited=False
            ).select_related('group', 'room')
            for s in to_delete:
                sessions_to_remove.append(s)
                diff.removed_sessions.append({
                    'id': s.id,
                    'group_name': c.name,
                    'date': s.date,
                    'start_time': s.start_time,
                    'end_time': s.end_time,
                    'room_name': s.room.name
                })

        DAY_MAP = {'MON': 0, 'TUE': 1, 'WED': 2, 'THU': 3, 'FRI': 4, 'SAT': 5, 'SUN': 6}

        # Track sessions that would exist in range
        existing_sessions_in_range = list(Session.objects.filter(
            date__range=[start_date, end_date]
        ).select_related('group', 'group__teacher', 'substitute_teacher', 'room'))

        # Find orphaned sessions for active groups
        for active_course in courses:
            schedules = active_course.schedules.all()
            active_sessions = [s for s in existing_sessions_in_range if s.group_id == active_course.id and s.status == 'PLANNED' and not s.is_manually_edited]
            
            for s in active_sessions:
                matching_schedule = None
                for sch in schedules:
                    if s.schedule_id == sch.id:
                        matching_schedule = sch
                        break
                    if s.date.weekday() == DAY_MAP.get(sch.day) and s.start_time == sch.start_time and s.end_time == sch.end_time:
                        matching_schedule = sch
                        break
                
                if not matching_schedule:
                    sessions_to_remove.append(s)
                    diff.removed_sessions.append({
                        'id': s.id,
                        'group_name': active_course.name,
                        'date': s.date,
                        'start_time': s.start_time,
                        'end_time': s.end_time,
                        'room_name': s.room.name if s.room else ''
                    })

        # List of sessions that will be generated (created or updated in memory)
        simulated_sessions: List[Session] = []
        removed_ids = {s.id for s in sessions_to_remove if s.id}

        # Generate / update loop
        for active_course in courses:
            schedules = active_course.schedules.all()
            for sch in schedules:
                target_weekday = DAY_MAP.get(sch.day)
                if target_weekday is None:
                    continue

                days_ahead = (target_weekday - start_date.weekday()) % 7
                current = start_date + timedelta(days=days_ahead)

                while current <= end_date:
                    # Check schedule locking
                    if LockingService.is_locked(current):
                        diff.locked_sessions_skipped_count += 1
                        current += timedelta(days=7)
                        continue

                    # Holiday suppression check
                    is_holiday = False
                    h_obj = None
                    if current in global_holiday_dates:
                        is_holiday = True
                        h_obj = holiday_map.get(current)
                    elif active_course.id in group_holiday_dates.get(current, set()):
                        is_holiday = True
                        h_obj = holiday_map.get((current, active_course.id))

                    if is_holiday and h_obj:
                        diff.holiday_skips.append({
                            'date': current,
                            'group_name': active_course.name,
                            'holiday_name': h_obj.name
                        })
                        current += timedelta(days=7)
                        continue

                    # Academic Calendar periods check
                    is_calendar_blocked = False
                    for period in acad_periods:
                        if period.start_date <= current <= period.end_date:
                            if period.affects_all or active_course.id in period.affected_groups.values_list('id', flat=True):
                                is_calendar_blocked = True
                                break
                    if is_calendar_blocked:
                        diff.holiday_skips.append({
                            'date': current,
                            'group_name': active_course.name,
                            'holiday_name': "Période Académique Bloquée"
                        })
                        current += timedelta(days=7)
                        continue

                    # Check Teacher & Room Recurring Exceptions (unavailability)
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

                    eff_room = sch.room
                    eff_start = sch.start_time
                    eff_end = sch.end_time

                    # Look for existing
                    existing = None
                    for s in existing_sessions_in_range:
                        if s.group_id == active_course.id and s.date == current and (s.schedule_id == sch.id or (s.start_time == sch.start_time and s.end_time == sch.end_time)):
                            existing = s
                            break

                    if existing:
                        if existing.is_manually_edited or existing.status in ('DONE', 'CANCELLED'):
                            diff.manual_exceptions.append({
                                'id': existing.id,
                                'group_name': active_course.name,
                                'date': existing.date,
                                'start_time': existing.start_time,
                                'end_time': existing.end_time,
                                'status': existing.get_status_display()
                            })
                            simulated_sessions.append(existing)
                        else:
                            needs_update = (
                                existing.start_time != eff_start or
                                existing.end_time != eff_end or
                                existing.room_id != eff_room.id
                            )
                            if needs_update and force:
                                updated_s = Session(
                                    id=existing.id,
                                    group=active_course,
                                    schedule=sch,
                                    date=current,
                                    start_time=eff_start,
                                    end_time=eff_end,
                                    room=eff_room,
                                    status=existing.status,
                                    is_manually_edited=existing.is_manually_edited,
                                    substitute_teacher=existing.substitute_teacher
                                )
                                simulated_sessions.append(updated_s)
                                diff.updated_sessions.append({
                                    'id': existing.id,
                                    'group_name': active_course.name,
                                    'date': current,
                                    'old_room': existing.room.name if existing.room else '',
                                    'new_room': eff_room.name,
                                    'old_start': existing.start_time.strftime('%H:%M'),
                                    'new_start': eff_start.strftime('%H:%M'),
                                    'old_end': existing.end_time.strftime('%H:%M'),
                                    'new_end': eff_end.strftime('%H:%M'),
                                })
                            else:
                                simulated_sessions.append(existing)
                    else:
                        new_s = Session(
                            group=active_course,
                            schedule=sch,
                            date=current,
                            start_time=eff_start,
                            end_time=eff_end,
                            room=eff_room,
                            status='PLANNED',
                            is_manually_edited=False
                        )
                        simulated_sessions.append(new_s)
                        diff.created_sessions.append({
                            'group_name': active_course.name,
                            'date': current,
                            'start_time': eff_start,
                            'end_time': eff_end,
                            'room_name': eff_room.name
                        })

                    current += timedelta(days=7)

        # 3. Add existing sessions that are outside the generation scope
        other_sessions = [s for s in existing_sessions_in_range if s.id not in removed_ids and not any(sim.id == s.id for sim in simulated_sessions)]
        proposed_sessions = simulated_sessions + other_sessions

        # 4. Check conflicts on existing and proposed sessions sets
        existing_conflicts = ConflictService.check_conflicts_for_sessions(existing_sessions_in_range)
        proposed_conflicts = ConflictService.check_conflicts_for_sessions(proposed_sessions)
        
        diff.conflicts = [c for c in proposed_conflicts if c.severity in (ConflictSeverity.BLOCKING, ConflictSeverity.WARNING)]
        diff.teacher_leave_conflicts = [c for c in proposed_conflicts if c.type == ConflictType.TEACHER_LEAVE]

        # Calculate introduced & resolved conflicts
        def conflict_key(c: Conflict):
            return (c.type, c.session1_id, c.session2_id, c.date, c.start_time, c.end_time, c.student_id, c.entity_id)

        existing_keys = {conflict_key(c) for c in existing_conflicts}
        proposed_keys = {conflict_key(c) for c in proposed_conflicts}

        diff.conflicts_resolved = [c for c in existing_conflicts if conflict_key(c) not in proposed_keys]
        diff.conflicts_introduced = [c for c in proposed_conflicts if conflict_key(c) not in existing_keys]

        # 5. Count affected attendance records
        if removed_ids:
            diff.attendance_affected_count = Attendance.objects.filter(session_id__in=removed_ids).count()
        else:
            diff.attendance_affected_count = 0

        return diff
