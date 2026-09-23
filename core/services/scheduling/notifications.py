import logging
from typing import List, Dict, Any, Optional
from django.conf import settings
from django.utils import timezone
from core.models import Session, Student, WhatsAppSendLog

logger = logging.getLogger('django')


class NotificationService:
    @staticmethod
    def _dispatch_notification(
        recipient_name: str,
        recipient_phone: Optional[str],
        recipient_email: Optional[str],
        subject: str,
        message: str,
        context: Dict[str, Any],
        student: Optional[Student] = None,
        message_type: str = 'session_reminder'
    ) -> bool:
        """
        Base dispatcher. Sends via WhatsApp when phone is available, logs to WhatsAppSendLog and system logs.
        """
        log_msg = (
            f"\n--- NOTIFICATION DISPATCHED ---\n"
            f"To: {recipient_name}\n"
            f"Phone: {recipient_phone or 'N/A'}\n"
            f"Email: {recipient_email or 'N/A'}\n"
            f"Subject: {subject}\n"
            f"Message: {message}\n"
            f"---------------------------------\n"
        )
        logger.info(log_msg)

        sent = False
        if recipient_phone:
            try:
                from core.utils import WhatsAppServiceAPI
                result = WhatsAppServiceAPI.send_message(recipient_phone, message)
                status = 'SENT' if result.get('success') else 'FAILED'
                err = result.get('error', '') if not result.get('success') else ''
                sent = result.get('success', False)
                WhatsAppSendLog.objects.create(
                    student=student,
                    phone=recipient_phone,
                    message_type=message_type,
                    message_preview=message[:300],
                    status=status,
                    error_message=err
                )
            except Exception as e:
                logger.warning(f"Failed to dispatch WhatsApp message to {recipient_phone}: {e}")
        return sent

    @classmethod
    def format_history_diff(cls, history_entry) -> List[str]:
        """
        Translates raw previous_values vs new_values into readable text lines.
        """
        changes = []
        new_vals = history_entry.new_values or {}
        prev_vals = history_entry.previous_values or {}

        field_labels = {
            'date': 'Date',
            'start_time': 'Heure début',
            'end_time': 'Heure fin',
            'room': 'Salle',
            'substitute_teacher': 'Professeur remplaçant',
            'status': 'Statut',
            'schedule_status': 'État planning'
        }

        for key, new_v in new_vals.items():
            prev_v = prev_vals.get(key, '—')
            label = field_labels.get(key, key)
            if key == 'status' and new_v == 'CANCELLED':
                changes.append("Séance annulée")
            elif key == 'status' and prev_v == 'CANCELLED' and new_v != 'CANCELLED':
                changes.append(f"Séance réactivée ({new_v})")
            else:
                changes.append(f"{label} : {prev_v or '—'} → {new_v or '—'}")

        if not changes and history_entry.action:
            changes.append(f"Action : {history_entry.action}")

        return changes

    @classmethod
    def notify_history_change(
        cls,
        history_entry,
        notify_teachers: bool = True,
        notify_students: bool = True
    ) -> Dict[str, Any]:
        """
        Dispatches notifications for a single SessionChangeHistory record.
        """
        session = history_entry.session
        diff_lines = cls.format_history_diff(history_entry)
        details = "\n".join(f"• {c}" for c in diff_lines) if diff_lines else "Planning mis à jour."
        group_name = session.group.name if session and session.group else "Cours"
        date_str = session.date.strftime('%d/%m/%Y') if session and session.date else ""

        notifications_sent = 0
        teacher_notified = False
        students_notified = 0

        # 1. Notify Teacher
        if notify_teachers and session:
            teacher = session.substitute_teacher or (session.group.teacher if session.group else None)
            if teacher and teacher.phone:
                msg = (
                    f"📢 *Notification de cours — {group_name}*\n\n"
                    f"Bonjour {teacher.name},\n"
                    f"Votre cours du {date_str} a été modifié :\n"
                    f"{details}\n"
                )
                if history_entry.change_reason:
                    msg += f"\n*Motif :* {history_entry.change_reason}\n"
                msg += "\nCordialement,\nLa Direction."

                cls._dispatch_notification(
                    recipient_name=teacher.name,
                    recipient_phone=teacher.phone,
                    recipient_email=teacher.email,
                    subject=f"Modification de cours: {group_name}",
                    message=msg,
                    context={'history_id': history_entry.id, 'session_id': session.id},
                    message_type='session_reminder'
                )
                teacher_notified = True
                notifications_sent += 1

        # 2. Notify Students & Parents
        if notify_students and session:
            students = []
            from core.models import MakeupSession
            makeup_link = MakeupSession.objects.filter(makeup_session=session).first()
            if makeup_link:
                students = makeup_link.students.filter(is_active=True)
            elif session.group:
                students = session.group.students.filter(is_active=True)

            for student in students:
                student_msg = (
                    f"📢 *Information Planning — {group_name}*\n\n"
                    f"Bonjour {student.name},\n"
                    f"La séance de votre cours du {date_str} a été modifiée :\n"
                    f"{details}\n"
                )
                if history_entry.change_reason:
                    student_msg += f"\n*Motif :* {history_entry.change_reason}\n"
                student_msg += "\nMerci de prendre note de ce changement.\nLa Direction."

                phones = [p for p in [student.parent_contact, student.parent_contact_2, student.phone] if p]
                seen_phones = set()
                for ph in phones:
                    if ph not in seen_phones:
                        seen_phones.add(ph)
                        cls._dispatch_notification(
                            recipient_name=student.name,
                            recipient_phone=ph,
                            recipient_email="",
                            subject=f"Planning modifié: {group_name}",
                            message=student_msg,
                            context={'history_id': history_entry.id, 'student_id': student.id},
                            student=student,
                            message_type='session_reminder'
                        )
                        notifications_sent += 1
                students_notified += 1

        return {
            'notifications_sent': notifications_sent,
            'teacher_notified': teacher_notified,
            'students_notified': students_notified
        }

    @classmethod
    def dispatch_batch_change_notifications(
        cls,
        history_records: List[Any],
        notify_teachers: bool = True,
        notify_students: bool = True
    ) -> Dict[str, Any]:
        """
        Dispatches notifications for multiple SessionChangeHistory records.
        """
        total_notifications = 0
        total_teachers = 0
        total_students = 0

        for h in history_records:
            res = cls.notify_history_change(
                h,
                notify_teachers=notify_teachers,
                notify_students=notify_students
            )
            total_notifications += res['notifications_sent']
            if res['teacher_notified']:
                total_teachers += 1
            total_students += res['students_notified']

        return {
            'total_notifications': total_notifications,
            'teachers_notified_count': total_teachers,
            'students_notified_count': total_students
        }

    @classmethod
    def notify_session_change(cls, session: Session, change_type: str, details: str):
        teacher = session.substitute_teacher or (session.group.teacher if session.group else None)
        if teacher:
            cls._dispatch_notification(
                recipient_name=teacher.name,
                recipient_phone=teacher.phone,
                recipient_email=teacher.email,
                subject=f"Modification de cours: {session.group.name if session.group else ''}",
                message=f"Bonjour {teacher.name}, votre cours du {session.date.strftime('%d/%m/%Y')} a été modifié ({change_type}). Détails: {details}",
                context={'session_id': session.id, 'type': change_type}
            )

        students = []
        from core.models import MakeupSession
        makeup_link = MakeupSession.objects.filter(makeup_session=session).first()
        if makeup_link:
            students = makeup_link.students.filter(is_active=True)
        elif session.group:
            students = session.group.students.filter(is_active=True)

        for student in students:
            if student.phone:
                cls._dispatch_notification(
                    recipient_name=student.name,
                    recipient_phone=student.phone,
                    recipient_email="",
                    subject=f"Cours modifié: {session.group.name if session.group else ''}",
                    message=f"Bonjour {student.name}, la séance du {session.date.strftime('%d/%m/%Y')} a été modifiée ({change_type}). Détails: {details}",
                    context={'session_id': session.id, 'student_id': student.id},
                    student=student
                )
            if student.parent_contact:
                cls._dispatch_notification(
                    recipient_name=f"Parent de {student.name} ({student.parent_name or ''})",
                    recipient_phone=student.parent_contact,
                    recipient_email="",
                    subject=f"Avis de modification: {session.group.name if session.group else ''}",
                    message=f"Bonjour, nous vous informons que le cours de votre enfant {student.name} du {session.date.strftime('%d/%m/%Y')} a été modifié ({change_type}). Détails: {details}",
                    context={'session_id': session.id, 'student_id': student.id},
                    student=student
                )

    @classmethod
    def send_session_cancelled(cls, session: Session):
        details = "La séance a été annulée."
        cls.notify_session_change(session, "Annulation", details)

    @classmethod
    def send_session_moved(cls, session: Session):
        details = f"La séance a été déplacée au {session.date.strftime('%d/%m/%Y')} de {session.start_time.strftime('%H:%M')} à {session.end_time.strftime('%H:%M')}."
        cls.notify_session_change(session, "Déplacement", details)

    @classmethod
    def send_room_changed(cls, session: Session):
        details = f"La salle a été modifiée. Nouveau lieu: {session.room.name if session.room else 'N/A'}."
        cls.notify_session_change(session, "Changement de salle", details)

    @classmethod
    def send_teacher_substituted(cls, session: Session):
        teacher_name = session.substitute_teacher.name if session.substitute_teacher else "N/A"
        details = f"Remplacement d'enseignant. Nouveau professeur: {teacher_name}."
        cls.notify_session_change(session, "Enseignant remplacé", details)

    @classmethod
    def send_makeup_session_created(cls, session: Session):
        details = f"Séance de rattrapage programmée le {session.date.strftime('%d/%m/%Y')} de {session.start_time.strftime('%H:%M')} à {session.end_time.strftime('%H:%M')}."
        cls.notify_session_change(session, "Séance de rattrapage", details)

    @classmethod
    def send_schedule_published(cls, session: Session):
        details = f"Le planning pour la séance du {session.date.strftime('%d/%m/%Y')} a été officiellement publié."
        cls.notify_session_change(session, "Publication du planning", details)

