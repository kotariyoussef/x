import logging
import random
from datetime import date, datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import connection, models, transaction
from django.db.models import Max, Q, Sum
from django.db.utils import IntegrityError
from django.utils import timezone
from django.utils.text import slugify

logger = logging.getLogger(__name__)


class TeacherPaymentMethod(models.TextChoices):
    HOURLY = 'HOURLY', 'Taux horaire'
    PERCENTAGE = 'PERCENTAGE', 'Part des gains (pourcentage des gains de la classe)'
    SESSION = 'SESSION', 'Tarif par session'


class TeacherPaymentType(models.TextChoices):
    ADVANCE = 'ADVANCE', 'Avance / Acompte'
    SALARY = 'SALARY', 'Règlement de salaire'
    ADJUSTMENT = 'ADJUSTMENT', 'Régularisation'


class TeacherLeaveType(models.TextChoices):
    SICK = 'SICK', 'Maladie'
    VACATION = 'VACATION', 'Vacances'
    OTHER = 'OTHER', 'Autre'


class PaymentStatus(models.TextChoices):
    PAID = 'PAID', 'Payé'
    PENDING = 'PENDING', 'En attente'
    CANCELLED = 'CANCELLED', 'Annulé'


class PaymentMethod(models.TextChoices):
    CASH = 'CASH', 'Espèces'
    TRANSFER = 'TRANSFER', 'Virement'
    CHECK = 'CHECK', 'Chèque'


class SessionStatus(models.TextChoices):
    PLANNED = 'PLANNED', 'Prévu'
    DONE = 'DONE', 'Terminé'
    CANCELLED = 'CANCELLED', 'Annulé'


WEEKDAY_TO_CODE = {
    0: 'MON',
    1: 'TUE',
    2: 'WED',
    3: 'THU',
    4: 'FRI',
    5: 'SAT',
    6: 'SUN',
}


def overlaps(start_a, end_a, start_b, end_b):
    return start_a < end_b and end_a > start_b


def duration_hours(start_time, end_time):
    start = datetime.combine(date.today(), start_time)
    end = datetime.combine(date.today(), end_time)
    return (end - start).total_seconds() / 3600


def get_weekday_code(day_value):
    if hasattr(day_value, 'weekday'):
        return WEEKDAY_TO_CODE[day_value.weekday()]
    return day_value


class Room(models.Model):
    """Salle de classe"""
    name = models.CharField(max_length=50, unique=True, verbose_name="Nom de la salle")
    capacity = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        verbose_name="Capacité"
    )
    is_active = models.BooleanField(default=True, verbose_name="Active")
    
    class Meta:
        verbose_name = "Salle"
        verbose_name_plural = "Salles"
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.capacity} places)"


class Teacher(models.Model):
    """Professeur"""
    PAYMENT_METHOD_CHOICES = TeacherPaymentMethod.choices
    
    name = models.CharField(max_length=100, verbose_name="Nom complet")
    phone = models.CharField(max_length=20, verbose_name="Téléphone")
    email = models.EmailField(blank=True, verbose_name="Email")
    hourly_rate = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        verbose_name="Tarif horaire (DH)",
        default=Decimal('100.00'),
        blank=True,
        null=True
    )
    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
        default=TeacherPaymentMethod.PERCENTAGE,
        verbose_name="Mode de paiement"
    )
    payment_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('50.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name="Part des gains (%)",
        blank=True,
        null=True
    )
    session_rate = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal('100.00'),
        validators=[MinValueValidator(Decimal('0.01'))],
        verbose_name="Tarif par session (DH)",
        blank=True,
        null=True
    )
    is_active = models.BooleanField(default=True, verbose_name="Actif")
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Professeur"
        verbose_name_plural = "Professeurs"
        ordering = ['name']
    
    def clean(self):
        super().clean()
        if self.payment_method == TeacherPaymentMethod.HOURLY and not self.hourly_rate:
            raise ValidationError({'hourly_rate': "Le tarif horaire est requis pour le mode de paiement 'Taux horaire'."})
        if self.payment_method == TeacherPaymentMethod.PERCENTAGE and self.payment_percentage is None:
            raise ValidationError({'payment_percentage': "La part des gains (%) est requise pour le mode de paiement 'Part des gains'."})
        if self.payment_method == TeacherPaymentMethod.SESSION and not self.session_rate:
            raise ValidationError({'session_rate': "Le tarif par session est requis pour le mode de paiement 'Tarif par session'."})
            
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
        
    def __str__(self):
        if self.payment_method == TeacherPaymentMethod.PERCENTAGE:
            return f"{self.name} ({self.payment_percentage}%)"
        elif self.payment_method == TeacherPaymentMethod.SESSION:
            return f"{self.name} ({self.session_rate} DH/sess)"
        return f"{self.name} ({self.hourly_rate} DH/h)"


