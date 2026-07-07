"""
Script de generation de donnees de test pour l'ecole de soutien
Usage: python manage.py shell
  In [1]: from core.fixtures import generate_fixtures; generate_fixtures()
"""
import random
from datetime import datetime, timedelta, time, date
from decimal import Decimal
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum
from dateutil.relativedelta import relativedelta

# Importer les modeles
from .models import (
    Room, Teacher, CourseGroup, CourseGroupSchedule,
    Student, Enrollment, Payment, Attendance, Session, Level, LevelCategory
)


# ==================== DONNEES DE BASE ====================

MOROCCAN_FIRST_NAMES = [
    "Ahmed", "Mohamed", "Youssef", "Hassan", "Omar", "Karim", "Amine", "Mehdi",
    "Samir", "Rachid", "Abdelali", "Hamza", "Ismail", "Khalid", "Tariq",
    "Ayoub", "Zakaria", "Rayan", "Adam", "Ilyas",
    "Fatima", "Aicha", "Zineb", "Salma", "Hiba", "Meriem", "Khadija", "Nour",
    "Yasmine", "Safaa", "Laila", "Amina", "Siham", "Karima", "Houda",
    "Sanaa", "Rim", "Malak", "Imane", "Dounia",
]

MOROCCAN_LAST_NAMES = [
    "Alami", "Bennani", "El Amrani", "Filali", "Idrissi", "Benjelloun", "Tazi",
    "Lazrak", "Berrada", "Skalli", "Zahiri", "Kettani", "Chraibi", "Fassi",
    "Belhaj", "Sefrioui", "Oudghiri", "Cherkaoui", "Hassani", "Bensouda",
    "El Malki", "Kadiri", "Slaoui", "Benmoussa", "El Yousfi",
]

SUBJECTS = [
    "Mathematiques", "Physique-Chimie", "SVT", "Francais", "Arabe",
    "Anglais", "Philosophie", "Histoire-Geo", "Economie", "Informatique",
]

DEFAULT_CATEGORIES = [
    ('GARDERIE', 'La Garderie'),
    ('PRIMAIRE', 'Primaire'),
    ('COLLEGE', 'Collège'),
    ('LYCEE', 'Lycée'),
]

LEVELS_WITH_CATEGORIES = [
    ("Petite Section",   "GARDERIE"),
    ("Moyenne Section",  "GARDERIE"),
    ("Grande Section",   "GARDERIE"),
    ("5eme Primaire",    "PRIMAIRE"),
    ("6eme Primaire",    "PRIMAIRE"),
    ("1ere College",     "COLLEGE"),
    ("2eme College",     "COLLEGE"),
    ("3eme College",     "COLLEGE"),
    ("Tronc Commun",     "LYCEE"),
    ("1ere Bac Sciences","LYCEE"),
    ("2eme Bac Sciences","LYCEE"),
    ("1ere Bac Lettres", "LYCEE"),
    ("2eme Bac Lettres", "LYCEE"),
]

DAYS = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT']

DAY_MAP = {'MON': 0, 'TUE': 1, 'WED': 2, 'THU': 3, 'FRI': 4, 'SAT': 5, 'SUN': 6}

PHONE_NUMBERS = ["0661345595", "0715125245", "0691417587", "0662001122", "0698334455"]


# ==================== FONCTIONS UTILITAIRES ====================

def generate_phone():
    return random.choice(PHONE_NUMBERS)


def generate_full_name():
    return f"{random.choice(MOROCCAN_FIRST_NAMES)} {random.choice(MOROCCAN_LAST_NAMES)}"


def random_time(start_hour=8, end_hour=18):
    """Genere une heure de debut aleatoire (heures pleines ou demi-heures)"""
    hour = random.randint(start_hour, end_hour - 1)
    minute = random.choice([0, 30])
    return time(hour, minute)


