"""
Script de génération de données de test de qualité de production pour l'école de soutien.
Usage: python manage.py shell
  In [1]: from core.fixtures import generate_fixtures; generate_fixtures()
"""
import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum, Q, Max
from django.contrib.auth.models import User
from dateutil.relativedelta import relativedelta

# Importer les modèles
from .models import (
    Room, Teacher, CourseGroup, CourseGroupSchedule,
    Student, Enrollment, Payment, Attendance, Session, Level, LevelCategory, LevelType,
    TeacherLeave, TeacherAvailability, TeacherPayment, Holiday, MakeupSession,
    WhatsAppSendLog, Announcement, ScheduleLock, SessionChangeHistory,
    TeacherPaymentMethod, TeacherPaymentType, TeacherLeaveType, PaymentStatus,
    PaymentMethod, SessionStatus
)


# ==================== DONNÉES DE LOCALISATION MAROCAINE ====================

MOROCCAN_FIRST_NAMES_MALE = [
    "Ahmed", "Mohamed", "Youssef", "Hassan", "Omar", "Karim", "Amine", "Mehdi",
    "Samir", "Rachid", "Abdelali", "Hamza", "Ismail", "Khalid", "Tariq",
    "Ayoub", "Zakaria", "Rayan", "Adam", "Ilyas", "Anass", "Saad", "Walid",
    "Reda", "Adnane", "Badr", "Imad", "Nabil", "Yassine", "Zouhair"
]

MOROCCAN_FIRST_NAMES_FEMALE = [
    "Fatima", "Aicha", "Zineb", "Salma", "Hiba", "Meriem", "Khadija", "Nour",
    "Yasmine", "Safaa", "Laila", "Amina", "Siham", "Karima", "Houda",
    "Sanaa", "Rim", "Malak", "Imane", "Dounia", "Nisrine", "Ghita", "Oumaima",
    "Chaimae", "Salma", "Kawtar", "Sara", "Noha", "Bouchra", "Wiam"
]

MOROCCAN_FIRST_NAMES = MOROCCAN_FIRST_NAMES_MALE + MOROCCAN_FIRST_NAMES_FEMALE

MOROCCAN_LAST_NAMES = [
    "Alami", "Bennani", "El Amrani", "Filali", "Idrissi", "Benjelloun", "Tazi",
    "Lazrak", "Berrada", "Skalli", "Zahiri", "Kettani", "Chraibi", "Fassi",
    "Belhaj", "Sefrioui", "Oudghiri", "Cherkaoui", "Hassani", "Bensouda",
    "El Malki", "Kadiri", "Slaoui", "Benmoussa", "El Yousfi", "Tahiri",
    "Mansouri", "Alaoui", "Jahidi", "Marrakchi"
]

MOROCCAN_SCHOOLS = [
    "Lycée Lyautey", "École Al Jabr", "Lycée Massignon", "Institution Tahar", 
    "Établissement El Yakout", "Lycée Moulay Abdellah", "Lycée Descartes", 
    "Collège Anatole France", "Groupe Scolaire Anis", "Lycée Ibn Toufail",
    "Lycée Mohammed V", "Lycée technique Jaber Ibn Hayyan", "Institution El Yakout"
]

SUBJECTS = [
    "Mathématiques", "Physique-Chimie", "SVT", "Français", "Arabe",
    "Anglais", "Philosophie", "Histoire-Géo", "Économie", "Informatique",
]

DAYS = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT']

DAY_MAP = {'MON': 0, 'TUE': 1, 'WED': 2, 'THU': 3, 'FRI': 4, 'SAT': 5, 'SUN': 6}

STANDARD_SLOTS = [
    (time(8, 30), time(10, 30)),
    (time(10, 30), time(12, 30)),
    (time(14, 0), time(16, 0)),
    (time(16, 0), time(18, 0)),
    (time(18, 0), time(20, 0)),
]


# ==================== FONCTIONS UTILITAIRES ====================

used_phones = set()

def generate_phone():
    """Génère un numéro de téléphone marocain réaliste et unique"""
    while True:
        prefix = random.choice(["06", "07"])
        digits = "".join(random.choices("0123456789", k=8))
        phone = f"{prefix}{digits}"
        if phone not in used_phones:
            used_phones.add(phone)
            return phone

def generate_full_name():
    return f"{random.choice(MOROCCAN_FIRST_NAMES)} {random.choice(MOROCCAN_LAST_NAMES)}"

def random_time(start_hour=8, end_hour=18):
    """Génère une heure de début aléatoire (heures pleines ou demi-heures)"""
    hour = random.randint(start_hour, end_hour - 1)
    minute = random.choice([0, 30])
    return time(hour, minute)

