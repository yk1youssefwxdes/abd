from typing import Dict, Any, Optional
from django.contrib.auth.models import User
from core.models import Session, SessionChangeHistory

class AuditService:
    @staticmethod
    def log_change(
        session: Session,
        user: Optional[User],
        action: str,
        previous_values: Dict[str, Any],
        new_values: Dict[str, Any],
        change_reason: Optional[str] = None,
        ip_address: Optional[str] = None,
        is_handled: bool = False
    ) -> SessionChangeHistory:
        """
        Explicitly logs a session modification or creation to the SessionChangeHistory model.
        """
        return SessionChangeHistory.objects.create(
            session=session,
            user=user,
            action=action,
            previous_values=previous_values,
            new_values=new_values,
            change_reason=change_reason or "",
            ip_address=ip_address,
            is_handled=is_handled
        )

    @staticmethod
    def get_unhandled_changes(date_start=None, date_end=None, session_id=None):
        """
        Retrieves all unhandled SessionChangeHistory records, optionally filtered by date range or session.
        """
        qs = SessionChangeHistory.objects.filter(is_handled=False).select_related(
            'session',
            'session__group',
            'session__group__teacher',
            'session__room',
            'session__substitute_teacher',
            'user'
        ).prefetch_related(
            'session__group__students'
        ).order_by('-timestamp')

        if session_id:
            qs = qs.filter(session_id=session_id)
        if date_start and date_end:
            qs = qs.filter(session__date__range=[date_start, date_end])

        return qs

    @staticmethod
    def get_unhandled_count(date_start=None, date_end=None) -> int:
        """
        Returns the total count of unhandled changes.
        """
        qs = SessionChangeHistory.objects.filter(is_handled=False)
        if date_start and date_end:
            qs = qs.filter(session__date__range=[date_start, date_end])
        return qs.count()

    @staticmethod
    def get_unhandled_session_ids() -> set:
        """
        Returns a set of session IDs that currently have unhandled changes.
        """
        return set(
            SessionChangeHistory.objects.filter(is_handled=False, session__isnull=False)
            .values_list('session_id', flat=True)
            .distinct()
        )