class TeacherLeave(models.Model):
    """Congés des enseignants"""
    LEAVE_CHOICES = TeacherLeaveType.choices
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name='leaves', verbose_name="Enseignant")
    start_date = models.DateField(verbose_name="Date de début")
    end_date = models.DateField(verbose_name="Date de fin")
    leave_type = models.CharField(max_length=10, choices=LEAVE_CHOICES, default=TeacherLeaveType.OTHER, verbose_name="Type de congé")
    notes = models.TextField(blank=True, verbose_name="Notes")

    class Meta:
        verbose_name = "Congé enseignant"
        verbose_name_plural = "Congés enseignants"
        ordering = ['-start_date']

    def clean(self):
        super().clean()
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError("La date de fin doit être postérieure ou égale à la date de début.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.teacher.name} – {self.get_leave_type_display()} du {self.start_date} au {self.end_date}"


class TeacherPayment(models.Model):
    """Paiements et avances des enseignants"""
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name='payroll_payments', verbose_name="Enseignant")
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))], verbose_name="Montant (DH)")
    payment_date = models.DateField(default=timezone.now, verbose_name="Date de paiement")
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.CASH, verbose_name="Mode de paiement")
    payment_type = models.CharField(max_length=20, choices=TeacherPaymentType.choices, default=TeacherPaymentType.SALARY, verbose_name="Type de paiement")
    period_month = models.PositiveSmallIntegerField(verbose_name="Mois de la période")
    period_year = models.PositiveSmallIntegerField(verbose_name="Année de la période")
    notes = models.TextField(blank=True, verbose_name="Notes / Détails")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Paiement Enseignant"
        verbose_name_plural = "Paiements Enseignants"
        ordering = ['-payment_date', '-id']

    def clean(self):
        super().clean()
        if self.period_month < 1 or self.period_month > 12:
            raise ValidationError({'period_month': "Le mois doit être compris entre 1 et 12."})
        if self.period_year < 2000 or self.period_year > 2100:
            raise ValidationError({'period_year': "L'année doit être valide."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.teacher.name} – {self.amount} DH ({self.get_payment_type_display()} - {self.period_month}/{self.period_year})"


def check_teacher_availability(teacher, day, start_time, end_time, date_val=None):
    # Check leaves (date-specific) if date is provided
    if date_val:
        leaves = TeacherLeave.objects.filter(
            teacher=teacher,
            start_date__lte=date_val,
            end_date__gte=date_val
        )
        if leaves.exists():
            l = leaves.first()
            raise ValidationError(
                f"Le professeur '{teacher.name}' est en congé ({l.get_leave_type_display()}) "
                f"du {l.start_date.strftime('%d/%m/%Y')} au {l.end_date.strftime('%d/%m/%Y')}."
            )

    # Check weekly availability (day-specific)
    availabilities = TeacherAvailability.objects.filter(teacher=teacher, day=day)
    if availabilities.exists():
        # 1. Any unavailable (is_available=False) slot overlaps?
        unavailables = availabilities.filter(is_available=False)
        for ua in unavailables:
            if start_time < ua.end_time and end_time > ua.start_time:
                raise ValidationError(
                    f"Le professeur '{teacher.name}' est indisponible le {ua.get_day_display()} "
                    f"de {ua.start_time.strftime('%H:%M')} à {ua.end_time.strftime('%H:%M')}."
                )

        # 2. If there are available (is_available=True) slots, must fit entirely within at least one
        availables = availabilities.filter(is_available=True)
        if availables.exists():
            fits = False
            for av in availables:
                if start_time >= av.start_time and end_time <= av.end_time:
                    fits = True
                    break
            if not fits:
                raise ValidationError(
                    f"Le créneau {start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')} le {day} "
                    f"est en dehors des créneaux de disponibilité autorisés pour le professeur '{teacher.name}'."
                )


class LevelCategory(models.Model):
    """Catégorie de niveau académique"""
    name = models.CharField(max_length=100, unique=True, verbose_name="Nom de la catégorie")
    code = models.CharField(max_length=50, unique=True, verbose_name="Code")

    class Meta:
        verbose_name = "Catégorie de niveau"
        verbose_name_plural = "Catégories de niveau"
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = slugify(self.name).upper()
        super().save(*args, **kwargs)


class Level(models.Model):
    """Niveau académique"""
    
    name = models.CharField(max_length=100, unique=True, verbose_name="Nom du niveau")
    category = models.ForeignKey(
        LevelCategory,
        on_delete=models.PROTECT,
        related_name='levels',
        verbose_name="Catégorie"
    )
    
    class Meta:
        verbose_name = "Niveau"
        verbose_name_plural = "Niveaux"
        ordering = ['category', 'name']
    
    def __str__(self):
        return self.name

    def get_category_display(self):
        return self.category.name if self.category else ""


class CourseGroup(models.Model):
    """Groupe de cours"""
    DAYS_CHOICES = [
        ('MON', 'Lundi'),
        ('TUE', 'Mardi'),
        ('WED', 'Mercredi'),
        ('THU', 'Jeudi'),
        ('FRI', 'Vendredi'),
        ('SAT', 'Samedi'),
        ('SUN', 'Dimanche'),
    ]
    
    name = models.CharField(max_length=100, verbose_name="Nom du groupe")
    subject = models.CharField(max_length=100, verbose_name="Matière")
    level = models.ForeignKey(
        Level,
        on_delete=models.SET_NULL,
        related_name='course_groups',
        verbose_name="Niveau",
        null=True,
        blank=True
    )
    
    monthly_price = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        verbose_name="Prix mensuel (DH)"
    )
    
    teacher = models.ForeignKey(
        Teacher,
        on_delete=models.PROTECT,
        related_name='course_groups',
        verbose_name="Professeur"
    )
    
    whatsapp_group_link = models.URLField(
        blank=True,
        null=True,
        verbose_name="Lien du groupe WhatsApp"
    )
    
    is_active = models.BooleanField(default=True, verbose_name="Actif")
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Groupe de cours"
        verbose_name_plural = "Groupes de cours"
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.subject})"