def add_hours(t, hours):
    """Ajoute des heures à un objet time, plafonné à 21h00."""
    total_minutes = t.hour * 60 + t.minute + int(hours * 60)
    total_minutes = min(total_minutes, 21 * 60)
    return time(total_minutes // 60, total_minutes % 60)

def times_overlap(s1, e1, s2, e2):
    """Renvoie True si les deux créneaux horaires se chevauchent."""
    return s1 < e2 and e1 > s2

def overlaps(start_a, end_a, start_b, end_b):
    """Version alias de times_overlap pour compatibilité avec models.py"""
    return times_overlap(start_a, end_a, start_b, end_b)

def find_free_schedule_slot(teacher_id, rooms, room_busy, teacher_busy, excluded_days=None):
    """Recherche un créneau hebdomadaire sans conflit pour la salle et le professeur"""
    days = list(DAYS)
    if excluded_days:
        days = [d for d in days if d not in excluded_days]
        
    random.shuffle(days)
    shuffled_rooms = list(rooms)
    random.shuffle(shuffled_rooms)
    
    slot_indices = list(range(len(STANDARD_SLOTS)))
    random.shuffle(slot_indices)
    
    for day in days:
        for room in shuffled_rooms:
            for slot_idx in slot_indices:
                r_key = (room.id, day, slot_idx)
                t_key = (teacher_id, day, slot_idx)
                if r_key not in room_busy and t_key not in teacher_busy:
                    return day, slot_idx, room
    return None, None, None


# Unique fields generators with set-based validation to bypass N+1 DB lookups
used_matricules = set()
def generate_unique_matricule(year):
    prefix = f"M{year % 100:02d}-"
    num = len(used_matricules) + 1
    while True:
        candidate = f"{prefix}{num:03d}"
        if candidate not in used_matricules:
            used_matricules.add(candidate)
            return candidate
        num += 1

used_receipts = set()
def generate_unique_receipt(year):
    prefix = f"REC{year}"
    num = len(used_receipts) + 1
    while True:
        candidate = f"{prefix}{num:04d}"
        if candidate not in used_receipts:
            used_receipts.add(candidate)
            return candidate
        num += 1


# ==================== FONCTION PRINCIPALE ====================

@transaction.atomic
def generate_fixtures(
    num_rooms=6,
    num_teachers=12,
    num_courses=25,
    num_students=100,
    months_history=12,
    months_future=3,
    generate_payments=True,
    generate_attendance=True,
    generate_teacher_payments=True,
    generate_holidays=True,
    generate_leaves=True,
    generate_announcements=True,
    generate_logs=True,
):
    """
    Génère un jeu complet de données de test de qualité de production.
    Passe par l'in-memory validation pour être ultra-rapide et sans conflits.
    """
    
    # Réinitialisation des générateurs uniques
    used_phones.clear()
    used_matricules.clear()
    used_receipts.clear()

    print("[*] Suppression des anciennes données...")
    SessionChangeHistory.objects.all().delete()
    MakeupSession.objects.all().delete()
    Attendance.objects.all().delete()
    WhatsAppSendLog.objects.all().delete()
    Payment.objects.all().delete()
    TeacherPayment.objects.all().delete()
    TeacherLeave.objects.all().delete()
    TeacherAvailability.objects.all().delete()
    Session.objects.all().delete()
    Enrollment.objects.all().delete()
    CourseGroupSchedule.objects.all().delete()
    Holiday.objects.all().delete()
    Announcement.objects.all().delete()
    ScheduleLock.objects.all().delete()
    CourseGroup.objects.all().delete()
    Student.objects.all().delete()
    Level.objects.all().delete()
    LevelCategory.objects.all().delete()
    Teacher.objects.all().delete()
    Room.objects.all().delete()

    print("\n" + "=" * 50)
    print("GÉNÉRATION DES DONNÉES DE TEST DE QUALITÉ PRODUCTION")
    print("=" * 50 + "\n")

    # ==================== 1. UTILISATEUR DE BASE ====================
    user = User.objects.filter(is_superuser=True).first() or User.objects.first()
    if not user:
        user = User.objects.create_superuser(
            username='admin',
            email='admin@schoolerp.ma',
            password='adminpassword'
        )

    # ==================== 2. SALLES ====================
    print(f"[+] Création de {num_rooms} salles...")
    rooms = []
    for i in range(1, num_rooms + 1):
        r = Room(name=f"Salle {i}", capacity=random.randint(15, 30), is_active=True)
        r.full_clean()
        rooms.append(r)
    Room.objects.bulk_create(rooms)
    rooms = list(Room.objects.all())

    # ==================== 3. CATÉGORIES & NIVEAUX ====================
    print("[+] Création des catégories académiques et non-académiques et des niveaux...")
    CATEGORIES = [
        # Académiques
        ('GARDERIE', 'La Garderie', True),
        ('PRIMAIRE', 'Primaire', True),
        ('COLLEGE', 'Collège', True),
        ('LYCEE', 'Lycée', True),
        # Non-académiques
        ('LANGUES', 'Langues & Communication', False),
        ('PARASCOLAIRE', 'Parascolaire & Activités', False),
        ('SOUTIEN_LIBRE', 'Formation & Soutien Libre', False),
    ]
    category_map = {}
    for code, name, is_acad in CATEGORIES:
        cat = LevelCategory(code=code, name=name, is_academic=is_acad)
        cat.full_clean()
        cat.save()
        category_map[code] = cat

    ACADEMIC_LEVELS_DATA = [
        ('Petite Section (PS)', 'GARDERIE', 1),
        ('Moyenne Section (MS)', 'GARDERIE', 2),
        ('Grande Section (GS)', 'GARDERIE', 3),
        ('1AP', 'PRIMAIRE', 4),
        ('2AP', 'PRIMAIRE', 5),
        ('3AP', 'PRIMAIRE', 6),
        ('4AP', 'PRIMAIRE', 7),
        ('5AP', 'PRIMAIRE', 8),
        ('6AP', 'PRIMAIRE', 9),
        ('1ASC', 'COLLEGE', 10),
        ('2ASC', 'COLLEGE', 11),
        ('3ASC', 'COLLEGE', 12),
        ('Tronc Commun (TC)', 'LYCEE', 13),
        ('1ère année Bac (1Bac)', 'LYCEE', 14),
        ('2ème année Bac (2Bac)', 'LYCEE', 15),
    ]
    academic_objs = []
    for name, cat_code, ord_num in ACADEMIC_LEVELS_DATA:
        lvl = Level(name=name, category=category_map[cat_code], level_type=LevelType.ACADEMIC, order=ord_num)
        lvl.full_clean()
        lvl.save()
        academic_objs.append(lvl)

    # Chainer les niveaux académiques consécutifs
    for i in range(len(academic_objs) - 1):
        academic_objs[i].next_level = academic_objs[i + 1]
        academic_objs[i].save(update_fields=['next_level'])

    NON_ACADEMIC_LEVELS_DATA = [
        ('A1 - Débutant', 'LANGUES', 1),
        ('A2 - Élémentaire', 'LANGUES', 2),
        ('B1 - Intermédiaire', 'LANGUES', 3),
        ('B2 - Avancé', 'LANGUES', 4),
        ('C1 - Expert', 'LANGUES', 5),
        ('Business English', 'LANGUES', 6),
        ('Club Robotique & IA', 'PARASCOLAIRE', 1),
        ('Club Échecs', 'PARASCOLAIRE', 2),
        ('Atelier Théâtre & Éloquence', 'PARASCOLAIRE', 3),
        ('Remise à niveau continue', 'SOUTIEN_LIBRE', 1),
        ('Préparation Concours', 'SOUTIEN_LIBRE', 2),
    ]
    for name, cat_code, ord_num in NON_ACADEMIC_LEVELS_DATA:
        lvl = Level(name=name, category=category_map[cat_code], level_type=LevelType.NON_ACADEMIC, order=ord_num)
        lvl.full_clean()
        lvl.save()

    db_levels = list(Level.objects.all())
    academic_db_levels = list(Level.objects.filter(level_type=LevelType.ACADEMIC))

    # ==================== 4. PROFESSEURS ====================
    print(f"[+] Création de {num_teachers} professeurs...")
    teachers_to_create = []
    num_teachers = max(num_teachers, 3)  # Au moins 3 pour couvrir les scénarios
    
    for idx in range(num_teachers):
        is_active = (idx != 0)  # Le premier professeur est inactif
        name = generate_full_name()
        phone = generate_phone()
        email = f"teacher{idx}_{random.randint(100, 999)}@schoolerp.ma"
        
        # Choix de la méthode de rémunération
        method = random.choice(['PERCENTAGE', 'HOURLY', 'SESSION'])
        if method == 'HOURLY':
            hourly_rate = Decimal(random.choice(['80.00', '100.00', '120.00', '150.00']))
            payment_percentage = None
            session_rate = None
        elif method == 'PERCENTAGE':
            hourly_rate = None
            payment_percentage = Decimal(random.choice(['40.00', '50.00', '60.00']))
            session_rate = None
        else:
            hourly_rate = None
            payment_percentage = None
            session_rate = Decimal(random.choice(['100.00', '120.00', '150.00']))
            
        t = Teacher(
            name=name,
            phone=phone,
            email=email,
            hourly_rate=hourly_rate,
            payment_method=method,
            payment_percentage=payment_percentage,
            session_rate=session_rate,
            is_active=is_active
        )
        t.full_clean()
        teachers_to_create.append(t)
        
    Teacher.objects.bulk_create(teachers_to_create)
    teachers = list(Teacher.objects.all())
    
    active_teachers = [t for t in teachers if t.is_active]
    
    # Partitionner les professeurs : 1 inactif, 1 actif sans groupes, les autres avec groupes
    teacher_no_groups = active_teachers[0]
    teachers_for_groups = active_teachers[1:]

    # ==================== 5. CONGÉS DES ENSEIGNANTS ====================
    teacher_leaves_map = {} # teacher_id -> list of (start_date, end_date)
    if generate_leaves:
        print("[+] Génération des congés professeurs...")
        leave_objs = []
        # 70% des profs prennent des congés
        teachers_with_leaves = random.sample(teachers, int(len(teachers) * 0.7))
        today = timezone.now().date()
        
        for t in teachers_with_leaves:
            num_leaves = random.randint(1, 2)
            teacher_leaves_map[t.id] = []
            
            for _ in range(num_leaves):
                offset_days = random.randint(-180, 90)
                start_date = today + timedelta(days=offset_days)
                duration = random.randint(1, 5)
                end_date = start_date + timedelta(days=duration)
                
                leave = TeacherLeave(
                    teacher=t,
                    start_date=start_date,
                    end_date=end_date,
                    leave_type=random.choice(['SICK', 'VACATION', 'OTHER']),
                    notes=random.choice(["Certificat médical", "Voyage", "Affaires personnelles", ""])
                )
                leave.full_clean()
                leave_objs.append(leave)
                teacher_leaves_map[t.id].append((start_date, end_date))
                
        TeacherLeave.objects.bulk_create(leave_objs)

    # ==================== 6. HORAIRES & GROUPES DE COURS ====================
    print(f"[+] Création de {num_courses} groupes de cours et plannings hebdomadaires...")
    courses = []
    course_schedule_objs = []
    
    room_busy = set() # (room_id, day, slot_index)
    teacher_busy = set() # (teacher_id, day, slot_index)
    
    # 10% des groupes de cours inactifs
    num_inactive_courses = max(1, num_courses // 10)
    
    for idx in range(num_courses):
        teacher = random.choice(teachers_for_groups)
        subject = random.choice(SUBJECTS)
        level = random.choice(db_levels)
        price = Decimal(random.choice(['300.00', '350.00', '400.00', '450.00', '500.00', '600.00']))
        is_active = (idx >= num_inactive_courses)
        
        # 1 ou 2 séances hebdomadaires
        num_sessions = random.choices([1, 2], weights=[0.7, 0.3])[0]
        
        course = CourseGroup(
            name=f"{subject} - {level.name} (G{idx+1})",
            subject=subject,
            level=level,
            monthly_price=price,
            teacher=teacher,
            is_active=is_active,
            whatsapp_group_link=f"https://chat.whatsapp.com/mockgroup{idx}" if random.random() > 0.4 else None
        )
        
        # Sauvegarde directe pour bypasser les signaux
        from django.db.models import Model as _BaseModel
        _BaseModel.save(course)
        # Assigner les niveaux au groupe (dont ~35% avec multi-niveaux)
        if level.next_level and random.random() < 0.35:
            course.levels.set([level, level.next_level])
        else:
            course.levels.set([level])
        courses.append(course)
        
        first_day = None
        for sess_idx in range(num_sessions):
            excluded = [first_day] if first_day else None
            day, slot_idx, room = find_free_schedule_slot(
                teacher.id, rooms, room_busy, teacher_busy, excluded_days=excluded
            )
            
            if not day:
                continue
                
            if sess_idx == 0:
                first_day = day
                
            room_busy.add((room.id, day, slot_idx))
            teacher_busy.add((teacher.id, day, slot_idx))
            
            start_time, end_time = STANDARD_SLOTS[slot_idx]
            
            sch = CourseGroupSchedule(
                course_group=course,
                day=day,
                start_time=start_time,
                end_time=end_time,
                room=room
            )
            sch.full_clean()
            course_schedule_objs.append(sch)
            
    CourseGroupSchedule.objects.bulk_create(course_schedule_objs)
    schedules = list(CourseGroupSchedule.objects.all())

    # ==================== 7. DISPONIBILITÉS ENSEIGNANTS ====================
    print("[+] Génération des disponibilités hebdomadaires des professeurs...")
    avail_objs = []
    teachers_with_avail = random.sample(teachers, int(len(teachers) * 0.7))
    
    teacher_schedules = {}
    for sch in schedules:
        teacher_schedules.setdefault(sch.course_group.teacher_id, []).append(sch)
        
    for t in teachers_with_avail:
        t_schs = teacher_schedules.get(t.id, [])
        class_days = set(sch.day for sch in t_schs)
        
        # Disponibilités alignées sur leurs cours
        for day in class_days:
            avail_objs.append(TeacherAvailability(
                teacher=t,
                day=day,
                start_time=time(8, 0),
                end_time=time(20, 0),
                is_available=True
            ))
            
        # Indisponibilités les autres jours
        non_class_days = [d for d in DAYS if d not in class_days]
        if non_class_days:
            unavail_day = random.choice(non_class_days)
            avail_objs.append(TeacherAvailability(
                teacher=t,
                day=unavail_day,
                start_time=time(14, 0),
                end_time=time(18, 0),
                is_available=False
            ))
            
    for av in avail_objs:
        av.full_clean()
    TeacherAvailability.objects.bulk_create(avail_objs)

    # ==================== 8. JOURS FÉRIÉS ====================
    global_holidays = set()
    group_holidays = set() # (date, course_group_id)
    holiday_objs = []
    holiday_m2m_links = []
    
    if generate_holidays:
        print("[+] Génération des jours fériés et vacances scolaires...")
        today = timezone.now().date()
        
        holiday_names = [
            ("Nouvel An", -170),
            ("Manifestation de l'Indépendance", -140),
            ("Aïd al-Fitr", -60),
            ("Fête du Travail", -30),
            ("Aïd al-Adha", 15),
            ("Fête du Trône", 45),
            ("1er Moharram", 75)
        ]
        
        for name, offset in holiday_names:
            h_date = today + timedelta(days=offset)
            affects_all = random.choice([True, True, False])
            
            hol = Holiday(
                name=name,
                date=h_date,
                affects_all=affects_all,
                notes="Généré automatiquement par le script de test."
            )
            hol.full_clean()
            holiday_objs.append(hol)
            
            if affects_all:
                global_holidays.add(h_date)
            else:
                affected_c = random.sample(courses, min(len(courses), random.randint(2, 5)))
                for c in affected_c:
                    group_holidays.add((h_date, c.id))
                holiday_m2m_links.append((hol, affected_c))
                
        Holiday.objects.bulk_create(holiday_objs)
        
        # Lier le ManyToMany
        db_holidays = {h.date: h for h in Holiday.objects.all()}
        through_objs = []
        for hol_date, affected_c in [(h.date, cs) for h, cs in holiday_m2m_links]:
            db_hol = db_holidays[hol_date]
            for c in affected_c:
                through_objs.append(Holiday.affected_groups.through(holiday_id=db_hol.id, coursegroup_id=c.id))
        Holiday.affected_groups.through.objects.bulk_create(through_objs)

    # ==================== 9. ÉLÈVES ====================
    print(f"[+] Création de {num_students} élèves...")
    student_objs = []
    num_inactive_students = max(1, num_students // 10)
    year_prefix = timezone.now().strftime('%y')
    
    for idx in range(num_students):
        is_active = (idx >= num_inactive_students)
        name = generate_full_name()
        phone = generate_phone()
        parent_contact = generate_phone()
        parent_contact_2 = generate_phone() if random.random() > 0.6 else ""
        parent_name = generate_full_name()
        address = f"{random.randint(1, 200)} Boulevard Zerktouni, Casablanca"
        date_of_birth = date(random.randint(2005, 2018), random.randint(1, 12), random.randint(1, 28))
        # 80% des élèves en niveau académique, 20% en parascolaire/langues
        if random.random() < 0.8 and academic_db_levels:
            level = random.choice(academic_db_levels)
        else:
            level = random.choice(db_levels)
        main_school = random.choice(MOROCCAN_SCHOOLS)
        
        matricule = generate_unique_matricule(int(year_prefix))
        
        stud = Student(
            matricule=matricule,
            name=name,
            phone=phone,
            parent_contact=parent_contact,
            parent_contact_2=parent_contact_2,
            parent_name=parent_name,
            address=address,
            date_of_birth=date_of_birth,
            level=level,
            main_school=main_school,
            is_active=is_active,
            notes=random.choice(["", "", "Excellent élève", "Difficultés en calcul"])
        )
        stud.full_clean()
        student_objs.append(stud)
        
    Student.objects.bulk_create(student_objs)
    students = list(Student.objects.all())

    # ==================== 10. INSCRIPTIONS (ENROLLMENTS) ====================
    print("[+] Génération des inscriptions...")
    enrollment_objs = []
    student_busy_slots = {}
    
    course_schedules_map = {}
    for sch in schedules:
        slot_idx = -1
        for idx, (st, et) in enumerate(STANDARD_SLOTS):
            if sch.start_time == st and sch.end_time == et:
                slot_idx = idx
                break
        course_schedules_map.setdefault(sch.course_group_id, []).append((sch.day, slot_idx))
        
    active_students = [s for s in students if s.is_active]
    inactive_students = [s for s in students if not s.is_active]
    random.shuffle(active_students)
    
    num_active = len(active_students)
    num_zero = int(num_active * 0.10)
    num_one = int(num_active * 0.40)
    num_two = int(num_active * 0.25)
    num_three = int(num_active * 0.15)
    
    student_enroll_counts = (
        [(s, 0) for s in active_students[:num_zero]] +
        [(s, 1) for s in active_students[num_zero:num_zero+num_one]] +
        [(s, 2) for s in active_students[num_zero+num_one:num_zero+num_one+num_two]] +
        [(s, 3) for s in active_students[num_zero+num_one+num_two:num_zero+num_one+num_two+num_three]] +
        [(s, 4) for s in active_students[num_zero+num_one+num_two+num_three:]]
    )
    
    for s in inactive_students:
        student_enroll_counts.append((s, random.randint(1, 2)))
        
    active_courses = [c for c in courses if c.is_active]
    
    for student, target_count in student_enroll_counts:
        if target_count == 0 or not active_courses:
            continue
            
        student_busy_slots[student.id] = set()
        enrolled_count = 0
        
        candidates = random.sample(active_courses, min(len(active_courses), target_count + 5))
        for course in candidates:
            if enrolled_count >= target_count:
                break
                
            c_slots = course_schedules_map.get(course.id, [])
            conflict = False
            for day, slot_idx in c_slots:
                if (day, slot_idx) in student_busy_slots[student.id]:
                    conflict = True
                    break
                    
            if not conflict:
                for day, slot_idx in c_slots:
                    student_busy_slots[student.id].add((day, slot_idx))
                    
                enrolled_date = today - timedelta(days=random.randint(15, 90))
                enr = Enrollment(
                    student=student,
                    course_group=course,
                    enrolled_date=enrolled_date,
                    is_active=student.is_active,
                    next_payment_date=today + timedelta(days=30)
                )
                enr.full_clean()
                enrollment_objs.append(enr)
                enrolled_count += 1
                
    Enrollment.objects.bulk_create(enrollment_objs)

    # ==================== 11. SÉANCES (SESSIONS) ====================
    print("[+] Génération de l'historique (6 mois) et prévisions (3 mois) de séances...")
    session_objs = []
    
    start_date = today - timedelta(days=180)
    end_date = today + timedelta(days=90)
    DAY_MAP_REV = {0: 'MON', 1: 'TUE', 2: 'WED', 3: 'THU', 4: 'FRI', 5: 'SAT', 6: 'SUN'}
    
    for course in courses:
        c_schs = [sch for sch in schedules if sch.course_group_id == course.id]
        for sch in c_schs:
            target_day_code = sch.day
            target_weekday = -1
            for k, v in DAY_MAP_REV.items():
                if v == target_day_code:
                    target_weekday = k
                    break
                    
            current_date = start_date
            while current_date <= end_date:
                if current_date.weekday() == target_weekday:
                    is_cancelled = False
                    cancel_reason = ""
                    
                    if current_date in global_holidays:
                        is_cancelled = True
                        cancel_reason = "Jour férié national"
                    elif (current_date, course.id) in group_holidays:
                        is_cancelled = True
                        cancel_reason = "Vacances spécifiques"
                        
                    t_leaves = teacher_leaves_map.get(course.teacher_id, [])
                    for l_start, l_end in t_leaves:
                        if l_start <= current_date <= l_end:
                            is_cancelled = True
                            cancel_reason = "Congé enseignant"
                            break
                            
                    if is_cancelled:
                        status = 'CANCELLED'
                        notes = cancel_reason
                    elif current_date < today:
                        status = 'DONE' if random.random() > 0.05 else 'CANCELLED'
                        notes = "Séance complétée" if status == 'DONE' else "Annulée par l'enseignant"
                    else:
                        status = 'PLANNED'
                        notes = "Séance planifiée"
                        
                    sess = Session(
                        group=course,
                        schedule=sch,
                        date=current_date,
                        start_time=sch.start_time,
                        end_time=sch.end_time,
                        room=sch.room,
                        status=status,
                        notes=notes,
                        is_manually_edited=False
                    )
                    session_objs.append(sess)
                current_date += timedelta(days=1)
                
    Session.objects.bulk_create(session_objs)
    db_sessions = list(Session.objects.all())

    # ==================== 12. SÉANCES EXCEPTIONNELLES ====================
    print("[+] Mutation d'un petit pourcentage de séances exceptionnelles...")
    active_rooms = [r for r in rooms if r.is_active]
    active_teachers = [t for t in teachers if t.is_active]
    
    sessions_by_date = {}
    for s in db_sessions:
        sessions_by_date.setdefault(s.date, []).append(s)
        
    num_mutations = max(5, len(db_sessions) // 20)  # 5%
    sessions_to_mutate = random.sample(db_sessions, min(len(db_sessions), num_mutations))
    
    sessions_to_update = []
    for s in sessions_to_mutate:
        if s.status == 'CANCELLED' and random.random() > 0.2:
            continue
            
        mutation_type = random.choice(['SUBSTITUTE', 'ROOM', 'TIME', 'CANCEL', 'MANUAL_ONLY'])
        day_sessions = sessions_by_date.get(s.date, [])
        
        if mutation_type == 'SUBSTITUTE':
            other_teachers = [t for t in active_teachers if t.id != s.group.teacher_id]
            random.shuffle(other_teachers)
            chosen_sub = None
            for t in other_teachers:
                conflict = False
                for os in day_sessions:
                    if os.id == s.id or os.status == 'CANCELLED':
                        continue
                    os_teacher = os.substitute_teacher or os.group.teacher
                    if os_teacher.id == t.id and overlaps(s.start_time, s.end_time, os.start_time, os.end_time):
                        conflict = True
                        break
                if not conflict:
                    chosen_sub = t
                    break
            if chosen_sub:
                s.substitute_teacher = chosen_sub
                s.is_manually_edited = True
                s.notes = f"Professeur remplaçant: {chosen_sub.name}"
                sessions_to_update.append(s)
                
        elif mutation_type == 'ROOM':
            other_rooms = [r for r in active_rooms if r.id != s.room_id]
            random.shuffle(other_rooms)
            chosen_room = None
            for r in other_rooms:
                conflict = False
                for os in day_sessions:
                    if os.id == s.id or os.status == 'CANCELLED':
                        continue
                    if os.room_id == r.id and overlaps(s.start_time, s.end_time, os.start_time, os.end_time):
                        conflict = True
                        break
                if not conflict:
                    chosen_room = r
                    break
            if chosen_room:
                s.room = chosen_room
                s.is_manually_edited = True
                s.notes = f"Changement de salle vers {chosen_room.name}"
                sessions_to_update.append(s)
                
        elif mutation_type == 'TIME':
            new_start = add_hours(s.start_time, 0.5)
            new_end = add_hours(s.end_time, 0.5)
            
            conflict = False
            effective_teacher = s.substitute_teacher or s.group.teacher
            for os in day_sessions:
                if os.id == s.id or os.status == 'CANCELLED':
                    continue
                if os.room_id == s.room_id and overlaps(new_start, new_end, os.start_time, os.end_time):
                    conflict = True
                    break
                os_teacher = os.substitute_teacher or os.group.teacher
                if os_teacher.id == effective_teacher.id and overlaps(new_start, new_end, os.start_time, os.end_time):
                    conflict = True
                    break
            if not conflict:
                s.start_time = new_start
                s.end_time = new_end
                s.is_manually_edited = True
                s.notes = "Séance décalée de 30 min"
                sessions_to_update.append(s)
                
        elif mutation_type == 'CANCEL':
            s.status = 'CANCELLED'
            s.is_manually_edited = True
            s.notes = "Séance annulée par l'administration"
            sessions_to_update.append(s)
            
        else:
            s.is_manually_edited = True
            s.notes = "Modification administrative manuelle"
            sessions_to_update.append(s)
            
    Session.objects.bulk_update(sessions_to_update, ['substitute_teacher', 'room', 'start_time', 'end_time', 'status', 'is_manually_edited', 'notes'])

    # ==================== 13. SÉANCES DE RATTRAPAGE ====================
    print("[+] Génération des séances de rattrapage (MakeupSessions)...")
    cancelled_sessions = [s for s in db_sessions if s.status == 'CANCELLED']
    num_makeups = max(1, len(cancelled_sessions) // 5)
    sessions_to_makeup = random.sample(cancelled_sessions, min(len(cancelled_sessions), num_makeups))
    
    new_makeup_sessions = []
    for s in sessions_to_makeup:
        chosen_date = None
        chosen_slot_idx = None
        chosen_room = None
        found = False
        
        for offset in range(2, 10):
            candidate_date = s.date + timedelta(days=offset)
            day_sessions = sessions_by_date.get(candidate_date, [])
            
            shuffled_rooms = list(active_rooms)
            random.shuffle(shuffled_rooms)
            slot_indices = list(range(len(STANDARD_SLOTS)))
            random.shuffle(slot_indices)
            
            for r in shuffled_rooms:
                for s_idx in slot_indices:
                    st, et = STANDARD_SLOTS[s_idx]
                    conflict = False
                    for os in day_sessions:
                        if os.status == 'CANCELLED':
                            continue
                        if os.room_id == r.id and overlaps(st, et, os.start_time, os.end_time):
                            conflict = True
                            break
                        os_teacher = os.substitute_teacher or os.group.teacher
                        if os_teacher.id == s.group.teacher_id and overlaps(st, et, os.start_time, os.end_time):
                            conflict = True
                            break
                    if not conflict:
                        chosen_date = candidate_date
                        chosen_slot_idx = s_idx
                        chosen_room = r
                        found = True
                        break
                if found:
                    break
            if found:
                break
                
        if found:
            st, et = STANDARD_SLOTS[chosen_slot_idx]
            m_status = 'DONE' if chosen_date < today else 'PLANNED'
            
            makeup_sess = Session(
                group=s.group,
                schedule=s.schedule,
                date=chosen_date,
                start_time=st,
                end_time=et,
                room=chosen_room,
                status=m_status,
                notes=f"Rattrapage automatique du {s.date.strftime('%d/%m/%Y')}",
                is_manually_edited=True
            )
            new_makeup_sessions.append((s, makeup_sess))
            
    if new_makeup_sessions:
        Session.objects.bulk_create([ms[1] for ms in new_makeup_sessions])
        saved_makeups = list(Session.objects.filter(notes__startswith="Rattrapage automatique du"))
        
        makeup_relations = []
        for orig, ms in new_makeup_sessions:
            db_ms = None
            for sm in saved_makeups:
                if sm.group_id == orig.group_id and sm.date == ms.date and sm.start_time == ms.start_time:
                    db_ms = sm
                    break
            if db_ms:
                m_obj = MakeupSession(
                    original_session=orig,
                    makeup_session=db_ms,
                    notes=f"Rattrapage lié"
                )
                makeup_relation_students = list(Student.objects.filter(enrollments=orig.group, is_active=True))
                makeup_relations.append((m_obj, makeup_relation_students))
                
        MakeupSession.objects.bulk_create([mr[0] for mr in makeup_relations])
        
        db_makeup_objs = list(MakeupSession.objects.all())
        m2m_throughs = []
        for db_mo, students_to_link in zip(db_makeup_objs, [mr[1] for mr in makeup_relations]):
            for student in students_to_link:
                m2m_throughs.append(MakeupSession.students.through(makeupsession_id=db_mo.id, student_id=student.id))
        MakeupSession.students.through.objects.bulk_create(m2m_throughs)

    # ==================== 14. FEUILLES DE PRÉSENCE (ATTENDANCE) ====================
    if generate_attendance:
        print("[+] Génération des fiches de présence...")
        attendance_objs = []
        done_sessions = Session.objects.filter(status='DONE').select_related('group')
        
        enrollments_by_group = {}
        for enr in Enrollment.objects.filter(is_active=True).select_related('student'):
            enrollments_by_group.setdefault(enr.course_group_id, []).append(enr.student)
            
        seen_attendance = set()
        for s in done_sessions:
            students_in_group = enrollments_by_group.get(s.group_id, [])
            for student in students_in_group:
                key = (student.id, s.group_id, s.date)
                if key in seen_attendance:
                    continue
                seen_attendance.add(key)
                
                is_present = random.random() < 0.90
                note = ""
                if not is_present:
                    note = random.choice(["Absent", "Malade", "Retard", "", "Non justifié"])
                    
                attendance_objs.append(Attendance(
                    student=student,
                    course_group=s.group,
                    session=s,
                    date=s.date,
                    is_present=is_present,
                    notes=note
                ))
        Attendance.objects.bulk_create(attendance_objs)

    # ==================== 15. PAIEMENTS DES ÉLÈVES (HISTORIQUE 12 MOIS) ====================
    if generate_payments:
        print(f"[+] Génération de {months_history} mois d'historique de paiements élèves...")
        payment_objs = []
        student_fees = {s: s.total_monthly_fees() for s in students if s.total_monthly_fees() > 0}
        
        base_month = today.replace(day=1)
        
        for month_offset in range(months_history):
            target_month = base_month - relativedelta(months=month_offset)
            year = target_month.year
            
            for student, fees in student_fees.items():
                scenario = random.choices(
                    ['full', 'partial', 'multiple', 'late', 'missed', 'overpayment'],
                    weights=[0.75, 0.08, 0.04, 0.06, 0.06, 0.01]
                )[0]
                
                if scenario == 'missed':
                    continue
                    
                pay_method = random.choice(['CASH', 'TRANSFER', 'CHECK'])
                
                if scenario == 'full':
                    pay_date = target_month + timedelta(days=random.randint(1, 10))
                    payment_objs.append(Payment(
                        student=student,
                        amount=fees,
                        payment_date=pay_date,
                        month_covered=target_month,
                        status='PAID',
                        payment_method=pay_method,
                        receipt_number=generate_unique_receipt(year),
                        notes="",
                        is_locked=(month_offset >= 2)
                    ))
                    
                elif scenario == 'partial':
                    pay_date = target_month + timedelta(days=random.randint(1, 10))
                    amount = (fees * Decimal(random.choice(['0.5', '0.6', '0.7', '0.8']))).quantize(Decimal('0.01'))
                    payment_objs.append(Payment(
                        student=student,
                        amount=amount,
                        payment_date=pay_date,
                        month_covered=target_month,
                        status='PAID',
                        payment_method=pay_method,
                        receipt_number=generate_unique_receipt(year),
                        notes="Paiement partiel",
                        is_locked=(month_offset >= 2)
                    ))
                    
                elif scenario == 'multiple':
                    pay_date1 = target_month + timedelta(days=random.randint(1, 5))
                    pay_date2 = target_month + timedelta(days=random.randint(15, 25))
                    amount1 = (fees * Decimal('0.5')).quantize(Decimal('0.01'))
                    amount2 = fees - amount1
                    
                    payment_objs.append(Payment(
                        student=student,
                        amount=amount1,
                        payment_date=pay_date1,
                        month_covered=target_month,
                        status='PAID',
                        payment_method=pay_method,
                        receipt_number=generate_unique_receipt(year),
                        notes="Acompte",
                        is_locked=(month_offset >= 2)
                    ))
                    payment_objs.append(Payment(
                        student=student,
                        amount=amount2,
                        payment_date=pay_date2,
                        month_covered=target_month,
                        status='PAID',
                        payment_method=pay_method,
                        receipt_number=generate_unique_receipt(year),
                        notes="Solde",
                        is_locked=(month_offset >= 2)
                    ))
                    
                elif scenario == 'late':
                    pay_date = target_month + timedelta(days=random.randint(20, 28))
                    payment_objs.append(Payment(
                        student=student,
                        amount=fees,
                        payment_date=pay_date,
                        month_covered=target_month,
                        status='PAID',
                        payment_method=pay_method,
                        receipt_number=generate_unique_receipt(year),
                        notes="Paiement en retard",
                        is_locked=(month_offset >= 2)
                    ))
                    
                elif scenario == 'overpayment':
                    pay_date = target_month + timedelta(days=random.randint(1, 10))
                    amount = fees + Decimal(random.choice(['50.00', '100.00']))
                    payment_objs.append(Payment(
                        student=student,
                        amount=amount,
                        payment_date=pay_date,
                        month_covered=target_month,
                        status='PAID',
                        payment_method=pay_method,
                        receipt_number=generate_unique_receipt(year),
                        notes="Trop-perçu reporté",
                        is_locked=(month_offset >= 2)
                    ))
                    
        Payment.objects.bulk_create(payment_objs)

    # ==================== 16. PAIEMENTS ENSEIGNANTS ====================
    if generate_teacher_payments:
        print("[+] Génération des règlements salariaux des professeurs...")
        teacher_payment_objs = []
        base_month = today.replace(day=1)
        
        for month_offset in range(months_history):
            target_month = base_month - relativedelta(months=month_offset)
            year = target_month.year
            month = target_month.month
            
            for t in teachers:
                if not t.is_active:
                    continue
                    
                scenario = random.choices(['salary', 'salary_advance', 'adjustment', 'none'], weights=[0.7, 0.15, 0.05, 0.1])[0]
                if scenario == 'none':
                    continue
                    
                pay_date = target_month + timedelta(days=random.randint(25, 28))
                pay_method = random.choice(['CASH', 'TRANSFER', 'CHECK'])
                base_salary = Decimal(f"{2500 + (t.id * 200) % 3500}.00")
                
                if scenario == 'salary':
                    teacher_payment_objs.append(TeacherPayment(
                        teacher=t,
                        amount=base_salary,
                        payment_date=pay_date,
                        payment_method=pay_method,
                        payment_type='SALARY',
                        period_month=month,
                        period_year=year,
                        notes="Salaire mensuel"
                    ))
                elif scenario == 'salary_advance':
                    advance_amount = Decimal('1000.00')
                    salary_amount = base_salary - advance_amount
                    advance_date = target_month + timedelta(days=random.randint(10, 15))
                    
                    teacher_payment_objs.append(TeacherPayment(
                        teacher=t,
                        amount=advance_amount,
                        payment_date=advance_date,
                        payment_method='CASH',
                        payment_type='ADVANCE',
                        period_month=month,
                        period_year=year,
                        notes="Avance sur salaire"
                    ))
                    teacher_payment_objs.append(TeacherPayment(
                        teacher=t,
                        amount=salary_amount,
                        payment_date=pay_date,
                        payment_method=pay_method,
                        payment_type='SALARY',
                        period_month=month,
                        period_year=year,
                        notes="Règlement du solde de salaire"
                    ))
                elif scenario == 'adjustment':
                    adj_amount = Decimal(random.choice(['200.00', '300.00', '500.00']))
                    teacher_payment_objs.append(TeacherPayment(
                        teacher=t,
                        amount=adj_amount,
                        payment_date=pay_date,
                        payment_method=pay_method,
                        payment_type='ADJUSTMENT',
                        period_month=month,
                        period_year=year,
                        notes="Régularisation primes/heures"
                    ))
                    
        TeacherPayment.objects.bulk_create(teacher_payment_objs)

    # ==================== 17. JOURNAUX WHATSAPP ====================
    if generate_logs:
        print("[+] Génération des journaux d'envois WhatsApp...")
        log_objs = []
        message_types = ['payment_reminder', 'payment_confirmation', 'absence_notification', 'session_reminder', 'bulk_announcement', 'other']
        
        for s in students:
            num_logs = random.randint(1, 3)
            for _ in range(num_logs):
                msg_type = random.choice(message_types)
                status = random.choices(['SENT', 'FAILED'], weights=[0.9, 0.1])[0]
                error_msg = "" if status == 'SENT' else "Erreur passerelle WhatsApp: Timeout"
                
                previews = {
                    'payment_reminder': f"Rappel de mensualité pour {s.name}.",
                    'payment_confirmation': f"Paiement enregistré pour {s.name}.",
                    'absence_notification': f"Absence constatée pour {s.name}.",
                    'session_reminder': f"Rappel: cours de {s.name} demain.",
                    'bulk_announcement': "Annonce: Fermeture de l'établissement.",
                    'other': "Contact administratif requis."
                }
                
                sent_at = timezone.now() - timedelta(days=random.randint(1, 150), hours=random.randint(1, 12))
                log = WhatsAppSendLog(
                    student=s,
                    phone=s.parent_contact,
                    message_type=msg_type,
                    message_preview=previews[msg_type],
                    status=status,
                    error_message=error_msg,
                    sent_at=sent_at
                )
                log_objs.append(log)
                
        WhatsAppSendLog.objects.bulk_create(log_objs)

    # ==================== 18. ANNONCES DE L'ÉCOLE ====================
    if generate_announcements:
        print("[+] Génération des annonces et événements...")
        ann_objs = []
        announcements_data = [
            ("Rentrée Scolaire 2026", "L'école souhaite une excellente rentrée scolaire à tous les élèves.", "general", None),
            ("Fermeture administrative", "Nos bureaux seront fermés pendant la fête nationale.", "general", None),
            ("Réunion de cadrage", "Réunion avec l'ensemble des parents d'élèves.", "event", today + timedelta(days=7)),
            ("Atelier d'orientation", "Session d'orientation post-bac pour les lycéens.", "event", today + timedelta(days=14)),
            ("Session Examens Blancs", "Les examens blancs débuteront prochainement.", "event", today + timedelta(days=21)),
        ]
        
        for title, content, cat, ev_date in announcements_data:
            ann = Announcement(
                title=title,
                content=content,
                category=cat,
                event_date=ev_date,
                is_active=True,
                created_at=timezone.now() - timedelta(days=random.randint(1, 30))
            )
            ann.full_clean()
            ann_objs.append(ann)
            
        Announcement.objects.bulk_create(ann_objs)
        
        db_anns = list(Announcement.objects.all())
        level_throughs = []
        group_throughs = []
        
        for ann in db_anns:
            if random.random() > 0.4:
                targeted_lvls = random.sample(db_levels, random.randint(1, 2))
                for lvl in targeted_lvls:
                    level_throughs.append(Announcement.target_levels.through(announcement_id=ann.id, level_id=lvl.id))
            if random.random() > 0.6:
                targeted_grps = random.sample(courses, random.randint(1, 2))
                for grp in targeted_grps:
                    group_throughs.append(Announcement.target_groups.through(announcement_id=ann.id, coursegroup_id=grp.id))
                    
        Announcement.target_levels.through.objects.bulk_create(level_throughs)
        Announcement.target_groups.through.objects.bulk_create(group_throughs)

    # ==================== 19. VERROUILLAGE DE PLANNING ====================
    print("[+] Génération des enregistrements de verrouillage...")
    ScheduleLock.objects.create(
        is_locked=True,
        start_date=today - timedelta(days=30),
        end_date=today + timedelta(days=30),
        academic_year="2025/2026",
        locked_by=user,
        notes="Verrouillage mensuel"
    )
    ScheduleLock.objects.create(
        is_locked=False,
        start_date=today + timedelta(days=31),
        end_date=today + timedelta(days=60),
        academic_year="2025/2026",
        locked_by=user,
        notes="Déverrouillé"
    )

    # ==================== 20. HISTORIQUE DE MODIFICATIONS DE SÉANCES ====================
    print("[+] Génération des historiques de modifications des séances...")
    history_objs = []
    exceptional_db_sessions = [s for s in db_sessions if s.is_manually_edited]
    
    for s in random.sample(exceptional_db_sessions, min(len(exceptional_db_sessions), 15)):
        prev_vals = {}
        new_vals = {}
        action = "UPDATE"
        
        exception_type = s.get_exception_type()
        if exception_type == 'CANCELLED':
            prev_vals['status'] = 'PLANNED'
            new_vals['status'] = 'CANCELLED'
            reason = "Séance annulée."
        elif exception_type == 'SUBSTITUTE':
            prev_vals['substitute_teacher_id'] = None
            new_vals['substitute_teacher_id'] = s.substitute_teacher_id
            reason = "Professeur indisponible."
        elif exception_type == 'ROOM':
            prev_vals['room_id'] = s.schedule.room_id if s.schedule else None
            new_vals['room_id'] = s.room_id
            reason = "Salle occupée."
        elif exception_type == 'TIME':
            prev_vals['start_time'] = s.schedule.start_time.strftime('%H:%M:%S') if s.schedule else "14:00:00"
            prev_vals['end_time'] = s.schedule.end_time.strftime('%H:%M:%S') if s.schedule else "16:00:00"
            new_vals['start_time'] = s.start_time.strftime('%H:%M:%S')
            new_vals['end_time'] = s.end_time.strftime('%H:%M:%S')
            reason = "Ajustement horaire."
        else:
            prev_vals['notes'] = ""
            new_vals['notes'] = s.notes
            reason = "Mise à jour."
            
        history_objs.append(SessionChangeHistory(
            session=s,
            user=user,
            timestamp=timezone.now() - timedelta(days=random.randint(1, 10)),
            previous_values=prev_vals,
            new_values=new_vals,
            change_reason=reason,
            ip_address=f"192.168.1.{random.randint(10, 99)}",
            action=action
        ))
        
    SessionChangeHistory.objects.bulk_create(history_objs)

    # ==================== RAPPORT FINAL ====================
    print("\n" + "=" * 50)
    print("GÉNÉRATION TERMINÉE AVEC SUCCÈS")
    print("=" * 50)
    print(f"\nRésumé :")
    print(f"   Salles :                   {Room.objects.count()}")
    print(f"   Catégories de Niveau :     {LevelCategory.objects.count()}")
    print(f"   Niveaux :                  {Level.objects.count()}")
    print(f"   Professeurs :              {Teacher.objects.count()}")
    print(f"   Groupes de cours :         {CourseGroup.objects.count()}")
    print(f"   Horaires :                 {CourseGroupSchedule.objects.count()}")
    print(f"   Élèves :                   {Student.objects.count()}")
    print(f"   Inscriptions :             {Enrollment.objects.count()}")
    print(f"   Séances (Sessions) :       {Session.objects.count()}")
    print(f"   Paiements élèves :         {Payment.objects.count()}")
    print(f"   Présences :                {Attendance.objects.count()}")
    print(f"   Congés enseignants :       {TeacherLeave.objects.count()}")
    print(f"   Disponibilités enseignant: {TeacherAvailability.objects.count()}")
    print(f"   Paiements professeurs :    {TeacherPayment.objects.count()}")
    print(f"   Jours Fériés / Congés :    {Holiday.objects.count()}")
    print(f"   Séances de rattrapage :    {MakeupSession.objects.count()}")
    print(f"   Journaux WhatsApp :        {WhatsAppSendLog.objects.count()}")
    print(f"   Annonces de l'école :      {Announcement.objects.count()}")
    print(f"   Verrouillages planning :   {ScheduleLock.objects.count()}")
    print(f"   Historique modifications :  {SessionChangeHistory.objects.count()}")

    total_revenue = Payment.objects.filter(status='PAID').aggregate(total=Sum('amount'))['total'] or Decimal('0')
    print(f"\n   Recette totale élèves : {total_revenue} DH")
    
    total_teacher_payout = TeacherPayment.objects.aggregate(total=Sum('amount'))['total'] or Decimal('0')
    print(f"   Total payé aux professeurs : {total_teacher_payout} DH")

    print("\n" + "=" * 50)
    print("Toutes les données de test sont chargées et prêtes !")
    print("=" * 50 + "\n")


# ==================== VARIANTES ====================

def run():
    """Appelé par la commande manage.py runscript ou shell"""
    generate_fixtures()


def quick_test_data():
    """Jeu de données minimaliste pour les tests rapides et unitaires"""
    generate_fixtures(
        num_rooms=3,
        num_teachers=4,
        num_courses=6,
        num_students=15,
        months_history=1,
        months_future=1,
        generate_payments=True,
        generate_attendance=True,
        generate_teacher_payments=True,
        generate_holidays=True,
        generate_leaves=True,
        generate_announcements=True,
        generate_logs=True
    )


def demo_data():
    """Jeu de données standard pour les démonstrations"""
    generate_fixtures(
        num_rooms=6,
        num_teachers=12,
        num_courses=20,
        num_students=80,
        months_history=6,
        months_future=2,
        generate_payments=True,
        generate_attendance=True,
        generate_teacher_payments=True,
        generate_holidays=True,
        generate_leaves=True,
        generate_announcements=True,
        generate_logs=True
    )


def full_test_data():
    """Jeu de données complet pour les tests approfondis"""
    generate_fixtures(
        num_rooms=8,
        num_teachers=15,
        num_courses=30,
        num_students=150,
        months_history=12,
        months_future=3,
        generate_payments=True,
        generate_attendance=True,
        generate_teacher_payments=True,
        generate_holidays=True,
        generate_leaves=True,
        generate_announcements=True,
        generate_logs=True
    )


def stress_test_data():
    """Jeu de données de stress de haute volumétrie"""
    generate_fixtures(
        num_rooms=20,
        num_teachers=50,
        num_courses=120,
        num_students=1000,
        months_history=12,
        months_future=3,
        generate_payments=True,
        generate_attendance=True,
        generate_teacher_payments=True,
        generate_holidays=True,
        generate_leaves=True,
        generate_announcements=True,
        generate_logs=True
    )


if __name__ == '__main__':
    print("Utilisez: python manage.py shell")
    print("Puis: from core.fixtures import generate_fixtures; generate_fixtures()")