from datetime import date, datetime, time
from typing import List
from django.utils import timezone
from core.models import Session

class CalendarExporter:
    @staticmethod
    def format_ics_datetime(dt_val: datetime) -> str:
        utc_dt = timezone.make_naive(dt_val, timezone.utc) if timezone.is_aware(dt_val) else dt_val
        return utc_dt.strftime('%Y%m%dT%H%M%SZ')

    @classmethod
    def generate_ics(cls, sessions: List[Session], title: str) -> str:
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Centre//Academic Scheduling System//FR",
            f"X-WR-CALNAME:{title}",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH"
        ]

        for s in sessions:
            if s.status == 'CANCELLED':
                continue
            
            start_dt = timezone.make_aware(datetime.combine(s.date, s.start_time))
            end_dt = timezone.make_aware(datetime.combine(s.date, s.end_time))
            
            dtstamp = cls.format_ics_datetime(s.created_at if s.created_at else timezone.now())
            dtstart = cls.format_ics_datetime(start_dt)
            dtend = cls.format_ics_datetime(end_dt)
            
            summary = f"{s.group.name if s.group else ''} ({s.group.subject if s.group else ''})"
            description = s.notes or ""
            teacher = s.substitute_teacher or (s.group.teacher if s.group else None)
            if teacher:
                description += f"\\nProfesseur: {teacher.name}"
            
            location = s.room.name if s.room else "N/A"
            uid = f"session-{s.id}@centre-tonaroz.com"
            
            lines.extend([
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{dtstamp}",
                f"DTSTART:{dtstart}",
                f"DTEND:{dtend}",
                f"SUMMARY:{summary}",
                f"DESCRIPTION:{description}",
                f"LOCATION:{location}",
                "STATUS:CONFIRMED",
                "TRANSP:OPAQUE",
                "END:VEVENT"
            ])
            
        lines.append("END:VCALENDAR")
        return "\r\n".join(lines)