class CourseGroupSchedule(models.Model):
    """Horaire hebdomadaire pour un groupe de cours"""
    course_group = models.ForeignKey(
        CourseGroup,
        on_delete=models.CASCADE,
        related_name='schedules',
        verbose_name="Groupe de cours"
    )
    day = models.CharField(
        max_length=3,
        choices=CourseGroup.DAYS_CHOICES,
        verbose_name="Jour"
    )
    start_time = models.TimeField(verbose_name="Heure de début")
    end_time = models.TimeField(verbose_name="Heure de fin")
    room = models.ForeignKey(
        Room,
        on_delete=models.PROTECT,
        related_name='schedules',
        verbose_name="Salle"
    )

    class Meta:
        verbose_name = "Horaire de groupe"
        verbose_name_plural = "Horaires de groupe"
        ordering = ['day', 'start_time']

    def __str__(self):
        return f"{self.course_group.name} - {self.get_day_display()} {self.start_time.strftime('%H:%M')}-{self.end_time.strftime('%H:%M')} ({self.room.name})"

    def duration_hours(self):
        return duration_hours(self.start_time, self.end_time)

    def clean(self):
        super().clean()

        if self.end_time <= self.start_time:
            raise ValidationError("L'heure de fin doit être postérieure à l'heure de début.")
        
        # Check room conflicts
        overlapping_rooms = CourseGroupSchedule.objects.filter(
            room=self.room,
            day=self.day,
            course_group__is_active=True
        )
        if self.pk:
            overlapping_rooms = overlapping_rooms.exclude(pk=self.pk)
        for s in overlapping_rooms:
            if overlaps(self.start_time, self.end_time, s.start_time, s.end_time):
                raise ValidationError(
                    f"La salle '{self.room.name}' est déjà réservée par le groupe '{s.course_group.name}' "
                    f"de {s.start_time.strftime('%H:%M')} à {s.end_time.strftime('%H:%M')} le {s.get_day_display()}."
                )

        # Check teacher conflicts
        overlapping_teachers = CourseGroupSchedule.objects.filter(
            course_group__teacher=self.course_group.teacher,
            day=self.day,
            course_group__is_active=True
        )
        if self.pk:
            overlapping_teachers = overlapping_teachers.exclude(pk=self.pk)
        for s in overlapping_teachers:
            if overlaps(self.start_time, self.end_time, s.start_time, s.end_time):
                raise ValidationError(
                    f"Le professeur '{self.course_group.teacher.name}' est déjà affecté au groupe '{s.course_group.name}' "
                    f"de {s.start_time.strftime('%H:%M')} à {s.end_time.strftime('%H:%M')} le {s.get_day_display()}."
                )

        # Check teacher availability/leave
        # if self.course_group and self.course_group.teacher:
        #     check_teacher_availability(self.course_group.teacher, self.day, self.start_time, self.end_time)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


def get_easy_numbers_2_digits():
    easy = set()
    for i in range(1, 10):
        easy.add(i)
    for i in range(10, 100, 10):
        easy.add(i)
    for i in range(11, 100, 11):
        easy.add(i)
    for i in range(1, 9):
        easy.add(i * 10 + (i + 1))
    return sorted(list(easy))

def get_easy_numbers_3_digits():
    easy = set()
    for i in range(100, 1000, 100):
        easy.add(i)
    for i in range(100, 1000, 10):
        easy.add(i)
    for i in range(111, 1000, 111):
        easy.add(i)
    for i in range(100, 1000):
        s = str(i)
        if s[0] == s[2]:
            easy.add(i)
    for i in range(1, 8):
        easy.add(i * 100 + (i + 1) * 10 + (i + 2))
    return sorted(list(easy))


