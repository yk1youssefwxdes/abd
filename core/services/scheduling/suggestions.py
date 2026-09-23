from datetime import date, time, datetime, timedelta
from typing import List, Dict, Any, Optional
from django.db.models import Q
from core.models import Room, Teacher, CourseGroup, Session, Enrollment, MakeupSession
from .domain import Conflict, ConflictType, ConflictSeverity, RescheduleSuggestion
from .conflicts import ConflictService
from .rescheduling import ReschedulingAssistantService

class ConflictResolutionService:
    @classmethod
    def get_suggestions(cls, conflict: Conflict) -> List[Dict[str, Any]]:
        suggestions = []
        c_type = conflict.type

        # 1. ROOM CONFLICT / SUITABILITY / CAPACITY
        if c_type in [ConflictType.ROOM_DOUBLE_BOOKING, ConflictType.ROOM_SUITABILITY, ConflictType.SMALL_CLASSROOM, ConflictType.CAPACITY_NEAR_LIMIT]:
            conflict_date = conflict.date
            start_t = conflict.start_time
            end_t = conflict.end_time

            rooms = Room.objects.filter(is_active=True)
            if conflict.room:
                rooms = rooms.exclude(id=conflict.room.id)
                
            if conflict_date and start_t and end_t:
                busy_room_ids = Session.objects.filter(
                    date=conflict_date,
                    status__in=['PLANNED', 'DONE']
                ).filter(
                    start_time__lt=end_t,
                    end_time__gt=start_t
                ).values_list('room_id', flat=True)
                rooms = rooms.exclude(id__in=busy_room_ids)

            course = conflict.course
            enrolled_count = conflict.enrolled if course else 0

            for r in rooms:
                score = 0
                reasons = []

                if r.capacity >= enrolled_count:
                    score += 20
                    reasons.append(f"Capacité suffisante ({r.capacity} places)")
                else:
                    reasons.append(f"Capacité insuffisante ({r.capacity} places)")

                if conflict.room and r.building == conflict.room.building:
                    score += 10
                    reasons.append("Même bâtiment")
                
                if course:
                    equipment_matched = True
                    if course.requires_accessibility and not r.accessibility:
                        equipment_matched = False
                    if course.requires_computer_lab and not r.has_computer_lab:
                        equipment_matched = False
                    if course.requires_science_lab and not r.has_science_lab:
                        equipment_matched = False
                    if course.requires_projector and not r.has_projector:
                        equipment_matched = False
                    if course.requires_air_conditioning and not r.has_air_conditioning:
                        equipment_matched = False
                    
                    if equipment_matched:
                        score += 30
                        reasons.append("Équipements ok")
                    else:
                        reasons.append("Équipements manquants")

                suggestions.append({
                    'type': 'ROOM_CHANGE',
                    'room_id': r.id,
                    'room_name': r.name,
                    'score': score,
                    'description': f"Changer vers salle '{r.name}': " + ", ".join(reasons)
                })

            suggestions.sort(key=lambda x: x['score'], reverse=True)

        # 2. TEACHER CONFLICT / LEAVE / AVAILABILITY
        elif c_type in [ConflictType.TEACHER_DOUBLE_BOOKING, ConflictType.TEACHER_LEAVE, ConflictType.TEACHER_UNAVAILABLE, ConflictType.TEACHER_OUT_OF_BOUNDS]:
            conflict_date = conflict.date
            start_t = conflict.start_time
            end_t = conflict.end_time
            course = conflict.course

            if conflict_date and start_t and end_t:
                busy_teacher_ids = Session.objects.filter(
                    date=conflict_date,
                    status__in=['PLANNED', 'DONE']
                ).filter(
                    start_time__lt=end_t,
                    end_time__gt=start_t
                ).values_list('group__teacher_id', flat=True)

                teachers = Teacher.objects.filter(is_active=True).exclude(id__in=busy_teacher_ids)
                if course and course.teacher:
                    teachers = teachers.exclude(id=course.teacher.id)

                for t in teachers:
                    score = 0
                    reasons = []

                    teaches_subject = CourseGroup.objects.filter(teacher=t, subject__iexact=course.subject if course else "").exists()
                    if teaches_subject:
                        score += 30
                        reasons.append(f"Enseigne la matière '{course.subject}'")
                    else:
                        reasons.append("Matière différente")

                    day_map = {0: 'MON', 1: 'TUE', 2: 'WED', 3: 'THU', 4: 'FRI', 5: 'SAT', 6: 'SUN'}
                    day_code = day_map[conflict_date.weekday()]
                    from core.models import TeacherAvailability, TeacherLeave
                    avails = TeacherAvailability.objects.filter(teacher=t, day=day_code)
                    is_avail = True
                    for av in avails:
                        if not av.is_available and ConflictService.time_overlaps(start_t, end_t, av.start_time, av.end_time):
                            is_avail = False
                    
                    on_leave = TeacherLeave.objects.filter(teacher=t, start_date__lte=conflict_date, end_date__gte=conflict_date).exists()
                    if on_leave:
                        is_avail = False

                    if is_avail:
                        score += 20
                        reasons.append("Disponible")
                    else:
                        reasons.append("Indisponible/Congé")

                    suggestions.append({
                        'type': 'TEACHER_SUBSTITUTE',
                        'teacher_id': t.id,
                        'teacher_name': t.name,
                        'score': score,
                        'description': f"Remplacer par '{t.name}': " + ", ".join(reasons)
                    })

            # Suggest rescheduling to another time
            if conflict.session1:
                resched_sugs = ReschedulingAssistantService.get_reschedule_suggestions(conflict.session1)
                for rs in resched_sugs[:5]:
                    suggestions.append({
                        'type': 'RESCHEDULE_TIME',
                        'date': rs.date.strftime('%Y-%m-%d'),
                        'start_time': rs.start_time.strftime('%H:%M'),
                        'end_time': rs.end_time.strftime('%H:%M'),
                        'room_id': rs.room_id,
                        'room_name': rs.room_name,
                        'score': 100 - rs.conflict_score,
                        'description': f"Reporter au {rs.date.strftime('%d/%m/%Y')} de {rs.start_time.strftime('%H:%M')} à {rs.end_time.strftime('%H:%M')} en salle '{rs.room_name}' ({rs.reason})"
                    })

            suggestions.sort(key=lambda x: x['score'], reverse=True)

        # 3. STUDENT OVERLAP
        elif c_type == ConflictType.STUDENT_OVERLAP:
            student_id = conflict.student_id
            session1 = conflict.session1
            session2 = conflict.session2

            if student_id and session1 and session2:
                level = session1.group.level
                subject = session1.group.subject
                alt_groups = CourseGroup.objects.filter(level=level, subject__iexact=subject, is_active=True).exclude(id=session1.group.id)
                
                for g in alt_groups:
                    suggestions.append({
                        'type': 'STUDENT_TRANSFER',
                        'group_id': g.id,
                        'group_name': g.name,
                        'student_id': student_id,
                        'score': 50,
                        'description': f"Transférer l'élève vers le groupe alternatif '{g.name}'"
                    })

                makeup_sess = None
                if MakeupSession.objects.filter(makeup_session=session1).exists():
                    makeup_sess = session1
                elif MakeupSession.objects.filter(makeup_session=session2).exists():
                    makeup_sess = session2

                if makeup_sess:
                    resched_sugs = ReschedulingAssistantService.get_reschedule_suggestions(makeup_sess)
                    for rs in resched_sugs[:3]:
                        suggestions.append({
                            'type': 'RESCHEDULE_MAKEUP',
                            'session_id': makeup_sess.id,
                            'date': rs.date.strftime('%Y-%m-%d'),
                            'start_time': rs.start_time.strftime('%H:%M'),
                            'end_time': rs.end_time.strftime('%H:%M'),
                            'room_id': rs.room_id,
                            'room_name': rs.room_name,
                            'score': 80 - rs.conflict_score,
                            'description': f"Reporter la séance de rattrapage au {rs.date.strftime('%d/%m/%Y')} {rs.start_time.strftime('%H:%M')} (Salle {rs.room_name})"
                        })

        return suggestions[:8]
