from django import template
from core.models import CourseGroup

register = template.Library()


from django.db.models import Q

@register.simple_tag
def load_courses(student=None):
    """
    Usage:
        {% load_courses student as courses %}
        {% load_courses as courses %}
    """
    courses = (
        CourseGroup.objects
        .filter(is_active=True)
        .select_related('teacher')
        .prefetch_related('schedules__room')
    )

    if student:
        enrolled_ids = student.enrollment_set.values_list(
            'course_group_id', flat=True
        )
        courses = courses.exclude(id__in=enrolled_ids)

        # Show courses matching the student's level, plus level-agnostic courses
        courses = courses.filter(
            Q(levels=student.level) | Q(level=student.level) | (Q(levels__isnull=True) & Q(level__isnull=True))
        ).distinct()

    return courses.order_by('name')