class Student(models.Model):
    """Élève"""
    matricule = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        null=True,
        verbose_name="Matricule"
    )
    name = models.CharField(max_length=100, verbose_name="Nom complet")
    phone = models.CharField(max_length=20, blank=True, verbose_name="Téléphone élève")
    parent_contact = models.CharField(max_length=20, verbose_name="Téléphone parent")
    parent_name = models.CharField(max_length=100, blank=True, verbose_name="Nom du parent")
    
    address = models.TextField(blank=True, verbose_name="Adresse")
    date_of_birth = models.DateField(null=True, blank=True, verbose_name="Date de naissance")
    
    level = models.ForeignKey(
        Level,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='students',
        verbose_name="Niveau scolaire"
    )
    main_school = models.CharField(max_length=150, blank=True, verbose_name="Établissement principal")
    
    # Relation Many-to-Many avec les groupes
    enrollments = models.ManyToManyField(
        CourseGroup,
        through='Enrollment',
        related_name='students',
        verbose_name="Groupes inscrits"
    )
    
    is_active = models.BooleanField(default=True, verbose_name="Actif")
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, verbose_name="Notes")
    
    class Meta:
        verbose_name = "Élève"
        verbose_name_plural = "Élèves"
        ordering = ['name']
    
    def __str__(self):
        return self.name
    
    def total_monthly_fees(self):
        """Calcule le total des frais mensuels"""
        active_enrollments = self.enrollment_set.filter(is_active=True)
        # Ensure Decimal result even when no enrollments
        total = sum((e.course_group.monthly_price for e in active_enrollments), Decimal('0.00'))
        return total
     
    def payment_status(self):
        from .utils import calculate_student_monthly_total
        current_month = timezone.now().date().replace(day=1)

        required = calculate_student_monthly_total(self)

        paid = (
            self.payments
            .filter(month_covered=current_month, status='PAID')
            .aggregate(total=Sum('amount'))['total']
            or Decimal('0')
        )

        if required == 0:
            return 'OK'  # No courses = nothing to pay

        if paid >= required:
            return 'OK'
        elif paid > 0:
            return 'PARTIAL'
        return 'UNPAID'

    @classmethod
    def _build_candidate_matricule(cls, prefix, used_numbers):
        available_2 = [n for n in range(1, 100) if n not in used_numbers]
        if available_2:
            easy_2 = set(get_easy_numbers_2_digits())
            available_easy = [n for n in available_2 if n in easy_2]
            chosen = random.choice(available_easy or available_2)
            return f"{prefix}{chosen:02d}"

        available_3 = [n for n in range(100, 1000) if n not in used_numbers]
        if available_3:
            easy_3 = set(get_easy_numbers_3_digits())
            available_easy = [n for n in available_3 if n in easy_3]
            chosen = random.choice(available_easy or available_3)
            return f"{prefix}{chosen:03d}"

        new_num = 1000
        while True:
            candidate = f"{prefix}{new_num}"
            if candidate not in used_numbers:
                return candidate
            new_num += 1

    @classmethod
    def generate_next_matricule(cls, year=None):
        year_prefix = (year or timezone.now().strftime('%y'))
        prefix = f"M{year_prefix}-"

        for _ in range(20):
            with transaction.atomic():
                queryset = cls.objects.filter(matricule__startswith=prefix)
                if connection.features.has_select_for_update:
                    queryset = queryset.select_for_update()

                existing_matricules = list(queryset.values_list('matricule', flat=True))
                used_numbers = set()
                for matricule in existing_matricules:
                    try:
                        used_numbers.add(int(matricule.split('-')[1]))
                    except (IndexError, ValueError):
                        continue

                candidate = cls._build_candidate_matricule(prefix, used_numbers)
                if not cls.objects.filter(matricule=candidate).exists():
                    return candidate

        raise RuntimeError("Unable to generate a unique student matricule")

    def save(self, *args, **kwargs):
        if not self.matricule:
            for _ in range(20):
                self.matricule = self.generate_next_matricule()
                try:
                    super().save(*args, **kwargs)
                    return
                except IntegrityError:
                    continue
            raise RuntimeError("Unable to assign a unique student matricule")

        super().save(*args, **kwargs)




class Enrollment(models.Model):
    """Inscription d'un élève dans un groupe (table intermédiaire)"""
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    course_group = models.ForeignKey(CourseGroup, on_delete=models.CASCADE)
    enrolled_date = models.DateField(auto_now_add=True, verbose_name="Date d'inscription")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    next_payment_date = models.DateField(null=True, blank=True, verbose_name="Prochaine date de paiement")
    
    class Meta:
        verbose_name = "Inscription"
        verbose_name_plural = "Inscriptions"
        constraints = [
            models.UniqueConstraint(fields=['student', 'course_group'], name='unique_enrollment_per_student_course_group')
        ]
    
    def clean(self):
        super().clean()
        # Student schedule conflict detection: prevent enrolling in two groups
        # whose weekly slots overlap on the same day and time window.
        if not self.student_id or not self.course_group_id:
            return

        new_schedules = CourseGroupSchedule.objects.filter(
            course_group=self.course_group
        ).select_related('course_group')

        # Active enrollments for this student, excluding the current group
        existing_enrollments = (
            Enrollment.objects
            .filter(student_id=self.student_id, is_active=True)
            .exclude(course_group=self.course_group)
            .select_related('course_group')
        )
        existing_group_ids = existing_enrollments.values_list('course_group_id', flat=True)
        existing_schedules = CourseGroupSchedule.objects.filter(
            course_group_id__in=existing_group_ids
        ).select_related('course_group')

        for new_sch in new_schedules:
            for existing_sch in existing_schedules:
                if new_sch.day == existing_sch.day:
                    if overlaps(new_sch.start_time, new_sch.end_time, existing_sch.start_time, existing_sch.end_time):
                        raise ValidationError(
                            f"Conflit d'horaire détecté : le groupe '{self.course_group.name}' "
                            f"({new_sch.get_day_display()} "
                            f"{new_sch.start_time.strftime('%H:%M')}-{new_sch.end_time.strftime('%H:%M')}) "
                            f"chevauche le groupe '{existing_sch.course_group.name}' déjà inscrit "
                            f"({existing_sch.start_time.strftime('%H:%M')}-{existing_sch.end_time.strftime('%H:%M')})."
                        )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def get_initial_payment(self):
        """Returns the initial payment for this enrollment's month, if paid"""
        month_start = self.enrolled_date.replace(day=1)
        payment = self.student.payments.filter(month_covered=month_start, status='PAID').first()
        if payment:
            return f"{payment.amount} DH (Reçu N° {payment.receipt_number})"
        return "Non payé"

    def __str__(self):
        return f"{self.student.name} → {self.course_group.name}"


