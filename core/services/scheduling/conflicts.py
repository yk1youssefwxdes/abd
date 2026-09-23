from datetime import date, time, timedelta, datetime
from typing import List, Dict, Any, Optional
from collections import defaultdict
from django.utils import timezone
from django.db.models import Q, Count
from django.conf import settings

from core.models import (
    Room, Teacher, CourseGroup, Session, CourseGroupSchedule,
    TeacherLeave, TeacherAvailability, Enrollment, Holiday, MakeupSession
)
from .domain import Conflict, ConflictType, ConflictSeverity

class ConflictService:
    @staticmethod
    def time_overlaps(start_a: time, end_a: time, start_b: time, end_b: time) -> bool:
        return start_a < end_b and end_a > start_b

    @staticmethod
    def get_effective_teacher(session: Session) -> Optional[Teacher]:
        if session.substitute_teacher:
            return session.substitute_teacher
        if session.group:
            return session.group.teacher
        return None

    @classmethod
    def check_conflicts_for_sessions(cls, sessions: List[Session]) -> List[Conflict]:
        """
        In-memory conflict detection for a list of sessions.
        Optimized to handle unsaved or proposed sessions.
        """
        conflicts = []
        day_map = {0: 'MON', 1: 'TUE', 2: 'WED', 3: 'THU', 4: 'FRI', 5: 'SAT', 6: 'SUN'}
        
        # Pre-fetch maps needed for checking (avoiding N+1 queries)
        teacher_ids = set()
        group_ids = set()
        room_ids = set()
        session_dates = set()
        
        for s in sessions:
            teacher = cls.get_effective_teacher(s)
            if teacher:
                teacher_ids.add(teacher.id)
            if s.group_id:
                group_ids.add(s.group_id)
            if s.room_id:
                room_ids.add(s.room_id)
            session_dates.add(s.date)

        # 1. Fetch Teacher Availabilities
        availabilities = TeacherAvailability.objects.filter(teacher_id__in=teacher_ids)
        avail_map = defaultdict(list)
        for av in availabilities:
            avail_map[(av.teacher_id, av.day)].append(av)

        # 2. Fetch Teacher Leaves
        leaves = TeacherLeave.objects.filter(
            teacher_id__in=teacher_ids,
            end_date__gte=min(session_dates) if session_dates else date.min,
            start_date__lte=max(session_dates) if session_dates else date.max
        )
        leave_map = defaultdict(list)
        for lv in leaves:
            leave_map[lv.teacher_id].append(lv)

        # 3. Fetch Holidays, Academic Calendar periods, and Recurring Exceptions
        holidays = Holiday.objects.filter(
            date__in=session_dates
        ).prefetch_related('affected_groups')
        holiday_map = {}
        for h in holidays:
            holiday_map[h.date] = h

        from core.models import AcademicCalendarPeriod, RecurringException
        acad_periods = list(AcademicCalendarPeriod.objects.filter(
            start_date__lte=max(session_dates) if session_dates else date.max,
            end_date__gte=min(session_dates) if session_dates else date.min,
            is_active=True
        ).prefetch_related('affected_groups'))

        rec_exceptions = list(RecurringException.objects.filter(
            Q(teacher_id__in=teacher_ids, target_type='TEACHER') |
            Q(room_id__in=room_ids, target_type='ROOM')
        ))

        # 4. Fetch Enrollments & Student Counts
        enrollments = Enrollment.objects.filter(
            course_group_id__in=group_ids,
            is_active=True,
            student__is_active=True
        ).select_related('student')
        
        student_counts_map = defaultdict(int)
        group_students = defaultdict(list)
        for enr in enrollments:
            student_counts_map[enr.course_group_id] += 1
            group_students[enr.course_group_id].append(enr.student)

        # 5. Fetch Makeup Sessions (to determine if a session is a makeup and load its specific students)
        session_ids = [s.id for s in sessions if s.id]
        makeups_qs = MakeupSession.objects.filter(
            Q(makeup_session_id__in=session_ids) | Q(makeup_session__in=sessions)
        ).prefetch_related('students')
        makeup_session_ids = {m.makeup_session_id for m in makeups_qs}
        
        makeup_students_map = {}
        for m in makeups_qs:
            makeup_students_map[m.makeup_session_id] = list(m.students.filter(is_active=True))
            
        session_students_resolved = {}
        for s in sessions:
            if s.id in makeup_students_map:
                session_students_resolved[s.id or id(s)] = makeup_students_map[s.id]
            else:
                session_students_resolved[s.id or id(s)] = group_students[s.group_id] if s.group_id else []

        # Find double bookings among the sessions list itself
        for i, s1 in enumerate(sessions):
            # Check Holiday adjustments
            h = holiday_map.get(s1.date)
            if h:
                if h.affects_all or (s1.group_id and h.affected_groups.filter(id=s1.group_id).exists()):
                    conflicts.append(Conflict(
                        type=ConflictType.HOLIDAY_ADJUSTMENT,
                        severity=ConflictSeverity.INFO,
                        description=f"La séance du {s1.date.strftime('%d/%m/%Y')} tombe pendant le congé/jour férié : '{h.name}'.",
                        session1_id=s1.id,
                        date=s1.date
                    ))

            # Check Academic Calendar periods (Vacation, Exam, Closure)
            for period in acad_periods:
                if period.start_date <= s1.date <= period.end_date:
                    if period.affects_all or (s1.group_id and period.affected_groups.filter(id=s1.group_id).exists()):
                        conflicts.append(Conflict(
                            type=ConflictType.HOLIDAY_ADJUSTMENT,
                            severity=ConflictSeverity.INFO,
                            description=f"La séance du {s1.date.strftime('%d/%m/%Y')} tombe pendant la période académique '{period.name}' ({period.get_period_type_display()}).",
                            session1_id=s1.id,
                            date=s1.date
                        ))

            # Check Teacher Leaves & Recurring Exceptions
            t1 = cls.get_effective_teacher(s1)
            if t1:
                for lv in leave_map.get(t1.id, []):
                    if lv.start_date <= s1.date <= lv.end_date:
                        conflicts.append(Conflict(
                            type=ConflictType.TEACHER_LEAVE,
                            severity=ConflictSeverity.WARNING,
                            description=f"Le professeur '{t1.name}' est en congé le {s1.date.strftime('%d/%m/%Y')} (Motif: {lv.get_leave_type_display()}).",
                            entity_id=t1.id,
                            entity_name=t1.name,
                            session1_id=s1.id,
                            date=s1.date
                        ))

                # Check Recurring Exceptions (Teacher)
                for exc in rec_exceptions:
                    if exc.target_type == 'TEACHER' and exc.teacher_id == t1.id:
                        if exc.matches_date_and_time(s1.date, s1.start_time, s1.end_time) and not exc.is_available:
                            conflicts.append(Conflict(
                                type=ConflictType.TEACHER_UNAVAILABLE,
                                severity=ConflictSeverity.WARNING,
                                description=f"Le professeur '{t1.name}' a une indisponibilité récurrente le {s1.date.strftime('%d/%m/%Y')} de {exc.start_time.strftime('%H:%M')} à {exc.end_time.strftime('%H:%M')}.",
                                entity_id=t1.id,
                                entity_name=t1.name,
                                session1_id=s1.id,
                                date=s1.date
                            ))

                # Check Teacher Availabilities
                day_code = day_map[s1.date.weekday()]
                teacher_avails = avail_map.get((t1.id, day_code), [])
                
                # Check explicit unavailable slots
                unavail = [a for a in teacher_avails if not a.is_available]
                for entry in unavail:
                    if cls.time_overlaps(s1.start_time, s1.end_time, entry.start_time, entry.end_time):
                        conflicts.append(Conflict(
                            type=ConflictType.TEACHER_UNAVAILABLE,
                            severity=ConflictSeverity.WARNING,
                            description=f"Le professeur '{t1.name}' est marqué indisponible le {s1.date.strftime('%d/%m/%Y')} de {entry.start_time.strftime('%H:%M')} à {entry.end_time.strftime('%H:%M')}.",
                            entity_id=t1.id,
                            entity_name=t1.name,
                            session1_id=s1.id,
                            date=s1.date
                        ))

                # Check if outside available bounds
                avail_slots = [a for a in teacher_avails if a.is_available]
                if avail_slots and not any(
                    s1.start_time >= entry.start_time and s1.end_time <= entry.end_time
                    for entry in avail_slots
                ):
                    conflicts.append(Conflict(
                        type=ConflictType.TEACHER_OUT_OF_BOUNDS,
                        severity=ConflictSeverity.WARNING,
                        description=f"La séance du {s1.date.strftime('%d/%m/%Y')} pour '{s1.group.name if s1.group else ''}' est en dehors des heures de disponibilité de '{t1.name}'.",
                        entity_id=t1.id,
                        entity_name=t1.name,
                        session1_id=s1.id,
                        date=s1.date
                    ))

            # Capacity & Room warnings
            if s1.room:
                enrolled = student_counts_map[s1.group_id]
                cap = s1.room.capacity
                
                # Capacity warning threshold can be configured
                warning_margin = getattr(settings, 'CAPACITY_WARNING_MARGIN', 2)
                near_limit_ratio = getattr(settings, 'CAPACITY_NEAR_LIMIT_RATIO', 0.9)

                if enrolled > cap:
                    conflicts.append(Conflict(
                        type=ConflictType.SMALL_CLASSROOM,
                        severity=ConflictSeverity.WARNING,
                        description=f"La session du {s1.date.strftime('%d/%m/%Y')} pour '{s1.group.name if s1.group else ''}' compte {enrolled} élèves inscrits, ce qui dépasse la capacité de la salle '{s1.room.name}' ({cap} places).",
                        entity_id=s1.room.id,
                        entity_name=s1.room.name,
                        session1_id=s1.id,
                        date=s1.date
                    ))
                elif enrolled >= cap * near_limit_ratio or cap - enrolled <= warning_margin:
                    if enrolled > 0:
                        conflicts.append(Conflict(
                            type=ConflictType.CAPACITY_NEAR_LIMIT,
                            severity=ConflictSeverity.WARNING,
                            description=f"La session du {s1.date.strftime('%d/%m/%Y')} pour '{s1.group.name if s1.group else ''}' approche de la capacité maximale de la salle '{s1.room.name}' ({enrolled}/{cap} places).",
                            entity_id=s1.room.id,
                            entity_name=s1.room.name,
                            session1_id=s1.id,
                            date=s1.date
                        ))
                elif enrolled <= cap * 0.3 and cap >= 10:
                    conflicts.append(Conflict(
                        type=ConflictType.LARGE_CLASSROOM,
                        severity=ConflictSeverity.WARNING,
                        description=f"La salle '{s1.room.name}' ({cap} places) est trop grande pour le groupe '{s1.group.name if s1.group else ''}' ({enrolled} élèves inscrits).",
                        entity_id=s1.room.id,
                        entity_name=s1.room.name,
                        session1_id=s1.id,
                        date=s1.date
                    ))

            # Room suitability check
            if s1.room and s1.group:
                suitability_issues = []
                if s1.group.requires_accessibility and not s1.room.accessibility:
                    suitability_issues.append("accessibilité PMR")
                if s1.group.requires_computer_lab and not s1.room.has_computer_lab:
                    suitability_issues.append("laboratoire informatique")
                if s1.group.requires_science_lab and not s1.room.has_science_lab:
                    suitability_issues.append("laboratoire scientifique")
                if s1.group.requires_projector and not s1.room.has_projector:
                    suitability_issues.append("projecteur")
                if s1.group.requires_air_conditioning and not s1.room.has_air_conditioning:
                    suitability_issues.append("climatisation")
                    
                if suitability_issues:
                    issues_str = ", ".join(suitability_issues)
                    conflicts.append(Conflict(
                        type=ConflictType.ROOM_SUITABILITY,
                        severity=ConflictSeverity.WARNING,
                        description=f"La salle '{s1.room.name}' ne convient pas au groupe '{s1.group.name}' : manque d'équipements ({issues_str}).",
                        entity_id=s1.room.id,
                        entity_name=s1.room.name,
                        session1_id=s1.id,
                        date=s1.date
                    ))

            # Check Recurring Exceptions (Room)
            if s1.room:
                for exc in rec_exceptions:
                    if exc.target_type == 'ROOM' and exc.room_id == s1.room_id:
                        if exc.matches_date_and_time(s1.date, s1.start_time, s1.end_time) and not exc.is_available:
                            conflicts.append(Conflict(
                                type=ConflictType.ROOM_DOUBLE_BOOKING,
                                severity=ConflictSeverity.WARNING,
                                description=f"La salle '{s1.room.name}' a une indisponibilité récurrente le {s1.date.strftime('%d/%m/%Y')} de {exc.start_time.strftime('%H:%M')} à {exc.end_time.strftime('%H:%M')}.",
                                entity_id=s1.room.id,
                                entity_name=s1.room.name,
                                session1_id=s1.id,
                                date=s1.date
                            ))

            # Info: manual overrides
            if s1.is_manually_edited:
                conflicts.append(Conflict(
                    type=ConflictType.MANUAL_OVERRIDE,
                    severity=ConflictSeverity.INFO,
                    description=f"La séance du {s1.date.strftime('%d/%m/%Y')} a été modifiée manuellement.",
                    session1_id=s1.id,
                    date=s1.date
                ))

            # Info: makeup session
            if s1.id in makeup_session_ids:
                conflicts.append(Conflict(
                    type=ConflictType.MAKEUP_SESSION,
                    severity=ConflictSeverity.INFO,
                    description=f"La séance du {s1.date.strftime('%d/%m/%Y')} est une séance de rattrapage.",
                    session1_id=s1.id,
                    date=s1.date
                ))

            # Direct overlap check with other sessions in the lists
            for s2 in sessions[i + 1:]:
                if s1.date != s2.date:
                    continue
                if not cls.time_overlaps(s1.start_time, s1.end_time, s2.start_time, s2.end_time):
                    continue

                # Room double booking
                if s1.room_id == s2.room_id:
                    conflicts.append(Conflict(
                        type=ConflictType.ROOM_DOUBLE_BOOKING,
                        severity=ConflictSeverity.BLOCKING,
                        description=f"La salle '{s1.room.name if s1.room else s1.room_id}' est réservée en double le {s1.date.strftime('%d/%m/%Y')} de {s1.start_time.strftime('%H:%M')} à {s1.end_time.strftime('%H:%M')}.",
                        entity_id=s1.room_id,
                        entity_name=s1.room.name if s1.room else str(s1.room_id),
                        session1_id=s1.id,
                        session2_id=s2.id,
                        date=s1.date,
                        start_time=s1.start_time,
                        end_time=s1.end_time
                    ))

                # Teacher double booking
                t2 = cls.get_effective_teacher(s2)
                if t1 and t2 and t1.id == t2.id:
                    conflicts.append(Conflict(
                        type=ConflictType.TEACHER_DOUBLE_BOOKING,
                        severity=ConflictSeverity.BLOCKING,
                        description=f"Le professeur '{t1.name}' est affecté à deux cours le {s1.date.strftime('%d/%m/%Y')} de {s1.start_time.strftime('%H:%M')} à {s1.end_time.strftime('%H:%M')}.",
                        entity_id=t1.id,
                        entity_name=t1.name,
                        session1_id=s1.id,
                        session2_id=s2.id,
                        date=s1.date,
                        start_time=s1.start_time,
                        end_time=s1.end_time
                    ))

                # Group double booking
                if s1.group_id and s1.group_id == s2.group_id:
                    conflicts.append(Conflict(
                        type=ConflictType.GROUP_DOUBLE_BOOKING,
                        severity=ConflictSeverity.BLOCKING,
                        description=f"Le groupe '{s1.group.name if s1.group else s1.group_id}' a deux sessions planifiées en même temps le {s1.date.strftime('%d/%m/%Y')} de {s1.start_time.strftime('%H:%M')} à {s1.end_time.strftime('%H:%M')}.",
                        entity_id=s1.group_id,
                        entity_name=s1.group.name if s1.group else str(s1.group_id),
                        session1_id=s1.id,
                        session2_id=s2.id,
                        date=s1.date,
                        start_time=s1.start_time,
                        end_time=s1.end_time
                    ))

            # Student overlaps check
            s1_students = session_students_resolved.get(s1.id or id(s1), [])
            if s1_students:
                for s2 in sessions:
                    if s1 == s2 or s1.date != s2.date:
                        continue
                    if not cls.time_overlaps(s1.start_time, s1.end_time, s2.start_time, s2.end_time):
                        continue
                    # Enforce ordering to avoid duplicate alerts
                    if (s1.id and s2.id and s1.id >= s2.id) or (not s1.id and not s2.id and id(s1) >= id(s2)):
                        continue
                    s2_students = session_students_resolved.get(s2.id or id(s2), [])
                    common_students = set(s1_students).intersection(s2_students)
                    for std in common_students:
                        conflicts.append(Conflict(
                            type=ConflictType.STUDENT_OVERLAP,
                            severity=ConflictSeverity.WARNING,
                            description=f"L'élève '{std.name}' est inscrit dans '{s1.group.name if s1.group else ''}' et '{s2.group.name if s2.group else ''}' qui se chevauchent le {s1.date.strftime('%d/%m/%Y')} de {max(s1.start_time, s2.start_time).strftime('%H:%M')} à {min(s1.end_time, s2.end_time).strftime('%H:%M')}.",
                            student_id=std.id,
                            student_name=std.name,
                            session1_id=s1.id,
                            session2_id=s2.id,
                            date=s1.date
                        ))

        return conflicts

    @classmethod
    def check_conflicts_for_schedules(cls, schedules: List[CourseGroupSchedule]) -> List[Conflict]:
        """
        Weekly schedule conflict detection (static level).
        """
        conflicts = []
        
        # Load teacher availabilities
        teacher_ids = {sch.course_group.teacher_id for sch in schedules if sch.course_group and sch.course_group.teacher_id}
        availabilities = TeacherAvailability.objects.filter(teacher_id__in=teacher_ids)
        avail_map = defaultdict(list)
        for av in availabilities:
            avail_map[(av.teacher_id, av.day)].append(av)

        # Load recurring exceptions
        from core.models import RecurringException
        room_ids = {sch.room_id for sch in schedules if sch.room_id}
        rec_exceptions = list(RecurringException.objects.filter(
            Q(teacher_id__in=teacher_ids, target_type='TEACHER') |
            Q(room_id__in=room_ids, target_type='ROOM')
        ).filter(recurrence_type='WEEKLY'))

        # Get enrollment counts
        group_ids = {sch.course_group_id for sch in schedules}
        enrollment_counts = Enrollment.objects.filter(
            course_group_id__in=group_ids,
            is_active=True,
            student__is_active=True
        ).values('course_group_id').annotate(count=Count('id'))
        student_counts_map = {item['course_group_id']: item['count'] for item in enrollment_counts}

        # Student schedules overlap mapping
        enrollments = Enrollment.objects.filter(
            course_group_id__in=group_ids,
            is_active=True,
            student__is_active=True
        ).select_related('student')
        
        student_groups = defaultdict(list)
        for enr in enrollments:
            student_groups[enr.student].append(enr.course_group_id)

        group_schedules_map = defaultdict(list)
        for sch in schedules:
            group_schedules_map[sch.course_group_id].append(sch)

        for i, sch1 in enumerate(schedules):
            # Check Teacher Availability / Unavailability / Out of Bounds
            t = sch1.course_group.teacher if sch1.course_group else None
            if t:
                teacher_avails = avail_map.get((t.id, sch1.day), [])
                
                # 1. Unavailability
                unavail = [a for a in teacher_avails if not a.is_available]
                for entry in unavail:
                    if cls.time_overlaps(sch1.start_time, sch1.end_time, entry.start_time, entry.end_time):
                        conflicts.append(Conflict(
                            type=ConflictType.TEACHER_UNAVAILABLE,
                            severity=ConflictSeverity.WARNING,
                            description=f"Le professeur '{t.name}' est marqué indisponible le {sch1.get_day_display()} de {entry.start_time.strftime('%H:%M')} à {entry.end_time.strftime('%H:%M')}.",
                            entity_id=t.id,
                            entity_name=t.name,
                            sch1_id=sch1.id
                        ))

                # 2. Out of bounds
                avail_slots = [a for a in teacher_avails if a.is_available]
                if avail_slots and not any(
                    sch1.start_time >= entry.start_time and sch1.end_time <= entry.end_time
                    for entry in avail_slots
                ):
                    conflicts.append(Conflict(
                        type=ConflictType.TEACHER_OUT_OF_BOUNDS,
                        severity=ConflictSeverity.WARNING,
                        description=f"L'horaire hebdomadaire du groupe '{sch1.course_group.name}' est planifié en dehors des heures de disponibilité de '{t.name}'.",
                        entity_id=t.id,
                        entity_name=t.name,
                        sch1_id=sch1.id
                    ))

            # Capacity warnings
            if sch1.room:
                enrolled = student_counts_map.get(sch1.course_group_id, 0)
                cap = sch1.room.capacity
                
                warning_margin = getattr(settings, 'CAPACITY_WARNING_MARGIN', 2)
                near_limit_ratio = getattr(settings, 'CAPACITY_NEAR_LIMIT_RATIO', 0.9)

                if enrolled > cap:
                    conflicts.append(Conflict(
                        type=ConflictType.SMALL_CLASSROOM,
                        severity=ConflictSeverity.WARNING,
                        description=f"Le groupe '{sch1.course_group.name}' compte {enrolled} élèves inscrits, ce qui dépasse la capacité de la salle '{sch1.room.name}' le {sch1.get_day_display()} ({cap} places).",
                        entity_id=sch1.room.id,
                        entity_name=sch1.room.name,
                        sch1_id=sch1.id
                    ))
                elif enrolled >= cap * near_limit_ratio or cap - enrolled <= warning_margin:
                    if enrolled > 0:
                        conflicts.append(Conflict(
                            type=ConflictType.CAPACITY_NEAR_LIMIT,
                            severity=ConflictSeverity.WARNING,
                            description=f"Le groupe '{sch1.course_group.name}' approche de la capacité maximale de la salle '{sch1.room.name}' ({enrolled}/{cap} places) le {sch1.get_day_display()}.",
                            entity_id=sch1.room.id,
                            entity_name=sch1.room.name,
                            sch1_id=sch1.id
                        ))
                elif enrolled <= cap * 0.3 and cap >= 10:
                    conflicts.append(Conflict(
                        type=ConflictType.LARGE_CLASSROOM,
                        severity=ConflictSeverity.WARNING,
                        description=f"La salle hebdomadaire '{sch1.room.name}' ({cap} places) est sous-utilisée par le groupe '{sch1.course_group.name}' ({enrolled} élèves inscrits) le {sch1.get_day_display()}.",
                        entity_id=sch1.room.id,
                        entity_name=sch1.room.name,
                        sch1_id=sch1.id
                    ))

            # Room suitability check (weekly schedule)
            if sch1.room and sch1.course_group:
                suitability_issues = []
                if sch1.course_group.requires_accessibility and not sch1.room.accessibility:
                    suitability_issues.append("accessibilité PMR")
                if sch1.course_group.requires_computer_lab and not sch1.room.has_computer_lab:
                    suitability_issues.append("laboratoire informatique")
                if sch1.course_group.requires_science_lab and not sch1.room.has_science_lab:
                    suitability_issues.append("laboratoire scientifique")
                if sch1.course_group.requires_projector and not sch1.room.has_projector:
                    suitability_issues.append("projecteur")
                if sch1.course_group.requires_air_conditioning and not sch1.room.has_air_conditioning:
                    suitability_issues.append("climatisation")
                    
                if suitability_issues:
                    issues_str = ", ".join(suitability_issues)
                    conflicts.append(Conflict(
                        type=ConflictType.ROOM_SUITABILITY,
                        severity=ConflictSeverity.WARNING,
                        description=f"La salle hebdomadaire '{sch1.room.name}' ne convient pas au groupe '{sch1.course_group.name}' : manque d'équipements ({issues_str}) le {sch1.get_day_display()}.",
                        entity_id=sch1.room.id,
                        entity_name=sch1.room.name,
                        sch1_id=sch1.id
                    ))

            # Check Recurring Exceptions (Teacher - Weekly)
            t = sch1.course_group.teacher if sch1.course_group else None
            if t:
                for exc in rec_exceptions:
                    if exc.target_type == 'TEACHER' and exc.teacher_id == t.id and exc.day_of_week == sch1.day:
                        if cls.time_overlaps(sch1.start_time, sch1.end_time, exc.start_time, exc.end_time) and not exc.is_available:
                            conflicts.append(Conflict(
                                type=ConflictType.TEACHER_UNAVAILABLE,
                                severity=ConflictSeverity.WARNING,
                                description=f"Le professeur '{t.name}' a une indisponibilité récurrente le {sch1.get_day_display()} de {exc.start_time.strftime('%H:%M')} à {exc.end_time.strftime('%H:%M')}.",
                                entity_id=t.id,
                                entity_name=t.name,
                                sch1_id=sch1.id
                            ))
                            
            # Check Recurring Exceptions (Room - Weekly)
            if sch1.room:
                for exc in rec_exceptions:
                    if exc.target_type == 'ROOM' and exc.room_id == sch1.room_id and exc.day_of_week == sch1.day:
                        if cls.time_overlaps(sch1.start_time, sch1.end_time, exc.start_time, exc.end_time) and not exc.is_available:
                            conflicts.append(Conflict(
                                type=ConflictType.ROOM_DOUBLE_BOOKING,
                                severity=ConflictSeverity.WARNING,
                                description=f"La salle '{sch1.room.name}' a une indisponibilité récurrente le {sch1.get_day_display()} de {exc.start_time.strftime('%H:%M')} à {exc.end_time.strftime('%H:%M')}.",
                                entity_id=sch1.room.id,
                                entity_name=sch1.room.name,
                                sch1_id=sch1.id
                            ))

            # Double bookings with other weekly schedules
            for sch2 in schedules[i + 1:]:
                if sch1.day != sch2.day:
                    continue
                if not cls.time_overlaps(sch1.start_time, sch1.end_time, sch2.start_time, sch2.end_time):
                    continue

                # Room double booking
                if sch1.room_id == sch2.room_id:
                    conflicts.append(Conflict(
                        type=ConflictType.ROOM_DOUBLE_BOOKING,
                        severity=ConflictSeverity.BLOCKING,
                        description=f"La salle '{sch1.room.name}' est réservée en double le {sch1.get_day_display()} de {sch1.start_time.strftime('%H:%M')} à {sch1.end_time.strftime('%H:%M')}.",
                        entity_id=sch1.room_id,
                        entity_name=sch1.room.name,
                        sch1_id=sch1.id,
                        sch2_id=sch2.id
                    ))

                # Teacher double booking
                t1 = sch1.course_group.teacher if sch1.course_group else None
                t2 = sch2.course_group.teacher if sch2.course_group else None
                if t1 and t2 and t1.id == t2.id:
                    conflicts.append(Conflict(
                        type=ConflictType.TEACHER_DOUBLE_BOOKING,
                        severity=ConflictSeverity.BLOCKING,
                        description=f"Le professeur '{t1.name}' est affecté à deux cours le {sch1.get_day_display()} de {sch1.start_time.strftime('%H:%M')} à {sch1.end_time.strftime('%H:%M')}.",
                        entity_id=t1.id,
                        entity_name=t1.name,
                        sch1_id=sch1.id,
                        sch2_id=sch2.id
                    ))

        # Check student weekly schedule overlap
        seen_pairs = set()
        for std, grp_ids in student_groups.items():
            if len(grp_ids) < 2:
                continue
            for i_g in range(len(grp_ids)):
                for j_g in range(i_g + 1, len(grp_ids)):
                    schedules_a = group_schedules_map.get(grp_ids[i_g], [])
                    schedules_b = group_schedules_map.get(grp_ids[j_g], [])
                    for sch_a in schedules_a:
                        for sch_b in schedules_b:
                            if sch_a.day != sch_b.day:
                                continue
                            if not cls.time_overlaps(sch_a.start_time, sch_a.end_time, sch_b.start_time, sch_b.end_time):
                                continue
                            key = (std.id, min(sch_a.id, sch_b.id), max(sch_a.id, sch_b.id))
                            if key in seen_pairs:
                                continue
                            seen_pairs.add(key)
                            conflicts.append(Conflict(
                                type=ConflictType.STUDENT_OVERLAP,
                                severity=ConflictSeverity.WARNING,
                                description=f"L'élève '{std.name}' est inscrit dans '{sch_a.course_group.name}' et '{sch_b.course_group.name}' qui se chevauchent le {sch_a.get_day_display()} de {max(sch_a.start_time, sch_b.start_time).strftime('%H:%M')} à {min(sch_a.end_time, sch_b.end_time).strftime('%H:%M')}.",
                                student_id=std.id,
                                student_name=std.name,
                                sch1_id=sch_a.id,
                                sch2_id=sch_b.id
                            ))

        return conflicts

    @classmethod
    def detect_database_conflicts(cls, past_days: int = 14, future_days: int = 30) -> Dict[str, List[Conflict]]:
        """
        Equivalent to detect_all_conflicts but returning domain Conflict objects.
        """
        today = timezone.now().date()
        window_start = today - timedelta(days=past_days)
        window_end = today + timedelta(days=future_days)

        # 1. Weekly schedule conflicts
        schedules = list(CourseGroupSchedule.objects.filter(
            course_group__is_active=True
        ).select_related('course_group', 'course_group__teacher', 'room'))
        
        all_schedule_conflicts = cls.check_conflicts_for_schedules(schedules)

        # Separate schedule conflicts from student overlaps (since they are shown in different lists in templates)
        schedule_conflicts = [c for c in all_schedule_conflicts if c.type != ConflictType.STUDENT_OVERLAP]
        student_conflicts = [c for c in all_schedule_conflicts if c.type == ConflictType.STUDENT_OVERLAP]

        # 2. Dynamic session conflicts
        sessions = list(Session.objects.filter(
            date__range=[window_start, window_end]
        ).exclude(status='CANCELLED').select_related(
            'group', 'group__teacher', 'substitute_teacher', 'room'
        ))

        all_session_conflicts = cls.check_conflicts_for_sessions(sessions)
        
        session_conflicts = [c for c in all_session_conflicts if c.severity == ConflictSeverity.BLOCKING]
        capacity_warnings = [c for c in all_session_conflicts if c.type in (ConflictType.SMALL_CLASSROOM, ConflictType.CAPACITY_NEAR_LIMIT, ConflictType.LARGE_CLASSROOM)]
        info_alerts = [c for c in all_session_conflicts if c.severity == ConflictSeverity.INFO]
        
        # Merge any student overlaps found on session level
        session_student_overlaps = [c for c in all_session_conflicts if c.type == ConflictType.STUDENT_OVERLAP]
        student_conflicts.extend(session_student_overlaps)

        # Total counts
        total_count = len(schedule_conflicts) + len(session_conflicts) + len(capacity_warnings) + len(student_conflicts) + len(info_alerts)

        return {
            'schedule_conflicts': schedule_conflicts,
            'session_conflicts': session_conflicts,
            'capacity_warnings': capacity_warnings,
            'student_conflicts': student_conflicts,
            'info_alerts': info_alerts,
            'total_count': total_count,
            'scan_window_start': window_start,
            'scan_window_end': window_end,
        }
