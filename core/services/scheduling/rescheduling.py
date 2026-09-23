from datetime import date, time, timedelta, datetime
from typing import List, Dict, Any, Optional
from django.conf import settings
from django.db import transaction

from core.models import Room, Teacher, CourseGroup, Session, TeacherLeave, TeacherAvailability, Holiday, Enrollment, MakeupSession
from .domain import RescheduleSuggestion
from .locking import LockingService
from .conflicts import ConflictService
from .audit import AuditService

class ReschedulingAssistantService:
    @staticmethod
    def get_session_duration(session: Session) -> timedelta:
        """
        Calculates session duration as a timedelta.
        """
        # Convert times to datetimes to calculate difference
        today = date.today()
        dt_start = datetime.combine(today, session.start_time)
        dt_end = datetime.combine(today, session.end_time)
        if dt_end <= dt_start:
            dt_end += timedelta(days=1)
        return dt_end - dt_start

    @classmethod
    def get_reschedule_suggestions(
        cls,
        session: Session
    ) -> List[RescheduleSuggestion]:
        """
        Finds the best rescheduled slots for a session over a search horizon.
        Uses in-memory checks optimized to avoid N+1 queries.
        """
        group = session.group
        teacher = group.teacher if group else None
        if not group or not teacher:
            return []

        # Get search horizon from settings
        horizon_days = getattr(settings, 'RESCHEDULING_SEARCH_HORIZON', 21)
        start_search = date.today() + timedelta(days=1)
        end_search = date.today() + timedelta(days=horizon_days)

        # 1. Fetch Room, Teacher, Student data
        rooms = list(Room.objects.filter(is_active=True))
        
        # All sessions in range (excluding CANCELLED)
        sessions_in_range = list(Session.objects.filter(
            date__range=[start_search, end_search]
        ).exclude(status='CANCELLED').select_related('room', 'group'))

        # Teacher leaves in range
        leaves = list(TeacherLeave.objects.filter(
            teacher=teacher,
            start_date__lte=end_search,
            end_date__gte=start_search
        ))

        # Teacher availability rules
        availabilities = list(TeacherAvailability.objects.filter(teacher=teacher))
        avail_map = defaultdict(list)
        for av in availabilities:
            avail_map[av.day].append(av)

        # Holidays in range
        holidays = list(Holiday.objects.filter(
            date__range=[start_search, end_search]
        ).prefetch_related('affected_groups'))

        # Students enrolled in group
        enrolled_student_ids = list(Enrollment.objects.filter(
            course_group=group,
            is_active=True,
            student__is_active=True
        ).values_list('student_id', flat=True))

        # Fetch other sessions of enrolled students in the range
        student_sessions = list(Session.objects.filter(
            date__range=[start_search, end_search],
            group__enrollment__student_id__in=enrolled_student_ids,
            group__enrollment__is_active=True
        ).exclude(status='CANCELLED').exclude(group=group).values('id', 'date', 'start_time', 'end_time', 'group__enrollment__student_id'))

        # Map student sessions by date for fast lookup
        student_sessions_by_date = defaultdict(list)
        for ss in student_sessions:
            student_sessions_by_date[ss['date']].append(ss)

        # Calculate target duration
        duration = cls.get_session_duration(session)

        # Generate candidates times: e.g. 08:30 to 20:00 hourly/half-hourly
        # In school support centers, common slots are e.g. 2 hours or 1.5 hours
        # We try candidate start times at 30-min intervals
        candidate_start_times = []
        curr_h = 8
        curr_m = 30
        while curr_h < 20 or (curr_h == 20 and curr_m == 0):
            candidate_start_times.append(time(curr_h, curr_m))
            curr_m += 30
            if curr_m >= 60:
                curr_h += 1
                curr_m = 0

        suggestions: List[RescheduleSuggestion] = []
        day_map = {0: 'MON', 1: 'TUE', 2: 'WED', 3: 'THU', 4: 'FRI', 5: 'SAT', 6: 'SUN'}

        # Main search loop
        curr_date = start_search
        while curr_date <= end_search:
            # Check locking for this day
            if LockingService.is_locked(curr_date):
                curr_date += timedelta(days=1)
                continue

            # Check holiday
            is_holiday = False
            for h in holidays:
                if h.date == curr_date:
                    if h.affects_all or h.affected_groups.filter(id=group.id).exists():
                        is_holiday = True
                        break
            if is_holiday:
                curr_date += timedelta(days=1)
                continue

            # Check teacher leave
            on_leave = False
            for lv in leaves:
                if lv.start_date <= curr_date <= lv.end_date:
                    on_leave = True
                    break
            if on_leave:
                curr_date += timedelta(days=1)
                continue

            day_code = day_map[curr_date.weekday()]
            teacher_day_avails = avail_map[day_code]

            # Try each time slot
            for start_t in candidate_start_times:
                # Calculate end time
                dt_temp = datetime.combine(curr_date, start_t) + duration
                end_t = dt_temp.time()

                # If end time rolls over past 22:00, skip
                if end_t > time(22, 0) or dt_temp.date() > curr_date:
                    continue

                # Check if teacher has an overlapping session
                teacher_overlap = False
                for s in sessions_in_range:
                    if s.date == curr_date:
                        s_teacher = s.substitute_teacher or (s.group.teacher if s.group else None)
                        if s_teacher and s_teacher.id == teacher.id:
                            if ConflictService.time_overlaps(start_t, end_t, s.start_time, s.end_time):
                                teacher_overlap = True
                                break
                if teacher_overlap:
                    continue

                # Evaluate teacher availability score penalty
                avail_penalty = 0
                avail_reason = "Enseignant disponible"

                unavail_slots = [a for a in teacher_day_avails if not a.is_available]
                overlaps_unavail = False
                for ua in unavail_slots:
                    if ConflictService.time_overlaps(start_t, end_t, ua.start_time, ua.end_time):
                        overlaps_unavail = True
                        break
                if overlaps_unavail:
                    continue

                avail_slots = [a for a in teacher_day_avails if a.is_available]
                if avail_slots:
                    fully_covered = any(
                        start_t >= entry.start_time and end_t <= entry.end_time
                        for entry in avail_slots
                    )
                    if not fully_covered:
                        avail_penalty = 50
                        avail_reason = "En dehors des disponibilités de l'enseignant"

                # Check student conflicts on this date/time
                student_conflict_count = 0
                for ss in student_sessions_by_date[curr_date]:
                    if ConflictService.time_overlaps(start_t, end_t, ss['start_time'], ss['end_time']):
                        student_conflict_count += 1

                # Try each room
                for r in rooms:
                    # Check room overlap
                    room_overlap = False
                    for s in sessions_in_range:
                        if s.date == curr_date and s.room_id == r.id:
                            if ConflictService.time_overlaps(start_t, end_t, s.start_time, s.end_time):
                                room_overlap = True
                                break
                    if room_overlap:
                        continue

                    # Calculate conflict score
                    # Base score starts with student conflicts + teacher availability penalty
                    score = (student_conflict_count * 10) + avail_penalty

                    # Preferences
                    reasons = []
                    if student_conflict_count == 0:
                        reasons.append("0 conflits d'élèves")
                    else:
                        reasons.append(f"{student_conflict_count} élève(s) avec conflit")

                    if avail_penalty > 0:
                        reasons.append("hors disponibilité enseignant")
                    
                    # Preference: same day of week
                    weekday_matches = False
                    for sch in group.schedules.all():
                        if sch.day == day_code:
                            weekday_matches = True
                            if sch.start_time == start_t:
                                score -= 5
                                reasons.append("même horaire habituel")
                    
                    if weekday_matches:
                        score -= 5
                        reasons.append("même jour de la semaine")

                    reason_str = ", ".join(reasons)

                    suggestions.append(RescheduleSuggestion(
                        date=curr_date,
                        start_time=start_t,
                        end_time=end_t,
                        room_id=r.id,
                        room_name=r.name,
                        teacher_id=teacher.id,
                        teacher_name=teacher.name,
                        conflict_score=score,
                        reason=reason_str
                    ))

            curr_date += timedelta(days=1)

        # Sort suggestions: lower conflict score is better, then by date, then start_time
        suggestions.sort(key=lambda s: (s.conflict_score, s.date, s.start_time))
        
        # Return top 10 suggestions
        return suggestions[:10]

    @classmethod
    @transaction.atomic
    def apply_reschedule_suggestion(
        cls,
        session: Session,
        suggestion: RescheduleSuggestion,
        user: Optional[Any] = None,
        ip_address: Optional[str] = None,
        change_reason: Optional[str] = None
    ) -> Session:
        """
        Creates a makeup session for the suggestion and cancels the original session.
        Atomically executes write operations and links via MakeupSession.
        """
        # Validate locks
        LockingService.check_lock(session.date)
        LockingService.check_lock(suggestion.date)

        # 1. Update the original session to CANCELLED
        old_status = session.status
        session.status = 'CANCELLED'
        session.is_manually_edited = True
        session.save()

        # Log change for original session
        AuditService.log_change(
            session=session,
            user=user,
            action='update',
            previous_values={'status': old_status},
            new_values={'status': 'CANCELLED'},
            change_reason=change_reason or "Annulée pour rattrapage",
            ip_address=ip_address
        )

        # 2. Create the new makeup session
        room = Room.objects.get(id=suggestion.room_id)
        makeup_sess = Session.objects.create(
            group=session.group,
            date=suggestion.date,
            start_time=suggestion.start_time,
            end_time=suggestion.end_time,
            room=room,
            status='PLANNED',
            is_manually_edited=True,
            notes=f"Séance de rattrapage pour la séance annulée du {session.date.strftime('%d/%m/%Y')}"
        )

        # Log change for new session
        AuditService.log_change(
            session=makeup_sess,
            user=user,
            action='create',
            previous_values={},
            new_values={
                'date': str(makeup_sess.date),
                'start_time': str(makeup_sess.start_time),
                'end_time': str(makeup_sess.end_time),
                'room': makeup_sess.room.name,
                'status': makeup_sess.status
            },
            change_reason="Création automatique de rattrapage",
            ip_address=ip_address
        )

        # 3. Create the MakeupSession linkage
        makeup_link = MakeupSession.objects.create(
            original_session=session,
            makeup_session=makeup_sess,
            notes=change_reason or "Rattrapage programmé"
        )
        
        # Link active group students to the makeup session resource
        students = list(session.group.students.filter(is_active=True))
        makeup_link.students.set(students)

        # Trigger notifications
        from .notifications import NotificationService
        NotificationService.send_makeup_session_created(makeup_sess)

        return makeup_sess