class Payment(models.Model):
    """Paiement"""
    STATUS_CHOICES = PaymentStatus.choices
    PAYMENT_METHOD_CHOICES = PaymentMethod.choices
    
    student = models.ForeignKey(
        Student,
        on_delete=models.PROTECT,
        related_name='payments',
        verbose_name="Élève"
    )
    
    amount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        verbose_name="Montant (DH)"
    )
    
    payment_date = models.DateField(verbose_name="Date de paiement")
    month_covered = models.DateField(
        verbose_name="Mois couvert",
        help_text="Premier jour du mois couvert par ce paiement"
    )
    
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default=PaymentStatus.PAID,
        verbose_name="Statut"
    )
    
    payment_method = models.CharField(
        max_length=10,
        choices=PAYMENT_METHOD_CHOICES,
        default=PaymentMethod.CASH,
        verbose_name="Mode de paiement"
    )
    
    receipt_number = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="N° de reçu"
    )
    
    notes = models.TextField(blank=True, verbose_name="Notes")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.CharField(max_length=100, blank=True, verbose_name="Créé par")
    
    # Verrou numérique : empêcher modification
    is_locked = models.BooleanField(default=False, verbose_name="Verrouillé")
    
    class Meta:
        verbose_name = "Paiement"
        verbose_name_plural = "Paiements"
        ordering = ['-payment_date', '-created_at']
    
    def __str__(self):
        return f"Reçu {self.receipt_number} - {self.student.name} - {self.amount} DH"
    
    def get_prorated_details(self):
        """Returns pro-rated details for student enrollments in the payment month"""
        from .utils import count_scheduled_sessions_in_month, count_remaining_sessions_in_month
        details = []
        month_covered = self.month_covered
        if not month_covered:
            return details
            
        enrollments = self.student.enrollment_set.filter(is_active=True).select_related('course_group')
        for e in enrollments:
            if e.enrolled_date.year == month_covered.year and e.enrolled_date.month == month_covered.month:
                if e.enrolled_date.day > 1:
                    total_sess = count_scheduled_sessions_in_month(e.course_group, month_covered.year, month_covered.month)
                    rem_sess = count_remaining_sessions_in_month(e.course_group, e.enrolled_date)
                    if total_sess > 0:
                        sess_price = (e.course_group.monthly_price / Decimal(total_sess)).quantize(Decimal('0.01'))
                        prorated_price = (Decimal(rem_sess) * sess_price).quantize(Decimal('0.01'))
                        import math
                        prorated_price = Decimal(str(math.ceil(prorated_price / Decimal('10')))) * Decimal('10')
                    else:
                        sess_price = Decimal('0.00')
                        prorated_price = Decimal('0.00')
                    details.append({
                        'course_group': e.course_group,
                        'total_sessions': total_sess,
                        'remaining_sessions': rem_sess,
                        'session_price': sess_price,
                        'prorated_price': prorated_price
                    })
        return details
    
    @classmethod
    def generate_next_receipt_number(cls, year=None):
        year = year or timezone.now().year
        prefix = f"REC{year}"

        for _ in range(20):
            with transaction.atomic():
                queryset = cls.objects.filter(receipt_number__startswith=prefix)
                if connection.features.has_select_for_update:
                    queryset = queryset.select_for_update()

                last_payment = queryset.order_by('-receipt_number').first()
                if last_payment:
                    last_num = int(last_payment.receipt_number[-4:])
                else:
                    last_num = 0

                candidate = f"{prefix}{last_num + 1:04d}"
                if not cls.objects.filter(receipt_number=candidate).exists():
                    return candidate

        raise RuntimeError("Unable to generate a unique payment receipt number")

    def save(self, *args, **kwargs):
        if self.month_covered:
            self.month_covered = self.month_covered.replace(day=1)

        if not self.receipt_number:
            for _ in range(20):
                self.receipt_number = self.generate_next_receipt_number()
                try:
                    super().save(*args, **kwargs)
                    return
                except IntegrityError:
                    continue
            raise RuntimeError("Unable to assign a unique payment receipt number")

        super().save(*args, **kwargs)


