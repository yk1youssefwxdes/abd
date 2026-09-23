"""
core/signals.py
───────────────
Session change detection + WhatsApp notification pipeline.

Flow:
  pre_save  → snapshot (status, date, start_time, room_id) before DB write
  post_save → compare snapshot to saved values; if changed, send WA messages
"""
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.conf import settings


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

_SNAPSHOT_ATTR = '_pre_save_snapshot'


def _build_cancellation_message(session) -> str:
    from .utils import load_message_template, SafeDict
    date_str = session.date.strftime('%d/%m/%Y')
    default_template = (
        "Séance annulée\n\n"
        "Groupe : {group_name}\n"
        "Date : {date}\n"
        "Heure : {start_time} - {end_time}\n\n"
        "La séance du {date} a été annulée. "
        "Nous nous excusons pour la gêne occasionnée."
    )
    template_str = load_message_template('whatsapp_session_cancellation.txt', default_template)
    return template_str.format_map(SafeDict({
        'group_name': session.group.name,
        'date': date_str,
        'start_time': session.start_time.strftime('%H:%M'),
        'end_time': session.end_time.strftime('%H:%M'),
    }))


def _build_change_message(session, changes: list) -> str:
    from .utils import load_message_template, SafeDict
    date_str = session.date.strftime('%d/%m/%Y')
    change_lines = '\n'.join(f'  - {c}' for c in changes)
    default_template = (
        "Modification de séance\n\n"
        "Groupe : {group_name}\n"
        "Date : {date}\n"
        "Heure : {start_time} - {end_time}\n"
        "Salle : {room_name}\n\n"
        "Les informations suivantes ont change :\n{change_lines}"
    )
    template_str = load_message_template('whatsapp_session_change.txt', default_template)
    return template_str.format_map(SafeDict({
        'group_name': session.group.name,
        'date': date_str,
        'start_time': session.start_time.strftime('%H:%M'),
        'end_time': session.end_time.strftime('%H:%M'),
        'room_name': session.room.name,
        'change_lines': change_lines,
    }))


def _notify(phone: str, message: str, student=None, message_type: str = 'session_reminder'):
    """Send a WhatsApp message and log it. Never raises."""
    try:
        from .utils import WhatsAppServiceAPI
        from .models import WhatsAppSendLog

        result = WhatsAppServiceAPI.send_message(phone, message)
        WhatsAppSendLog.objects.create(
            student=student,
            phone=phone,
            message_type=message_type,
            message_preview=message[:300],
            status='SENT' if result.get('success') else 'FAILED',
            error_message=result.get('error', '') if not result.get('success') else '',
        )
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Signal receivers
# ──────────────────────────────────────────────────────────────────────────────

@receiver(pre_save, sender='core.Session')
def session_pre_save_snapshot(sender, instance, **kwargs):
    """Capture the pre-save state so post_save can diff it."""
    if not instance.pk:
        setattr(instance, _SNAPSHOT_ATTR, None)
        return
    try:
        old = sender.objects.get(pk=instance.pk)
        setattr(instance, _SNAPSHOT_ATTR, {
            'status':     old.status,
            'date':       old.date,
            'start_time': old.start_time,
            'end_time':   old.end_time,
            'room_id':    old.room_id,
        })
    except sender.DoesNotExist:
        setattr(instance, _SNAPSHOT_ATTR, None)


import atexit
import logging
from concurrent.futures import ThreadPoolExecutor
from django.db import connection, transaction

logger = logging.getLogger(__name__)

# Bounded executor to avoid uncontrolled thread explosion and prevent message loss on shutdown
_notification_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="wa_notify")
atexit.register(lambda: _notification_executor.shutdown(wait=True, cancel_futures=False))


def _run_async(func, *args, **kwargs):
    """Schedule a task asynchronously in the bounded worker pool, closing DB connection on completion."""
    def worker():
        try:
            func(*args, **kwargs)
        except Exception:
            logger.exception("Error executing asynchronous WhatsApp notification")
        finally:
            connection.close()

    try:
        transaction.on_commit(lambda: _notification_executor.submit(worker))
    except Exception:
        _notification_executor.submit(worker)


