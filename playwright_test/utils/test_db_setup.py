"""
Deterministic Test Database Setup for Playwright E2E Tests.
Sets up standard test users, roles, categories, levels, rooms, teachers,
course groups, students, enrollments, and sessions.
"""
import os
import sys
from pathlib import Path
from decimal import Decimal
from datetime import date, time, timedelta

# Set up Django environment
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "school_erp.settings")
os.environ.setdefault("AUTO_LICENSE", "true")

import django
django.setup()

from django.contrib.auth import get_user_model
from core.models import (
    UserProfile,
    Room,
    Teacher,
    TeacherPaymentMethod,
    TeacherAvailability,
    LevelCategory,
    Level,
    CourseGroup,
    CourseGroupSchedule,
    Student,
    Enrollment,
    Session,
    SessionStatus,
    Payment,
    PaymentMethod,
    PaymentStatus,
)

User = get_user_model()


def setup_test_data():
    print("Setting up deterministic test data for Playwright E2E testing...")

    # 1. Test Users
    users_data = [
        ("admin", "1234", "admin@school-erp.com", True, True, None),
        ("test_admin", "Password123!", "testadmin@school-erp.com", True, True, None),
        ("test_manager", "Password123!", "manager@school-erp.com", True, False, "ACADEMIC_MANAGER"),
        ("test_scheduler", "Password123!", "scheduler@school-erp.com", True, False, "SCHEDULER"),
        ("test_teacher_user", "Password123!", "teacher@school-erp.com", True, False, "TEACHER"),
        ("test_regular_user", "Password123!", "regular@school-erp.com", False, False, "STUDENT"),
    ]

    for username, password, email, is_staff, is_superuser, role in users_data:
        user, created = User.objects.get_or_create(
            username=username,
            defaults={"email": email, "is_staff": is_staff, "is_superuser": is_superuser},
        )
        user.set_password(password)
        user.is_staff = is_staff
        user.is_superuser = is_superuser
        user.email = email
        user.save()

        if role:
            UserProfile.objects.update_or_create(
                user=user,
                defaults={"role": role},
            )
        print(f"  [+] User '{username}' ready.")

    # 2. Rooms
    room1, _ = Room.objects.get_or_create(
        name="Salle Test A101",
        defaults={
            "capacity": 25,
            "building": "Bâtiment Principal",
            "floor": 1,
            "has_projector": True,
            "has_air_conditioning": True,
            "is_active": True,
        },
    )
    room2, _ = Room.objects.get_or_create(
        name="Salle Test B202",
        defaults={
            "capacity": 30,
            "building": "Bâtiment Annexe",
            "floor": 2,
            "has_computer_lab": True,
            "is_active": True,
        },
    )
    print("  [+] Rooms ready.")

    # 3. Level Categories & Levels
    cat_college, _ = LevelCategory.objects.get_or_create(
        name="Collège Test",
        defaults={"code": "COLLEGE-TEST"},
    )
    cat_lycee, _ = LevelCategory.objects.get_or_create(
        name="Lycée Test",
        defaults={"code": "LYCEE-TEST"},
    )

    level_3ac, _ = Level.objects.get_or_create(
        name="3ème Année Collège Test",
        defaults={"category": cat_college},
    )
    level_1bac, _ = Level.objects.get_or_create(
        name="1ère Année Bac Test",
        defaults={"category": cat_lycee},
    )
    print("  [+] Categories and Levels ready.")

    # 4. Teachers
    teacher1, _ = Teacher.objects.get_or_create(
        name="Prof. Karim Idrissi",
        defaults={
            "phone": "0612345678",
            "email": "karim.idrissi@school-test.com",
            "hourly_rate": Decimal("150.00"),
            "payment_method": TeacherPaymentMethod.HOURLY,
            "is_active": True,
        },
    )
    teacher2, _ = Teacher.objects.get_or_create(
        name="Prof. Meriem Alaoui",
        defaults={
            "phone": "0687654321",
            "email": "meriem.alaoui@school-test.com",
            "payment_percentage": Decimal("60.00"),
            "payment_method": TeacherPaymentMethod.PERCENTAGE,
            "is_active": True,
        },
    )
    # Associate test_teacher_user with teacher1
    teacher_user = User.objects.get(username="test_teacher_user")
    UserProfile.objects.update_or_create(
        user=teacher_user,
        defaults={"role": "TEACHER", "teacher": teacher1},
    )
    print("  [+] Teachers ready.")

    # 5. Teacher Availability
    TeacherAvailability.objects.get_or_create(
        teacher=teacher1,
        day="MON",
        start_time=time(8, 0),
        end_time=time(18, 0),
        defaults={"is_available": True},
    )
    TeacherAvailability.objects.get_or_create(
        teacher=teacher1,
        day="WED",
        start_time=time(8, 0),
        end_time=time(18, 0),
        defaults={"is_available": True},
    )

    # 6. Course Groups & Schedules
    today = date.today()
    cg1, _ = CourseGroup.objects.get_or_create(
        name="Mathématiques 3AC - Groupe A",
        defaults={
            "subject": "Mathématiques",
            "level": level_3ac,
            "teacher": teacher1,
            "monthly_price": Decimal("400.00"),
            "is_active": True,
        },
    )
    CourseGroupSchedule.objects.get_or_create(
        course_group=cg1,
        day="MON",
        start_time=time(14, 0),
        end_time=time(16, 0),
        defaults={"room": room1},
    )
    CourseGroupSchedule.objects.get_or_create(
        course_group=cg1,
        day="WED",
        start_time=time(14, 0),
        end_time=time(16, 0),
        defaults={"room": room1},
    )

    cg2, _ = CourseGroup.objects.get_or_create(
        name="Physique-Chimie 1BAC - Groupe B",
        defaults={
            "subject": "Physique-Chimie",
            "level": level_1bac,
            "teacher": teacher2,
            "monthly_price": Decimal("450.00"),
            "is_active": True,
        },
    )
    CourseGroupSchedule.objects.get_or_create(
        course_group=cg2,
        day="TUE",
        start_time=time(16, 0),
        end_time=time(18, 0),
        defaults={"room": room2},
    )
    print("  [+] Course Groups and Schedules ready.")

    # 7. Students & Enrollments
    students_info = [
        ("Amine Mansouri", "0600112233", "0611223344", "Mansouri Parent", level_3ac, cg1),
        ("Salma Berrada", "0622334455", "0633445566", "Berrada Parent", level_3ac, cg1),
        ("Youssef El Fassi", "0644556677", "0655667788", "El Fassi Parent", level_1bac, cg2),
        ("Nour Kabbaj", "0666778899", "0677889900", "Kabbaj Parent", level_1bac, cg2),
        ("Tariq Chraibi", "0688990011", "0699001122", "Chraibi Parent", level_3ac, None),
    ]

    for name, phone, parent_contact, parent_name, level, group in students_info:
        student, _ = Student.objects.get_or_create(
            name=name,
            defaults={
                "phone": phone,
                "parent_contact": parent_contact,
                "parent_name": parent_name,
                "level": level,
                "is_active": True,
            },
        )
        if group:
            Enrollment.objects.get_or_create(
                student=student,
                course_group=group,
                defaults={"is_active": True},
            )
    print("  [+] Students and Enrollments ready.")

    # 8. Sessions (Today and this week)
    current_monday = today - timedelta(days=today.weekday())
    for day_offset in range(7):
        session_date = current_monday + timedelta(days=day_offset)
        weekday_code = session_date.strftime("%a").upper()[:3]
        if weekday_code == "MON":
            Session.objects.get_or_create(
                group=cg1,
                date=session_date,
                start_time=time(14, 0),
                end_time=time(16, 0),
                defaults={
                    "room": room1,
                    "status": SessionStatus.PLANNED,
                },
            )
        elif weekday_code == "TUE":
            Session.objects.get_or_create(
                group=cg2,
                date=session_date,
                start_time=time(16, 0),
                end_time=time(18, 0),
                defaults={
                    "room": room2,
                    "status": SessionStatus.PLANNED,
                },
            )
        elif weekday_code == "WED":
            Session.objects.get_or_create(
                group=cg1,
                date=session_date,
                start_time=time(14, 0),
                end_time=time(16, 0),
                defaults={
                    "room": room1,
                    "status": SessionStatus.PLANNED,
                },
            )
    print("  [+] Sessions ready.")

    # 9. Payments
    stu1 = Student.objects.get(name="Amine Mansouri")
    first_of_month = today.replace(day=1)
    Payment.objects.get_or_create(
        student=stu1,
        receipt_number=f"REC-E2E-{today.strftime('%Y%m')}-001",
        defaults={
            "amount": Decimal("400.00"),
            "month_covered": first_of_month,
            "status": PaymentStatus.PAID,
            "payment_method": PaymentMethod.CASH,
            "payment_date": today,
        },
    )
    print("  [+] Payments ready.")
    print("Deterministic test database setup complete!")


if __name__ == "__main__":
    setup_test_data()