class Attendance(models.Model):
    """Présence aux cours"""
    student = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name="Élève")
    course_group = models.ForeignKey(CourseGroup, on_delete=models.CASCADE, verbose_name="Groupe")
    session = models.ForeignKey(
        'Session',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='attendances',
        verbose_name="Séance"
    )
    date = models.DateField(verbose_name="Date")
    is_present = models.BooleanField(default=True, verbose_name="Présent")
    notes = models.TextField(blank=True, verbose_name="Notes")
    
    class Meta:
        verbose_name = "Présence"
        verbose_name_plural = "Présences"
        constraints = [
            models.UniqueConstraint(fields=['student', 'course_group', 'date'], name='unique_attendance_per_student_group_date')
        ]
        ordering = ['-date']
        indexes = [
            models.Index(fields=['date']),
            models.Index(fields=['course_group', 'date']),
        ]
    
    def __str__(self):
        status = "✓" if self.is_present else "✗"
        return f"{status} {self.student.name} - {self.course_group.name} - {self.date}"


class Session(models.Model):
    """Instance of a group meeting (used for scheduling & payroll)"""
    STATUS_CHOICES = SessionStatus.choices

    group = models.ForeignKey(CourseGroup, on_delete=models.CASCADE, related_name='sessions')
    schedule = models.ForeignKey(CourseGroupSchedule, on_delete=models.SET_NULL, null=True, blank=True, related_name='sessions')
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    room = models.ForeignKey(
        Room,
        on_delete=models.PROTECT,
        related_name='sessions',
        verbose_name='Salle'
    )
    substitute_teacher = models.ForeignKey(
        Teacher,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='substitute_sessions',
        verbose_name="Enseignant remplaçant"
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=SessionStatus.PLANNED)
    notes = models.TextField(blank=True)
    is_manually_edited = models.BooleanField(default=False, verbose_name="Modifié manuellement")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Session'
        verbose_name_plural = 'Sessions'
        ordering = ['-date', 'start_time']
        indexes = [
            models.Index(fields=['date']),
            models.Index(fields=['status']),
            models.Index(fields=['date', 'status']),
            models.Index(fields=['group', 'date']),
        ]

    def __str__(self):
        return f"{self.group.name} - {self.date} {self.start_time.strftime('%H:%M')}-{self.end_time.strftime('%H:%M')}"

    def clean(self):
        if self.end_time <= self.start_time:
            raise ValidationError('End time must be after start time')
        
        if not self.room_id:
            raise ValidationError('La salle est requise.')

        # 1. Check room conflicts (excluding CANCELLED sessions)
        room_conflicts = Session.objects.filter(date=self.date, room=self.room).exclude(status=SessionStatus.CANCELLED)
        if self.pk:
            room_conflicts = room_conflicts.exclude(pk=self.pk)

        for s in room_conflicts:
            if (self.start_time < s.end_time and self.end_time > s.start_time):
                raise ValidationError(
                    f"La salle '{self.room.name}' est déjà réservée par le groupe '{s.group.name}' "
                    f"de {s.start_time.strftime('%H:%M')} à {s.end_time.strftime('%H:%M')}."
                )

        # 2. Check teacher conflicts (excluding CANCELLED sessions)
        effective_teacher = getattr(self, 'substitute_teacher', None) or (self.group.teacher if self.group else None)
        if effective_teacher:
            teacher_conflicts = Session.objects.filter(date=self.date).exclude(status=SessionStatus.CANCELLED)
            if self.pk:
                teacher_conflicts = teacher_conflicts.exclude(pk=self.pk)
            # Filter where the teacher is either the substitute_teacher or (substitute_teacher is null and primary teacher is effective_teacher)
            teacher_conflicts = teacher_conflicts.filter(
                Q(substitute_teacher=effective_teacher) |
                Q(substitute_teacher__isnull=True, group__teacher=effective_teacher)
            )
            for s in teacher_conflicts:
                if overlaps(self.start_time, self.end_time, s.start_time, s.end_time):
                    raise ValidationError(
                        f"Le professeur '{effective_teacher.name}' est déjà affecté au groupe '{s.group.name}' "
                        f"de {s.start_time.strftime('%H:%M')} à {s.end_time.strftime('%H:%M')}."
                    )

            # Check availability/leave for the session date
            DAY_MAP_REV = {0: 'MON', 1: 'TUE', 2: 'WED', 3: 'THU', 4: 'FRI', 5: 'SAT', 6: 'SUN'}
            day_str = DAY_MAP_REV[self.date.weekday()]
            # check_teacher_availability(effective_teacher, day_str, self.start_time, self.end_time, date_val=self.date)

        # 3. Check group conflicts (excluding CANCELLED sessions)
        if self.group:
            group_conflicts = Session.objects.filter(date=self.date, group=self.group).exclude(status=SessionStatus.CANCELLED)
            if self.pk:
                group_conflicts = group_conflicts.exclude(pk=self.pk)
            for s in group_conflicts:
                if overlaps(self.start_time, self.end_time, s.start_time, s.end_time):
                    raise ValidationError(
                        f"Le groupe '{self.group.name}' a déjà une session planifiée de "
                        f"{s.start_time.strftime('%H:%M')} à {s.end_time.strftime('%H:%M')}."
                    )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def duration_hours(self):
        return duration_hours(self.start_time, self.end_time)

    def get_default_schedule(self):
        """
        Get the regular CourseGroupSchedule matching this session's weekday.
        """
        if not self.group:
            return None
        weekday = get_weekday_code(self.date)
        return self.group.schedules.filter(day=weekday).first()

    def get_exception_type(self):
        """
        Compare the session's details to the default CourseGroupSchedule.
        Returns:
            - 'CANCELLED' if cancelled.
            - 'SUBSTITUTE' if a substitute teacher is assigned.
            - 'DATE' if there is no normal schedule on this weekday.
            - 'ROOM' if room differs.
            - 'TIME' if start or end times differ.
            - None if it matches the default schedule exactly.
        """
        if self.status == SessionStatus.CANCELLED:
            return 'CANCELLED'
        if self.substitute_teacher_id:
            return 'SUBSTITUTE'
        
        default_sch = self.get_default_schedule()
        if not default_sch:
            return 'DATE'
            
        if self.room_id != default_sch.room_id:
            return 'ROOM'
            
        # Standardize times comparison
        t_start = self.start_time.replace(second=0, microsecond=0)
        t_end = self.end_time.replace(second=0, microsecond=0)
        d_start = default_sch.start_time.replace(second=0, microsecond=0)
        d_end = default_sch.end_time.replace(second=0, microsecond=0)
        
        if t_start != d_start or t_end != d_end:
            return 'TIME'
            
        return None

    @property
    def is_exceptional(self):
        """
        Returns True if this session has any deviation from its default schedule.
        """
        return self.get_exception_type() is not None