def _async_send_session_notifications(session_id: int, now_cancelled: bool, schedule_changes: list, msg_type: str):
    """Worker function to send session cancellation/change notifications in background."""
    from .models import Session
    try:
        instance = (
            Session.objects
            .select_related('group', 'room', 'substitute_teacher', 'group__teacher')
            .get(pk=session_id)
        )
    except Exception:
        return

    if now_cancelled:
        message = _build_cancellation_message(instance)
    else:
        message = _build_change_message(instance, schedule_changes)

    # Notify enrolled students via parent contact
    try:
        import time
        enrolled_students = (
            instance.group.students
            .filter(is_active=True, enrollment__is_active=True)
            .distinct()
        )
        for student in enrolled_students:
            phones = [
                p for p in [student.parent_contact, student.parent_contact_2, student.phone]
                if p
            ]
            seen = set()
            for phone in phones:
                if phone not in seen:
                    seen.add(phone)
                    _notify(phone, message, student=student, message_type=msg_type)
                    time.sleep(0.3)  # Gentle spacing for WhatsApp Web without holding Django request
    except Exception:
        pass

    # Notify the teacher (substitute takes precedence over primary teacher)
    try:
        teacher = instance.substitute_teacher or instance.group.teacher
        if teacher and teacher.phone:
            teacher_label = "[Remplaçant]" if instance.substitute_teacher else "[Professeur]"
            _notify(
                teacher.phone,
                f"{teacher_label} {message}",
                student=None,
                message_type=msg_type,
            )
    except Exception:
        pass


if settings.WHATSAPP_SESSION_NOTIFICATIONS_ENABLED:
    @receiver(post_save, sender='core.Session')
    def session_post_save_notify(sender, instance, created, **kwargs):
        """
        After a Session is saved, diff against snapshot and send WA notifications
        for cancellations or meaningful schedule changes ONLY if _auto_notify is explicitly set to True.
        Notifications are dispatched asynchronously to keep requests fast and non-blocking.
        """
        if created:
            return

        if not getattr(instance, '_auto_notify', False):
            return

        snapshot = getattr(instance, _SNAPSHOT_ATTR, None)
        if snapshot is None:
            return

        now_cancelled = (
            snapshot['status'] != 'CANCELLED'
            and instance.status == 'CANCELLED'
        )

        schedule_changes = []
        if instance.date != snapshot['date']:
            schedule_changes.append(
                f"Date : {snapshot['date'].strftime('%d/%m/%Y')} → {instance.date.strftime('%d/%m/%Y')}"
            )
        if instance.start_time != snapshot['start_time']:
            schedule_changes.append(
                f"Heure début : {snapshot['start_time'].strftime('%H:%M')} → {instance.start_time.strftime('%H:%M')}"
            )
        if instance.end_time != snapshot.get('end_time') and snapshot.get('end_time') is not None:
            schedule_changes.append(
                f"Heure fin : {snapshot['end_time'].strftime('%H:%M')} → {instance.end_time.strftime('%H:%M')}"
            )
        if instance.room_id != snapshot['room_id']:
            try:
                from .models import Room
                old_room = Room.objects.filter(pk=snapshot['room_id']).first()
                old_room_name = old_room.name if old_room else str(snapshot['room_id'])
            except Exception:
                old_room_name = str(snapshot['room_id'])
            schedule_changes.append(f"Salle : {old_room_name} → {instance.room.name}")

        if not now_cancelled and not schedule_changes:
            return

        msg_type = 'absence_notification' if now_cancelled else 'session_reminder'
        _run_async(_async_send_session_notifications, instance.pk, now_cancelled, schedule_changes, msg_type)


@receiver(post_save, sender='core.Payment')
def payment_post_save_send_group_invites(sender, instance, created, **kwargs):
    """
    When a payment is created with status='PAID', check if the student has
    enrolled groups whose WhatsApp invite link has not been sent yet, and auto-send them.
    """
    if instance.status == 'PAID' and instance.student:
        try:
            from .utils import send_whatsapp_group_invites
            send_whatsapp_group_invites(instance.student)
        except Exception:
            pass