def add_hours(t, hours):
    """Add `hours` (float) to a time object, capped at 21:00."""
    total_minutes = t.hour * 60 + t.minute + int(hours * 60)
    total_minutes = min(total_minutes, 21 * 60)
    return time(total_minutes // 60, total_minutes % 60)


def times_overlap(s1, e1, s2, e2):
    """True if [s1, e1) overlaps [s2, e2)."""
    return s1 < e2 and e1 > s2


def _bulk_save(model_class, instances):
    """bulk_create bypasses all model-level validation and signals."""
    if not instances:
        return []
    return model_class.objects.bulk_create(instances, ignore_conflicts=True)


# ==================== FONCTION PRINCIPALE ====================

@transaction.atomic
def generate_fixtures(
    num_rooms=6,
    num_teachers=8,
    num_courses=15,
    num_students=50,
    generate_payments=True,
    generate_attendance=True,
):
    """
    Genere toutes les donnees de test en contournant full_clean() et les signaux.
    Utilise bulk_create() pour eviter les ValidationError de conflit.
    """

    print("[*] Suppression des anciennes donnees...")
    Attendance.objects.all().delete()
    Payment.objects.all().delete()
    Session.objects.all().delete()
    Enrollment.objects.all().delete()
    CourseGroupSchedule.objects.all().delete()
    CourseGroup.objects.all().delete()
    Student.objects.all().delete()
    Level.objects.all().delete()
    Teacher.objects.all().delete()
    Room.objects.all().delete()

    print("\n" + "=" * 50)
    print("GENERATION DES DONNEES DE TEST")
    print("=" * 50 + "\n")

    # ==================== 1. SALLES ====================
    print(f"[+] Creation de {num_rooms} salles...")
    _bulk_save(Room, [
        Room(name=f"Salle {i}", capacity=random.randint(15, 30), is_active=True)
        for i in range(1, num_rooms + 1)
    ])
    rooms = list(Room.objects.all())
    for r in rooms:
        print(f"    OK {r.name} - Capacite: {r.capacity}")

    # ==================== 0. CATEGORIES DE NIVEAU ====================
    print(f"\n[+] Creation de {len(DEFAULT_CATEGORIES)} catégories de niveau...")
    category_map = {}
    for code, name in DEFAULT_CATEGORIES:
        cat, created = LevelCategory.objects.get_or_create(code=code, defaults={'name': name})
        category_map[code] = cat
        print(f"    OK {name} ({code})")

    # ==================== 1.5 NIVEAUX ====================
    print(f"\n[+] Creation de {len(LEVELS_WITH_CATEGORIES)} niveaux...")
    _bulk_save(Level, [
        Level(name=n, category=category_map[c])
        for n, c in LEVELS_WITH_CATEGORIES
    ])
    db_levels = list(Level.objects.all())
    for lvl in db_levels:
        print(f"    OK {lvl.name} ({lvl.get_category_display()})")

    # ==================== 2. PROFESSEURS ====================
    print(f"\n[+] Creation de {num_teachers} professeurs...")
    teacher_objs = []
    for idx in range(num_teachers):
        method = random.choices(['PERCENTAGE', 'HOURLY'], weights=[0.7, 0.3])[0]
        teacher_objs.append(Teacher(
            name=generate_full_name(),
            phone=generate_phone(),
            email=f"teacher{idx}_{random.randint(100, 999)}@email.com",
            hourly_rate=Decimal(random.choice(['80.00', '100.00', '120.00', '150.00'])),
            payment_method=method,
            payment_percentage=Decimal(random.choice(['40.00', '50.00', '60.00'])),
            session_rate=Decimal('100.00'),
            is_active=True,
        ))
    _bulk_save(Teacher, teacher_objs)
    teachers = list(Teacher.objects.all())
    for t in teachers:
        print(f"    OK {t.name} ({t.get_payment_method_display()})")

    # ==================== 3. GROUPES DE COURS + HORAIRES ====================
    print(f"\n[+] Creation de {num_courses} groupes de cours...")

    courses = []
    course_schedule_objs = []

    # For proper overlap detection: {(room_id, day): [(start, end), ...]}
    room_day_slots: dict = {}
    teacher_day_slots: dict = {}

    PRICES = ['300.00', '350.00', '400.00', '450.00', '500.00', '600.00']
    DURATIONS = [1.5, 2.0, 2.5]

    for _ in range(num_courses):
        teacher = random.choice(teachers)
        day = random.choice(DAYS)

        # Try up to 40 combinations of (room, start_time) to find a conflict-free slot
        found = False
        chosen_room = None
        chosen_start = None
        chosen_end = None

        for _attempt in range(40):
            room = random.choice(rooms)
            start = random_time(8, 18)
            duration = random.choice(DURATIONS)
            end = add_hours(start, duration)

            r_key = (room.id, day)
            t_key = (teacher.id, day)

            r_slots = room_day_slots.get(r_key, [])
            t_slots = teacher_day_slots.get(t_key, [])

            r_conflict = any(times_overlap(start, end, s, e) for s, e in r_slots)
            t_conflict = any(times_overlap(start, end, s, e) for s, e in t_slots)

            if not r_conflict and not t_conflict:
                room_day_slots.setdefault(r_key, []).append((start, end))
                teacher_day_slots.setdefault(t_key, []).append((start, end))
                found = True
                chosen_room = room
                chosen_start = start
                chosen_end = end
                break

        if not found:
            print(f"    SKIP Pas de creneau libre, cours ignore")
            continue

        subject = random.choice(SUBJECTS)
        level = random.choice(db_levels)
        price = Decimal(random.choice(PRICES))

        # Save CourseGroup bypassing signals by calling grandparent Model.save directly
        from django.db.models import Model as _BaseModel
        course = CourseGroup(
            name=f"{subject} - {level.name}",
            subject=subject,
            level=level,
            monthly_price=price,
            teacher=teacher,
            is_active=True,
        )
        _BaseModel.save(course)  # Bypasses signals defined in models.py

        courses.append(course)
        course_schedule_objs.append(CourseGroupSchedule(
            course_group=course,
            day=day,
            start_time=chosen_start,
            end_time=chosen_end,
            room=chosen_room,
        ))
        print(f"    OK {course.name} - {price} DH ({day} {chosen_start}-{chosen_end})")

    # Bulk create schedules (bypasses full_clean + signals)
    _bulk_save(CourseGroupSchedule, course_schedule_objs)

    # Reload schedules with PKs for session generation
    schedules_db = {sch.course_group_id: sch for sch in CourseGroupSchedule.objects.all()}

    # ==================== 4. ELEVES ====================
    print(f"\n[+] Creation de {num_students} eleves...")
    student_objs = []
    for _ in range(num_students):
        student_objs.append(Student(
            name=generate_full_name(),
            phone=generate_phone(),
            parent_contact=generate_phone(),
            parent_name=generate_full_name(),
            address=f"{random.randint(1, 200)} Rue {random.choice(['Hassan II', 'Mohamed V', 'Ibn Batouta'])}, Casablanca",
            date_of_birth=date(random.randint(2005, 2012), random.randint(1, 12), random.randint(1, 28)),
            level=random.choice(db_levels),
            main_school=random.choice(["Lycée Lyautey", "École Al Jabr", "Lycée Massignon", "Institution Tahar", "Établissement El Yakout", ""]),
            is_active=True,
        ))
    _bulk_save(Student, student_objs)
    students = list(Student.objects.all())
    print(f"    OK {len(students)} eleves crees")

    # ==================== 5. INSCRIPTIONS ====================
    print(f"\n[+] Creation des inscriptions...")
    enrollment_objs = []
    seen_pairs = set()

    # Build a schedule index: course_id -> list of (day, start, end)
    course_schedules_index: dict = {}
    for sch in CourseGroupSchedule.objects.all():
        course_schedules_index.setdefault(sch.course_group_id, []).append(
            (sch.day, sch.start_time, sch.end_time)
        )

    for student in students:
        num_enroll = random.randint(1, min(4, len(courses)))
        candidates = random.sample(courses, min(num_enroll + 3, len(courses)))

        # Already-booked (day, start, end) for this student
        booked: list = []
        enrolled_count = 0

        for course in candidates:
            if enrolled_count >= num_enroll:
                break
            pair = (student.id, course.id)
            if pair in seen_pairs:
                continue

            c_slots = course_schedules_index.get(course.id, [])
            conflict = False
            for (c_day, c_start, c_end) in c_slots:
                for (b_day, b_start, b_end) in booked:
                    if c_day == b_day and times_overlap(c_start, c_end, b_start, b_end):
                        conflict = True
                        break
                if conflict:
                    break

            if conflict:
                continue

            seen_pairs.add(pair)
            enrollment_objs.append(Enrollment(student=student, course_group=course, is_active=True))
            booked.extend(c_slots)
            enrolled_count += 1

    _bulk_save(Enrollment, enrollment_objs)
    enrollments_count = Enrollment.objects.count()
    print(f"    Total: {enrollments_count} inscriptions creees")

    # ==================== 6. SESSIONS ====================
    print(f"\n[+] Generation des sessions (historique + prochains jours)...")
    today = timezone.now().date()
    session_objs = []
    used_session_slots: set = set()

    for course in courses:
        sch = schedules_db.get(course.id)
        if not sch:
            continue
        target_weekday = DAY_MAP.get(sch.day, -1)
        if target_weekday < 0:
            continue

        start_date = today - timedelta(days=45)
        end_date = today + timedelta(days=14)
        current = start_date
        while current <= end_date:
            if current.weekday() == target_weekday:
                slot = (current, course.id)
                if slot not in used_session_slots:
                    used_session_slots.add(slot)
                    if current < today:
                        status = 'DONE' if random.random() > 0.08 else 'CANCELLED'
                    else:
                        status = 'PLANNED'
                    session_objs.append(Session(
                        group=course,
                        schedule=sch,
                        date=current,
                        start_time=sch.start_time,
                        end_time=sch.end_time,
                        room=sch.room,
                        status=status,
                    ))
            current += timedelta(days=1)

    _bulk_save(Session, session_objs)
    print(f"    OK {len(session_objs)} sessions creees")

    # ==================== 7. PAIEMENTS ====================
    if generate_payments:
        print("\n[+] Generation de l'historique des paiements...")
        payment_objs = []
        receipt_counter = 0
        year = timezone.now().year
        base_month = today.replace(day=1)

        for month_offset in range(3, -1, -1):
            target_month = base_month - relativedelta(months=month_offset)
            print(f"\n    Mois: {target_month.strftime('%B %Y')}")
            month_count = 0

            for student in students:
                total_fees = student.total_monthly_fees()
                if total_fees == 0:
                    continue

                scenario = random.choices(['full', 'partial', 'none'], weights=[0.7, 0.2, 0.1])[0]
                if scenario == 'none':
                    continue

                if scenario == 'full':
                    amount = total_fees
                else:
                    amount = (total_fees * Decimal(
                        random.choice(['0.5', '0.6', '0.7', '0.8'])
                    )).quantize(Decimal('0.01'))

                receipt_counter += 1
                payment_date = target_month + timedelta(days=random.randint(0, 14))

                payment_objs.append(Payment(
                    student=student,
                    amount=amount,
                    payment_date=payment_date,
                    month_covered=target_month,
                    status='PAID',
                    payment_method=random.choice(['CASH', 'TRANSFER', 'CHECK']),
                    notes="" if random.random() > 0.2 else "Paiement echelonne",
                    is_locked=month_offset >= 2,
                    receipt_number=f"REC{year}{receipt_counter:04d}",
                ))
                month_count += 1

            print(f"      OK {month_count} paiements pour ce mois")

        _bulk_save(Payment, payment_objs)
        print(f"\n    Total: {len(payment_objs)} paiements crees")

    # ==================== 8. PRESENCES ====================
    if generate_attendance:
        print(f"\n[+] Generation des presences...")
        attendance_objs = []
        seen_att = set()
        start_date = today - timedelta(days=30)

        day_map_int = {0: 'MON', 1: 'TUE', 2: 'WED', 3: 'THU', 4: 'FRI', 5: 'SAT', 6: 'SUN'}

        for n in range(30):
            current_date = start_date + timedelta(days=n)
            day_code = day_map_int[current_date.weekday()]
            daily_courses = CourseGroup.objects.filter(schedules__day=day_code, is_active=True).distinct()

            for course in daily_courses:
                enrolled_students = Student.objects.filter(enrollments=course, is_active=True)
                for student in enrolled_students:
                    key = (student.id, course.id, current_date)
                    if key in seen_att:
                        continue
                    seen_att.add(key)
                    is_present = random.random() < 0.90
                    attendance_objs.append(Attendance(
                        student=student,
                        course_group=course,
                        date=current_date,
                        is_present=is_present,
                        notes="" if is_present else random.choice(["", "", "Malade", "Absent sans justification"]),
                    ))

        _bulk_save(Attendance, attendance_objs)
        print(f"    Total: {len(attendance_objs)} presences enregistrees")

    # ==================== RAPPORT FINAL ====================
    print("\n" + "=" * 50)
    print("GENERATION TERMINEE")
    print("=" * 50)
    print(f"\nResume:")
    print(f"   Salles:           {Room.objects.count()}")
    print(f"   Niveaux:          {Level.objects.count()}")
    print(f"   Professeurs:      {Teacher.objects.count()}")
    print(f"   Groupes de cours: {CourseGroup.objects.count()}")
    print(f"   Horaires:         {CourseGroupSchedule.objects.count()}")
    print(f"   Eleves:           {Student.objects.count()}")
    print(f"   Inscriptions:     {Enrollment.objects.count()}")
    print(f"   Sessions:         {Session.objects.count()}")
    print(f"   Paiements:        {Payment.objects.count()}")
    print(f"   Presences:        {Attendance.objects.count()}")

    total_revenue = Payment.objects.filter(status='PAID').aggregate(total=Sum('amount'))['total'] or Decimal('0')
    print(f"\n   Recette totale: {total_revenue} DH")

    unpaid_count = sum(
        1 for student in Student.objects.filter(is_active=True)
        if student.payment_status() in ['UNPAID', 'PARTIAL']
    )
    print(f"   Eleves impayes/partiels ce mois: {unpaid_count}")

    print("\n" + "=" * 50)
    print("Vous pouvez maintenant tester l'application!")
    print("=" * 50 + "\n")


# ==================== VARIANTES ====================

def run():
    """Appele depuis une management command"""
    generate_fixtures()


def quick_test_data():
    """Version rapide avec peu de donnees (tests unitaires)"""
    generate_fixtures(
        num_rooms=3,
        num_teachers=3,
        num_courses=5,
        num_students=10,
        generate_payments=True,
        generate_attendance=False,
    )


def full_test_data():
    """Version complete avec beaucoup de donnees (demo)"""
    generate_fixtures(
        num_rooms=6,
        num_teachers=12,
        num_courses=25,
        num_students=100,
        generate_payments=True,
        generate_attendance=True,
    )


if __name__ == '__main__':
    print("Utilisez: python manage.py shell")
    print("Puis: from core.fixtures import generate_fixtures; generate_fixtures()")