class Holiday(models.Model):
    """Jour férié ou congé scolaire supprimant des séances"""
    name = models.CharField(
        max_length=200,
        verbose_name="Nom du congé / jour férié"
    )
    date = models.DateField(unique=True, verbose_name="Date")
    affects_all = models.BooleanField(
        default=True,
        verbose_name="Tous les groupes",
        help_text="Si coché, aucun groupe n'a de séance ce jour-là."
    )
    affected_groups = models.ManyToManyField(
        'CourseGroup',
        blank=True,
        related_name='holidays',
        verbose_name="Groupes concernés",
        help_text="Laissez vide si tous les groupes sont concernés (option ci-dessus cochée)."
    )
    notes = models.TextField(blank=True, verbose_name="Notes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Jour férié / Congé"
        verbose_name_plural = "Jours fériés / Congés"
        ordering = ['date']

    def __str__(self):
        scope = "Tous" if self.affects_all else "Groupes sélectionnés"
        return f"{self.name} – {self.date.strftime('%d/%m/%Y')} ({scope})"


class TeacherAvailability(models.Model):
    """Disponibilités hebdomadaires des enseignants"""
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name='availabilities', verbose_name="Enseignant")
    day = models.CharField(max_length=3, choices=CourseGroup.DAYS_CHOICES, verbose_name="Jour")
    start_time = models.TimeField(verbose_name="Heure de début")
    end_time = models.TimeField(verbose_name="Heure de fin")
    is_available = models.BooleanField(default=True, verbose_name="Disponible")

    class Meta:
        verbose_name = "Disponibilité enseignant"
        verbose_name_plural = "Disponibilités enseignants"
        ordering = ['day', 'start_time']

    def clean(self):
        super().clean()
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValidationError("L'heure de fin doit être postérieure à l'heure de début.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        status = "Disponible" if self.is_available else "Indisponible"
        return f"{self.teacher.name} – {self.get_day_display()} {self.start_time.strftime('%H:%M')}-{self.end_time.strftime('%H:%M')} ({status})"


# ==================== SIGNALS ====================
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

@receiver(post_save, sender=CourseGroup)
def sync_course_group_on_save(sender, instance, **kwargs):
    """Automatically syncs future sessions when a CourseGroup is saved"""
    try:
        from .utils import generate_sessions_from_coursegroups
        from datetime import timedelta
        
        today = timezone.now().date()
        max_date = Session.objects.aggregate(Max('date'))['date__max']
        if not max_date or max_date < today:
            max_date = today + timedelta(weeks=4)
            
        generate_sessions_from_coursegroups(today, max_date, force=True, course=instance)
    except Exception:
        logger.exception("Failed to sync sessions after CourseGroup save")


@receiver(post_save, sender=CourseGroupSchedule)
def sync_course_group_schedule_on_save(sender, instance, **kwargs):
    """Automatically syncs future sessions when a CourseGroupSchedule is saved"""
    try:
        from .utils import generate_sessions_from_coursegroups
        from datetime import timedelta
        from django.core.cache import cache
        
        today = timezone.now().date()
        max_date = Session.objects.aggregate(Max('date'))['date__max']
        if not max_date or max_date < today:
            max_date = today + timedelta(weeks=4)
            
        generate_sessions_from_coursegroups(today, max_date, force=True, course=instance.course_group)
        
        # Bust sidebar conflict badge cache so it reflects the new schedule immediately
        cache.delete('sidebar_conflict_count')
    except Exception:
        # Silently fail if database isn't ready
        pass


@receiver(post_delete, sender=CourseGroupSchedule)
def sync_course_group_schedule_on_delete(sender, instance, **kwargs):
    """Automatically syncs future sessions when a CourseGroupSchedule is deleted"""
    try:
        from .utils import generate_sessions_from_coursegroups
        from datetime import timedelta
        from django.core.cache import cache
        
        today = timezone.now().date()
        max_date = Session.objects.aggregate(Max('date'))['date__max']
        if not max_date or max_date < today:
            max_date = today + timedelta(weeks=4)
            
        generate_sessions_from_coursegroups(today, max_date, force=True, course=instance.course_group)
        
        # Bust sidebar conflict badge cache
        cache.delete('sidebar_conflict_count')
    except Exception:
        # Silently fail if database isn't ready
        pass



# ==============================================================================
# WHATSAPP SEND LOG
# ==============================================================================

class WhatsAppSendLog(models.Model):
    """Log of all WhatsApp messages sent via the automation service."""

    MESSAGE_TYPE_CHOICES = [
        ('payment_reminder', 'Rappel de paiement'),
        ('payment_confirmation', 'Confirmation de paiement'),
        ('absence_notification', 'Notification d\'absence'),
        ('session_reminder', 'Rappel de séance'),
        ('bulk_announcement', 'Annonce groupée'),
        ('other', 'Autre'),
    ]

    STATUS_CHOICES = [
        ('SENT', 'Envoyé'),
        ('FAILED', 'Échec'),
    ]

    student = models.ForeignKey(
        'Student',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='whatsapp_logs',
        verbose_name='Élève',
    )
    phone = models.CharField(max_length=30, verbose_name='Téléphone')
    message_type = models.CharField(
        max_length=30,
        choices=MESSAGE_TYPE_CHOICES,
        default='other',
        verbose_name='Type de message',
    )
    message_preview = models.TextField(
        max_length=300,
        blank=True,
        verbose_name='Aperçu du message',
    )
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='SENT',
        verbose_name='Statut',
    )
    error_message = models.TextField(
        blank=True,
        verbose_name='Message d\'erreur',
    )
    sent_at = models.DateTimeField(auto_now_add=True, verbose_name='Envoyé le')

    class Meta:
        verbose_name = 'Journal WhatsApp'
        verbose_name_plural = 'Journal WhatsApp'
        ordering = ['-sent_at']

    def __str__(self):
        student_name = self.student.name if self.student else self.phone
        return f"[{self.get_status_display()}] {self.get_message_type_display()} → {student_name} ({self.sent_at:%d/%m/%Y %H:%M})"


