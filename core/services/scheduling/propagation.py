from datetime import date, timedelta
from typing import List, Dict, Any, Optional
from django.db import transaction
from core.models import Session, CourseGroup
from .locking import LockingService
from .audit import AuditService

class SchedulePropagationService:
    @staticmethod
    def get_academic_year_range(date_val: date) -> tuple:
        if date_val.month >= 9:
            start_date = date(date_val.year, 9, 1)
            end_date = date(date_val.year + 1, 8, 31)
        else:
            start_date = date(date_val.year - 1, 9, 1)
            end_date = date(date_val.year, 8, 31)
        return start_date, end_date

    @classmethod
    def propagate_session_changes(
        cls,
        session: Session,
        scope: str,  # 'only_this', 'this_week', 'future', 'academic_year'
        updates: Dict[str, Any],
        user: Optional[Any] = None,
        ip_address: Optional[str] = None,
        change_reason: Optional[str] = None
    ) -> List[Session]:
        """
        Propagates edits across target scopes in an atomic transaction.
        Validates locking for all affected dates and skips manual exceptions.
        """
        # Validate locking for the primary session date
        LockingService.check_lock(session.date)

        group = session.group
        date_val = session.date

        # Determine target sessions in scope
        if scope == 'only_this':
            targets = [session]
        elif scope == 'this_week':
            monday = date_val - timedelta(days=date_val.weekday())
            sunday = monday + timedelta(days=6)
            LockingService.check_lock_for_range(monday, sunday)
            targets = list(Session.objects.filter(
                group=group,
                date__range=[monday, sunday]
            ).exclude(is_manually_edited=True).exclude(pk=session.pk))
            targets.insert(0, session)
        elif scope == 'future':
            targets = list(Session.objects.filter(
                group=group,
                date__gte=date_val
            ).exclude(is_manually_edited=True).exclude(pk=session.pk))
            if targets:
                max_date = max(t.date for t in targets)
                LockingService.check_lock_for_range(date_val, max_date)
            targets.insert(0, session)
        elif scope == 'academic_year':
            start_ac, end_ac = cls.get_academic_year_range(date_val)
            LockingService.check_lock_for_range(start_ac, end_ac)
            targets = list(Session.objects.filter(
                group=group,
                date__range=[start_ac, end_ac]
            ).exclude(is_manually_edited=True).exclude(pk=session.pk))
            targets.insert(0, session)
        else:
            targets = [session]

        updated_sessions = []
        with transaction.atomic():
            for t in targets:
                # Capture values for comparison
                prev_vals = {
                    'start_time': t.start_time.strftime('%H:%M') if t.start_time else None,
                    'end_time': t.end_time.strftime('%H:%M') if t.end_time else None,
                    'room_id': t.room_id,
                    'substitute_teacher_id': t.substitute_teacher_id,
                    'status': t.status,
                    'notes': t.notes
                }

                # Apply updates
                if 'start_time' in updates:
                    t.start_time = updates['start_time']
                if 'end_time' in updates:
                    t.end_time = updates['end_time']
                if 'room_id' in updates:
                    t.room_id = int(updates['room_id'])
                if 'substitute_teacher_id' in updates:
                    val = updates['substitute_teacher_id']
                    t.substitute_teacher_id = int(val) if val else None
                if 'status' in updates:
                    t.status = updates['status']
                if 'notes' in updates:
                    t.notes = updates['notes']

                # Mark as manually edited if this is the source session
                if t == session:
                    t.is_manually_edited = True

                t.full_clean()
                t.save()
                updated_sessions.append(t)

                # Determine new values and log differences
                new_vals = {
                    'start_time': t.start_time.strftime('%H:%M') if t.start_time else None,
                    'end_time': t.end_time.strftime('%H:%M') if t.end_time else None,
                    'room_id': t.room_id,
                    'substitute_teacher_id': t.substitute_teacher_id,
                    'status': t.status,
                    'notes': t.notes
                }

                changed_prev = {}
                changed_new = {}
                for k, v in new_vals.items():
                    if prev_vals[k] != v:
                        changed_prev[k] = prev_vals[k]
                        changed_new[k] = v

                # Always audit log the main session, and other sessions only if actual changes happened
                if changed_prev or changed_new or t == session:
                    action = 'manual_override' if t == session else 'update'
                    AuditService.log_change(
                        session=t,
                        user=user,
                        action=action,
                        previous_values=changed_prev,
                        new_values=changed_new,
                        change_reason=change_reason,
                        ip_address=ip_address
                    )

        return updated_sessions
