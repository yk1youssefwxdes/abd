import threading
from django.core.cache import cache
from django.conf import settings


def conflicts_count(request):
    """
    Returns {'conflict_count': <int>} with the total number of active
    schedule conflicts (room + teacher overlaps).

    Results are cached for 2 minutes so every page load doesn't trigger
    a full scan. The cache is invalidated by the post_save signal on
    CourseGroupSchedule (see models.py).
    """
    CACHE_KEY = 'sidebar_conflict_count'
    CACHE_TTL = getattr(settings, 'CONFLICT_CACHE_TTL', 120)

    count = cache.get(CACHE_KEY)
    if count is None:
        try:
            from collections import defaultdict
            from .models import CourseGroupSchedule, TeacherAvailability
            from .utils import _detect_schedule_conflicts, _detect_schedule_availability_conflicts
            schedules = list(
                CourseGroupSchedule.objects.filter(course_group__is_active=True)
                .select_related('course_group', 'course_group__teacher', 'room')
            )
            overlap_conflicts = _detect_schedule_conflicts(schedules)

            teacher_ids = {sch.course_group.teacher_id for sch in schedules if getattr(sch.course_group, 'teacher_id', None)}
            availability_entries = TeacherAvailability.objects.filter(teacher_id__in=teacher_ids).select_related('teacher')
            availability_map = defaultdict(list)
            for entry in availability_entries:
                availability_map[(entry.teacher_id, entry.day)].append(entry)

            avail_conflicts = _detect_schedule_availability_conflicts(schedules, availability_map)
            count = len(overlap_conflicts) + len(avail_conflicts)
        except Exception:
            count = 0
        cache.set(CACHE_KEY, count, CACHE_TTL)

    return {'conflict_count': count}


def whatsapp_status(request):
    """
    Returns {'whatsapp_connected': True/False} to show status indicator in main sidebar.
    Cached for 30 seconds. If expired, refreshes asynchronously in background to
    prevent slowing down page loads or blocking on network timeouts.
    """
    CACHE_KEY = 'sidebar_whatsapp_status'
    CACHE_TTL = 30
    
    connected = cache.get(CACHE_KEY)
    if connected is None:
        def _refresh():
            try:
                from .utils import WhatsAppServiceAPI
                status_data = WhatsAppServiceAPI.get_status(timeout=0.4)
                is_conn = not status_data.get('offline', True) and status_data.get('status') == 'READY'
                cache.set(CACHE_KEY, is_conn, CACHE_TTL)
            except Exception:
                cache.set(CACHE_KEY, False, CACHE_TTL)

        # Set a quick temporary flag so concurrent requests don't all trigger threads
        cache.set(CACHE_KEY, False, 5)
        threading.Thread(target=_refresh, daemon=True).start()
        return {'whatsapp_connected': False}
        
    return {'whatsapp_connected': connected}


def school_info(request):
    """
    Returns configurable school settings to be available in all templates.
    Cached in bulk for 5 minutes.
    """
    CACHE_KEY = 'school_info_context'
    info = cache.get(CACHE_KEY)
    if info is not None:
        return info

    from .utils import get_setting
    info = {
        'SCHOOL_NAME': get_setting('CENTER_NAME') or get_setting('SCHOOL_NAME', 'Centre'),
        'SCHOOL_SUBTITLE': get_setting('SCHOOL_SUBTITLE', 'Soutien Scolaire & Langues'),
        'SCHOOL_ADDRESS': get_setting('SCHOOL_ADDRESS', 'Rue Marrakech, Im 16, Ap N 3, 2ème Étage, Khouribga'),
        'SCHOOL_PHONE': get_setting('SCHOOL_PHONE', '0707477911 / 0661569522'),
        'SCHOOL_EMAIL': get_setting('SCHOOL_EMAIL', 'contact@centre-tonaroz.com'),
        'SCHOOL_LOGO_PATH': get_setting('SCHOOL_LOGO_PATH', 'images/tonaroz_logo.svg'),
        'CURRENCY_SYMBOL': get_setting('CURRENCY_SYMBOL', 'DH'),
    }
    cache.set(CACHE_KEY, info, 300)
    return info