class MakeupSession(models.Model):
    """Suivi des séances de rattrapage"""
    original_session = models.ForeignKey(
        'Session',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='makeup_origins',
        verbose_name="Séance d'origine"
    )
    makeup_session = models.ForeignKey(
        'Session',
        on_delete=models.CASCADE,
        related_name='makeups',
        verbose_name="Séance de rattrapage"
    )
    students = models.ManyToManyField(
        Student,
        blank=True,
        related_name='makeup_sessions',
        verbose_name="Élèves concernés"
    )
    notes = models.TextField(blank=True, verbose_name="Notes")

    class Meta:
        verbose_name = "Séance de rattrapage"
        verbose_name_plural = "Séances de rattrapage"

    def __str__(self):
        orig = f"du {self.original_session.date}" if self.original_session else "inconnue"
        return f"Rattrapage {orig} planifié le {self.makeup_session.date}"


class Announcement(models.Model):
    """General school announcements and upcoming events, with optional target filters."""
    CATEGORY_CHOICES = [
        ('general', 'Annonce générale'),
        ('event', 'Événement à venir'),
    ]
    
    title = models.CharField(max_length=200, verbose_name="Titre")
    content = models.TextField(verbose_name="Contenu")
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        default='general',
        verbose_name="Catégorie"
    )
    event_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Date de l'événement",
        help_text="Requis pour les événements à venir"
    )
    target_levels = models.ManyToManyField(
        Level,
        blank=True,
        related_name='announcements',
        verbose_name="Niveaux cibles",
        help_text="Laissez vide pour afficher à tous les niveaux"
    )
    target_groups = models.ManyToManyField(
        CourseGroup,
        blank=True,
        related_name='announcements',
        verbose_name="Groupes cibles",
        help_text="Laissez vide pour afficher à tous les groupes"
    )
    is_active = models.BooleanField(default=True, verbose_name="Actif")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Annonce / Événement"
        verbose_name_plural = "Annonces & Événements"
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.get_category_display()}] {self.title}"

