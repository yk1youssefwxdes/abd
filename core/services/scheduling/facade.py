from datetime import date, timedelta, datetime
from typing import List, Dict, Any, Optional
from django.db import transaction, models
from django.db.models import Q
from django.utils import timezone
from collections import defaultdict

from core.models import Session, CourseGroup, ScheduleLock, Attendance, Room, Teacher
from .domain import ScheduleDiff, Conflict, RescheduleSuggestion
from .locking import LockingService
from .conflicts import ConflictService
from .preview import SchedulePreviewService
from .propagation import SchedulePropagationService
from .rescheduling import ReschedulingAssistantService
from .audit import AuditService

class SchedulingFacade:
    @staticmethod
    def is_locked(target_date: date) -> bool:
        return LockingService.is_locked(target_date)

    @staticmethod
    def get_conflicts(past_days: int = 14, future_days: int = 30) -> Dict[str, Any]:
        return ConflictService.detect_database_conflicts(past_days, future_days)

    @staticmethod
    def preview_regeneration(
        start_date: date,
        end_date: date,
        force: bool = False,
        course: Optional[CourseGroup] = None
    ) -> ScheduleDiff:
        return SchedulePreviewService.preview_bulk_generation(start_date, end_date, force, course)

    @staticmethod
    @transaction.atomic
    def execute_regeneration(
        start_date: date,
        end_date: date,
        force: bool = False,
        course: Optional[CourseGroup] = None,
        user: Optional[Any] = None,
        ip_address: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Executes bulk session generation. Validates locking first. Runs atomically.
        """
        LockingService.check_lock_for_range(start_date, end_date)
        from core.utils import generate_sessions_from_coursegroups
        
        # We run the existing generation inside a transaction block
        summary = generate_sessions_from_coursegroups(start_date, end_date, force, course)
        return summary

    @staticmethod
    def propagate_session_changes(
        session: Session,
        scope: str,
        updates: Dict[str, Any],
        user: Optional[Any] = None,
        ip_address: Optional[str] = None,
        change_reason: Optional[str] = None
    ) -> List[Session]:
        return SchedulePropagationService.propagate_session_changes(
            session, scope, updates, user, ip_address, change_reason
        )

    @staticmethod
    def get_reschedule_suggestions(session: Session) -> List[RescheduleSuggestion]:
        return ReschedulingAssistantService.get_reschedule_suggestions(session)

    @staticmethod
    def apply_reschedule_suggestion(
        session: Session,
        suggestion: RescheduleSuggestion,
        user: Optional[Any] = None,
        ip_address: Optional[str] = None,
        change_reason: Optional[str] = None
    ) -> Session:
        return ReschedulingAssistantService.apply_reschedule_suggestion(
            session, suggestion, user, ip_address, change_reason
        )

    @staticmethod
    @transaction.atomic
    def toggle_schedule_lock(
        is_locked: bool,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        academic_year: Optional[str] = None,
        user: Optional[Any] = None,
        notes: str = ""
    ) -> ScheduleLock:
        """
        Toggles or creates a date-range schedule lock.
        """
        if not is_locked:
            ScheduleLock.objects.all().update(is_locked=False)
            lock = ScheduleLock.objects.create(
                is_locked=False,
                locked_by=user,
                notes=notes or "Déverrouillage global"
            )
        else:
            lock = ScheduleLock.objects.create(
                is_locked=True,
                start_date=start_date,
                end_date=end_date,
                academic_year=academic_year,
                locked_by=user,
                notes=notes or "Verrouillage de planning"
            )
        return lock

    @staticmethod
    @transaction.atomic
    def reset_session_attendance(
        session: Session,
        user: Optional[Any] = None,
        ip_address: Optional[str] = None
    ) -> int:
        """
        Resets all attendance records for a session and logs the change.
        """
        LockingService.check_lock(session.date)
        
        attendances = Attendance.objects.filter(session=session)
        count = attendances.count()
        previous_status = session.status
        
        attendances.delete()
        session.status = 'PLANNED'
        session.save()
        
        AuditService.log_change(
            session=session,
            user=user,
            action='attendance_reset',
            previous_values={'status': previous_status, 'attendance_count': count},
            new_values={'status': 'PLANNED', 'attendance_count': 0},
            change_reason="Réinitialisation de la présence",
            ip_address=ip_address
        )
        return count

    @staticmethod
    def get_conflict_suggestions(conflict: Conflict) -> List[Dict[str, Any]]:
        from .suggestions import ConflictResolutionService
        return ConflictResolutionService.get_suggestions(conflict)

    @staticmethod
    @transaction.atomic
    def publish_schedule(
        start_date: date,
        end_date: date,
        user: Optional[Any] = None,
        ip_address: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Publishes all DRAFT sessions in the date range.
        Creates an audit entry for each published session.
        """
        draft_sessions = Session.objects.filter(
            date__range=[start_date, end_date],
            schedule_status='DRAFT'
        )
        count = draft_sessions.count()
        
        for s in draft_sessions:
            s.schedule_status = 'PUBLISHED'
            s.save()
            AuditService.log_change(
                session=s,
                user=user,
                action='update',
                previous_values={'schedule_status': 'DRAFT'},
                new_values={'schedule_status': 'PUBLISHED'},
                change_reason="Publication du planning",
                ip_address=ip_address
            )
            
            # Send notifications (Event: schedule published)
            from .notifications import NotificationService
            NotificationService.send_schedule_published(s)
            
        return {'published_count': count}

    @staticmethod
    @transaction.atomic
    def execute_bulk_operation(
        action: str,  # 'cancel', 'move', 'room_change', 'teacher_replace', 'attendance_reset', 'lock', 'unlock'
        filters: Dict[str, Any],
        params: Dict[str, Any],
        user: Optional[Any] = None,
        ip_address: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Executes a bulk operation (cancel, move, room change, teacher replacement, etc.)
        validating locks and conflicts.
        """
        qs = Session.objects.all()
        
        date_start = filters.get('date_start')
        date_end = filters.get('date_end')
        if date_start and date_end:
            qs = qs.filter(date__range=[date_start, date_end])
            
        teacher_id = filters.get('teacher_id')
        if teacher_id:
            qs = qs.filter(Q(group__teacher_id=teacher_id) | Q(substitute_teacher_id=teacher_id))
            
        room_id = filters.get('room_id')
        if room_id:
            qs = qs.filter(room_id=room_id)
            
        group_id = filters.get('group_id')
        if group_id:
            qs = qs.filter(group_id=group_id)
            
        weekday = filters.get('weekday')
        
        sessions = list(qs)
        
        if weekday:
            day_map = {0: 'MON', 1: 'TUE', 2: 'WED', 3: 'THU', 4: 'FRI', 5: 'SAT', 6: 'SUN'}
            sessions = [s for s in sessions if day_map[s.date.weekday()] in weekday]
            
        count = len(sessions)
        updated_count = 0
        skipped_count = 0
        
        if action == 'cancel':
            for s in sessions:
                if LockingService.is_locked(s.date):
                    skipped_count += 1
                    continue
                if s.status != 'CANCELLED':
                    prev_status = s.status
                    s.status = 'CANCELLED'
                    s.is_manually_edited = True
                    s.save()
                    AuditService.log_change(s, user, 'update', {'status': prev_status}, {'status': 'CANCELLED'}, "Annulation en masse", ip_address)
                    updated_count += 1
                    
                    from .notifications import NotificationService
                    NotificationService.send_session_cancelled(s)
                    
        elif action == 'move':
            days_offset = int(params.get('days_offset', 0))
            for s in sessions:
                old_date = s.date
                new_date = old_date + timedelta(days=days_offset)
                if LockingService.is_locked(old_date) or LockingService.is_locked(new_date):
                    skipped_count += 1
                    continue
                s.date = new_date
                s.is_manually_edited = True
                s.save()
                AuditService.log_change(s, user, 'update', {'date': str(old_date)}, {'date': str(new_date)}, "Déplacement en masse", ip_address)
                updated_count += 1
                
                from .notifications import NotificationService
                NotificationService.send_session_moved(s)
                
        elif action == 'room_change':
            new_room_id = int(params.get('new_room_id'))
            new_room = Room.objects.get(id=new_room_id)
            for s in sessions:
                if LockingService.is_locked(s.date):
                    skipped_count += 1
                    continue
                old_room_name = s.room.name if s.room else ''
                s.room = new_room
                s.is_manually_edited = True
                s.save()
                AuditService.log_change(s, user, 'update', {'room': old_room_name}, {'room': new_room.name}, "Changement de salle en masse", ip_address)
                updated_count += 1
                
                from .notifications import NotificationService
                NotificationService.send_room_changed(s)
                
        elif action == 'teacher_replace':
            new_teacher_id = int(params.get('new_teacher_id'))
            new_teacher = Teacher.objects.get(id=new_teacher_id)
            for s in sessions:
                if LockingService.is_locked(s.date):
                    skipped_count += 1
                    continue
                old_sub = s.substitute_teacher.name if s.substitute_teacher else (s.group.teacher.name if s.group and s.group.teacher else '')
                s.substitute_teacher = new_teacher
                s.is_manually_edited = True
                s.save()
                AuditService.log_change(s, user, 'update', {'substitute_teacher': old_sub}, {'substitute_teacher': new_teacher.name}, "Remplacement prof en masse", ip_address)
                updated_count += 1
                
                from .notifications import NotificationService
                NotificationService.send_teacher_substituted(s)
                
        elif action == 'attendance_reset':
            for s in sessions:
                if LockingService.is_locked(s.date):
                    skipped_count += 1
                    continue
                SchedulingFacade.reset_session_attendance(s, user, ip_address)
                updated_count += 1
                
        elif action in ['lock', 'unlock']:
            is_locked = (action == 'lock')
            lock = SchedulingFacade.toggle_schedule_lock(
                is_locked=is_locked,
                start_date=date_start,
                end_date=date_end,
                user=user,
                notes=params.get('notes', "Verrouillage/Déverrouillage en masse")
            )
            updated_count = len(sessions)
            
        return {
            'total_found': count,
            'updated': updated_count,
            'skipped_count': skipped_count
        }

    @staticmethod
    def get_teacher_workload(
        teacher: Teacher,
        start_date: date,
        end_date: date
    ) -> Dict[str, Any]:
        """
        Calculates teacher workload metrics and analytics.
        """
        sessions = Session.objects.filter(
            date__range=[start_date, end_date]
        ).filter(
            Q(group__teacher=teacher, substitute_teacher__isnull=True) |
            Q(substitute_teacher=teacher)
        ).select_related('group', 'room')
        
        total_hours = 0.0
        cancelled_hours = 0.0
        substitution_hours = 0.0
        session_count = 0
        
        sessions_by_date = defaultdict(list)
        for s in sessions:
            sessions_by_date[s.date].append(s)
            
        max_consecutive = 0
        daily_gaps = 0
        
        for dt_val, day_sessions in sessions_by_date.items():
            day_sessions.sort(key=lambda x: x.start_time)
            consec_run = 0
            prev_end = None
            
            for s in day_sessions:
                dur = (datetime.combine(dt_val, s.end_time) - datetime.combine(dt_val, s.start_time)).total_seconds() / 3600.0
                if s.status == 'CANCELLED':
                    cancelled_hours += dur
                else:
                    total_hours += dur
                    session_count += 1
                    if s.substitute_teacher == teacher:
                        substitution_hours += dur
                        
                    if prev_end:
                        gap = (datetime.combine(dt_val, s.start_time) - datetime.combine(dt_val, prev_end)).total_seconds() / 60.0
                        if gap > 0:
                            daily_gaps += gap
                        if gap <= 15:
                            consec_run += 1
                        else:
                            consec_run = 1
                    else:
                        consec_run = 1
                        
                    max_consecutive = max(max_consecutive, consec_run)
                    prev_end = s.end_time
                    
        return {
            'total_hours': round(total_hours, 2),
            'cancelled_hours': round(cancelled_hours, 2),
            'substitution_hours': round(substitution_hours, 2),
            'session_count': session_count,
            'consecutive_sessions': max_consecutive,
            'daily_gaps_minutes': int(daily_gaps),
            'overtime': max(0.0, total_hours - 40.0)
        }

    @staticmethod
    def get_calendar_ics(entity_type: str, entity_id: int) -> str:
        """
        Generates ICS string for teacher, student, room, or group.
        """
        from .exporter import CalendarExporter
        from core.models import Session, Teacher, Student, Room, CourseGroup
        
        sessions_qs = Session.objects.filter(schedule_status='PUBLISHED').select_related('group', 'room', 'substitute_teacher', 'group__teacher')
        
        if entity_type == 'teacher':
            teacher = Teacher.objects.get(id=entity_id)
            title = f"Planning de {teacher.name}"
            sessions_qs = sessions_qs.filter(Q(group__teacher_id=entity_id) | Q(substitute_teacher_id=entity_id))
        elif entity_type == 'student':
            student = Student.objects.get(id=entity_id)
            title = f"Planning de {student.name}"
            sessions_qs = sessions_qs.filter(group__students=student)
        elif entity_type == 'room':
            room = Room.objects.get(id=entity_id)
            title = f"Planning de la salle {room.name}"
            sessions_qs = sessions_qs.filter(room_id=entity_id)
        elif entity_type == 'group':
            group = CourseGroup.objects.get(id=entity_id)
            title = f"Planning du groupe {group.name}"
            sessions_qs = sessions_qs.filter(group_id=entity_id)
        else:
            raise ValueError("Type d'entité invalide.")
            
        return CalendarExporter.generate_ics(list(sessions_qs), title)

    @staticmethod
    def get_unhandled_changes(date_start=None, date_end=None, session_id=None):
        return AuditService.get_unhandled_changes(date_start=date_start, date_end=date_end, session_id=session_id)

    @staticmethod
    def get_unhandled_count(date_start=None, date_end=None) -> int:
        return AuditService.get_unhandled_count(date_start=date_start, date_end=date_end)

    @staticmethod
    @transaction.atomic
    def handle_changes(
        history_ids: Optional[List[int]] = None,
        handle_all: bool = False,
        send_notifications: bool = True,
        notify_teachers: bool = True,
        notify_students: bool = True,
        user: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Marks unhandled session change history records as handled, and optionally dispatches notifications.
        Can process all unhandled changes (handle_all=True) or a specified list of history IDs.
        """
        from core.models import SessionChangeHistory
        from .notifications import NotificationService

        qs = SessionChangeHistory.objects.filter(is_handled=False).select_related(
            'session', 'session__group', 'session__group__teacher', 'session__room', 'session__substitute_teacher'
        ).prefetch_related('session__group__students')

        if not handle_all:
            if not history_ids:
                return {'handled_count': 0, 'notifications_sent': 0, 'message': 'Aucune modification sélectionnée.'}
            qs = qs.filter(id__in=history_ids)

        records = list(qs)
        count = len(records)
        if count == 0:
            return {'handled_count': 0, 'notifications_sent': 0, 'message': 'Aucune modification en attente à traiter.'}

        notification_stats = {'total_notifications': 0, 'teachers_notified_count': 0, 'students_notified_count': 0}
        if send_notifications:
            notification_stats = NotificationService.dispatch_batch_change_notifications(
                history_records=records,
                notify_teachers=notify_teachers,
                notify_students=notify_students
            )

        now = timezone.now()
        ids_to_update = [r.id for r in records]
        SessionChangeHistory.objects.filter(id__in=ids_to_update).update(
            is_handled=True,
            handled_at=now
        )

        return {
            'handled_count': count,
            'notifications_sent': notification_stats['total_notifications'],
            'teachers_notified_count': notification_stats['teachers_notified_count'],
            'students_notified_count': notification_stats['students_notified_count'],
            'message': f"{count} modification(s) traitée(s) avec succès."
        }

