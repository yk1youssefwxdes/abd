from datetime import date
from typing import List
from django.core.exceptions import ValidationError
from core.models import ScheduleLock

class LockingService:
    @staticmethod
    def is_locked(target_date: date) -> bool:
        """
        Check if the schedule is locked for a specific date.
        Locks can be global (no dates), date-range bound, or academic year bound.
        """
        active_locks = ScheduleLock.objects.filter(is_locked=True)
        for lock in active_locks:
            # Global lock
            if not lock.start_date and not lock.end_date:
                return True
            # Range lock
            l_start = lock.start_date or date.min
            l_end = lock.end_date or date.max
            if l_start <= target_date <= l_end:
                return True
        return False

    @classmethod
    def check_lock(cls, target_date: date):
        """
        Raises a ValidationError if the schedule is locked for the target_date.
        """
        if cls.is_locked(target_date):
            raise ValidationError(f"Le planning est actuellement verrouillé pour la date {target_date.strftime('%d/%m/%Y')}.")

    @classmethod
    def check_lock_for_range(cls, start_date: date, end_date: date):
        """
        Raises a ValidationError if any lock overlaps with the [start_date, end_date] range.
        """
        active_locks = ScheduleLock.objects.filter(is_locked=True)
        for lock in active_locks:
            if not lock.start_date and not lock.end_date:
                raise ValidationError("Le planning est actuellement verrouillé globalement.")
            
            l_start = lock.start_date or date.min
            l_end = lock.end_date or date.max
            if max(l_start, start_date) <= min(l_end, end_date):
                period_str = f"du {lock.start_date.strftime('%d/%m/%Y')}" if lock.start_date else ""
                period_str += f" au {lock.end_date.strftime('%d/%m/%Y')}" if lock.end_date else ""
                raise ValidationError(f"Le planning est actuellement verrouillé pour la période {period_str}.")
