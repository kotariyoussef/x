from django.test import TestCase
from datetime import date
from decimal import Decimal
from django.utils import timezone
from .models import Room, Teacher, CourseGroup, Student, Enrollment, Payment, CourseGroupSchedule
from .utils import calculate_enrollment_expected_fee, get_student_payment_status, detect_all_conflicts

class ConflictDetectionTestCase(TestCase):
    def test_detect_all_conflicts_reports_room_and_teacher_conflicts_separately(self):
        room = Room.objects.create(name="Salle A", capacity=2)
        teacher = Teacher.objects.create(
            name="Teacher One",
            phone="0600000000",
            payment_method="PERCENTAGE",
            payment_percentage=Decimal("50.00"),
        )
        course_one = CourseGroup.objects.create(
            name="Math",
            subject="Math",
            monthly_price=Decimal("100.00"),
            teacher=teacher,
        )
        course_two = CourseGroup.objects.create(
            name="Science",
            subject="Science",
            monthly_price=Decimal("100.00"),
            teacher=teacher,
        )

        CourseGroupSchedule.objects.create(
            course_group=course_one,
            day="MON",
            start_time="14:00:00",
            end_time="16:00:00",
            room=room,
        )
        CourseGroupSchedule.objects.create(
            course_group=course_two,
            day="MON",
            start_time="15:00:00",
            end_time="17:00:00",
            room=room,
        )

        result = detect_all_conflicts()

        self.assertEqual(len(result['schedule_conflicts']), 2)
        self.assertTrue(any(conflict['type'] == 'ROOM' for conflict in result['schedule_conflicts']))
        self.assertTrue(any(conflict['type'] == 'TEACHER' for conflict in result['schedule_conflicts']))


class PaymentLogicTestCase(TestCase):
    def setUp(self):
        self.room = Room.objects.create(name="Salle 101", capacity=30)
        self.teacher = Teacher.objects.create(
            name="Teacher John", 
            phone="12345678", 
            payment_method="PERCENTAGE", 
            payment_percentage=Decimal('50.00')
        )
        self.course = CourseGroup.objects.create(
            name="Math 1",
            subject="Math",
            monthly_price=Decimal('1000.00'),
            teacher=self.teacher
        )
        self.schedule = CourseGroupSchedule.objects.create(
            course_group=self.course,
            day="MON",
            start_time="14:00:00",
            end_time="16:00:00",
            room=self.room
        )
        self.student = Student.objects.create(
            name="Student Alice",
            parent_contact="87654321"
        )

    def test_future_enrollment_expected_fee_is_zero(self):
        enrollment = Enrollment.objects.create(
            student=self.student,
            course_group=self.course,
            is_active=True
        )
        Enrollment.objects.filter(pk=enrollment.pk).update(enrolled_date=date(2026, 7, 15))
        enrollment.refresh_from_db()
        
        june_date = date(2026, 6, 1)
        expected_fee = calculate_enrollment_expected_fee(enrollment, june_date)
        self.assertEqual(expected_fee, Decimal('0.00'))

    def test_current_month_prorated_expected_fee(self):
        # Enrollment date mid-month: Oct 19, 2026 (Monday)
        # Mondays in October 2026: Oct 5, 12, 19, 26 (4 total)
        # Remaining from Oct 19: Oct 19, 26 (2 remaining)
        # Expected fee = 2/4 * 1000.00 = 500.00
        enrollment = Enrollment.objects.create(
            student=self.student,
            course_group=self.course,
            is_active=True
        )
        Enrollment.objects.filter(pk=enrollment.pk).update(enrolled_date=date(2026, 10, 19))
        enrollment.refresh_from_db()
        
        october_date = date(2026, 10, 1)
        expected_fee = calculate_enrollment_expected_fee(enrollment, october_date)
        self.assertEqual(expected_fee, Decimal('500.00'))

    def test_get_student_payment_status_historical_month(self):
        enrollment = Enrollment.objects.create(
            student=self.student,
            course_group=self.course,
            is_active=True
        )
        Enrollment.objects.filter(pk=enrollment.pk).update(enrolled_date=date(2026, 5, 1))
        enrollment.refresh_from_db()
        
        may_date = date(2026, 5, 1)
        status = get_student_payment_status(self.student, may_date)
        self.assertEqual(status['required'], Decimal('1000.00'))
        self.assertEqual(status['remaining'], Decimal('1000.00'))
        self.assertEqual(status['status'], 'UNPAID')

    def test_current_month_prorated_expected_fee_rounded_up(self):
        # Course price = 500.00, 4 total mondays in Oct 2026.
        # Oct 12 has 3 remaining. Prorated price = 3 * 125.00 = 375.00
        # Round up to nearest multiple of 10 -> 380.00.
        course = CourseGroup.objects.create(
            name="Math 2",
            subject="Math",
            monthly_price=Decimal('500.00'),
            teacher=self.teacher
        )
        CourseGroupSchedule.objects.create(
            course_group=course,
            day="MON",
            start_time="14:00:00",
            end_time="16:00:00",
            room=self.room
        )
        enrollment = Enrollment.objects.create(
            student=self.student,
            course_group=course,
            is_active=True
        )
        Enrollment.objects.filter(pk=enrollment.pk).update(enrolled_date=date(2026, 10, 12))
        enrollment.refresh_from_db()

        october_date = date(2026, 10, 1)
        expected_fee = calculate_enrollment_expected_fee(enrollment, october_date)
        self.assertEqual(expected_fee, Decimal('380.00'))

    def test_setup_levels_management_command(self):
        from django.core.management import call_command
        from .models import Level
        
        # Clear existing levels
        Level.objects.all().delete()
        
        # Call management command
        call_command('setup_levels')
        
        # Check that levels are correctly created
        self.assertEqual(Level.objects.filter(category__code='GARDERIE').count(), 3)
        self.assertEqual(Level.objects.filter(category__code='PRIMAIRE').count(), 6)
        self.assertEqual(Level.objects.filter(category__code='COLLEGE').count(), 3)
        self.assertEqual(Level.objects.filter(category__code='LYCEE').count(), 3)
        
        # Check specific levels
        self.assertTrue(Level.objects.filter(name='Petite Section (PS)', category__code='GARDERIE').exists())
        self.assertTrue(Level.objects.filter(name='1AP', category__code='PRIMAIRE').exists())
        self.assertTrue(Level.objects.filter(name='3ASC', category__code='COLLEGE').exists())
        self.assertTrue(Level.objects.filter(name='Tronc Commun (TC)', category__code='LYCEE').exists())


