from dataclasses import dataclass, field
from datetime import date, time
from typing import List, Dict, Any, Optional
from enum import Enum

class ConflictSeverity(str, Enum):
    BLOCKING = "blocking"
    WARNING = "warning"
    INFO = "info"

class ConflictType(str, Enum):
    ROOM_DOUBLE_BOOKING = "ROOM_DOUBLE_BOOKING"
    TEACHER_DOUBLE_BOOKING = "TEACHER_DOUBLE_BOOKING"
    GROUP_DOUBLE_BOOKING = "GROUP_DOUBLE_BOOKING"
    TEACHER_UNAVAILABLE = "TEACHER_UNAVAILABLE"
    TEACHER_LEAVE = "TEACHER_LEAVE"
    TEACHER_OUT_OF_BOUNDS = "TEACHER_OUT_OF_BOUNDS"
    LARGE_CLASSROOM = "LARGE_CLASSROOM"
    SMALL_CLASSROOM = "SMALL_CLASSROOM"
    CAPACITY_NEAR_LIMIT = "CAPACITY_NEAR_LIMIT"
    STUDENT_OVERLAP = "STUDENT_OVERLAP"
    ROOM_SUITABILITY = "ROOM_SUITABILITY"
    MAKEUP_SESSION = "MAKEUP_SESSION"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"
    HOLIDAY_ADJUSTMENT = "HOLIDAY_ADJUSTMENT"

@dataclass
class Conflict:
    type: ConflictType
    severity: ConflictSeverity
    description: str
    entity_id: Optional[int] = None
    entity_name: Optional[str] = None
    session1_id: Optional[int] = None
    session2_id: Optional[int] = None
    sch1_id: Optional[int] = None
    sch2_id: Optional[int] = None
    student_id: Optional[int] = None
    student_name: Optional[str] = None
    date: Optional[date] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None

    @property
    def session1(self):
        if self.session1_id:
            from core.models import Session
            return Session.objects.filter(id=self.session1_id).select_related('group', 'room').first()
        return None

    @property
    def session2(self):
        if self.session2_id:
            from core.models import Session
            return Session.objects.filter(id=self.session2_id).select_related('group', 'room').first()
        return None

    @property
    def sch1(self):
        if self.sch1_id:
            from core.models import CourseGroupSchedule
            return CourseGroupSchedule.objects.filter(id=self.sch1_id).select_related('course_group', 'room').first()
        return None

    @property
    def sch2(self):
        if self.sch2_id:
            from core.models import CourseGroupSchedule
            return CourseGroupSchedule.objects.filter(id=self.sch2_id).select_related('course_group', 'room').first()
        return None

    @property
    def entity(self):
        name_val = self.student_name or self.entity_name or ""
        class DummyEntity:
            name = name_val
        return DummyEntity()

    @property
    def course(self):
        if self.sch1:
            return self.sch1.course_group
        if self.session1:
            return self.session1.group
        return None

    @property
    def session(self):
        return self.session1

    @property
    def room(self):
        if self.session1 and self.session1.room:
            return self.session1.room
        if self.sch1 and self.sch1.room:
            return self.sch1.room
        return None

    @property
    def capacity(self):
        r = self.room
        return r.capacity if r else 0

    @property
    def enrolled(self):
        c = self.course
        if c:
            from core.models import Enrollment
            return Enrollment.objects.filter(course_group=c, is_active=True, student__is_active=True).count()
        return 0

    @property
    def overflow(self):
        return max(0, self.enrolled - self.capacity)

    @property
    def context(self):
        return 'SCHEDULE' if self.sch1_id else 'SESSION'



@dataclass
class ScheduleDiff:
    created_sessions: List[Dict[str, Any]] = field(default_factory=list)
    updated_sessions: List[Dict[str, Any]] = field(default_factory=list)
    removed_sessions: List[Dict[str, Any]] = field(default_factory=list)
    conflicts: List[Conflict] = field(default_factory=list)
    manual_exceptions: List[Dict[str, Any]] = field(default_factory=list)
    holiday_skips: List[Dict[str, Any]] = field(default_factory=list)
    teacher_leave_conflicts: List[Conflict] = field(default_factory=list)
    attendance_affected_count: int = 0
    conflicts_introduced: List[Conflict] = field(default_factory=list)
    conflicts_resolved: List[Conflict] = field(default_factory=list)
    locked_sessions_skipped_count: int = 0

@dataclass
class RescheduleSuggestion:
    date: date
    start_time: time
    end_time: time
    room_id: int
    room_name: str
    teacher_id: int
    teacher_name: str
    conflict_score: int
    reason: str
