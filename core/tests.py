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

    def test_student_helper_generates_matricule_with_year_prefix(self):
        matricule = Student.generate_next_matricule()
        self.assertTrue(matricule.startswith("M26-"))

    def test_payment_helper_generates_unique_receipt_numbers(self):
        first_receipt = Payment.generate_next_receipt_number(2026)
        Payment.objects.create(
            student=self.student,
            amount=Decimal("100.00"),
            payment_date=date(2026, 7, 1),
            month_covered=date(2026, 7, 1),
            receipt_number=first_receipt,
        )
        second_receipt = Payment.generate_next_receipt_number(2026)

        self.assertTrue(first_receipt.startswith("REC2026"))
        self.assertTrue(second_receipt.startswith("REC2026"))
        self.assertTrue(int(first_receipt[-4:]) < int(second_receipt[-4:]))

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
        alternate_room = Room.objects.create(name="Salle 102", capacity=20)
        alternate_teacher = Teacher.objects.create(
            name="Teacher Two",
            phone="0600000001",
            payment_method="PERCENTAGE",
            payment_percentage=Decimal("50.00"),
        )
        course.refresh_from_db()
        course.teacher = alternate_teacher
        course.save(update_fields=['teacher'])
        CourseGroupSchedule.objects.create(
            course_group=course,
            day="MON",
            start_time="14:00:00",
            end_time="16:00:00",
            room=alternate_room
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


class KioskSearchTestCase(TestCase):
    """Tests for Parent Kiosk search logic and session security."""

    def setUp(self):
        self.teacher = Teacher.objects.create(
            name="Prof Test",
            phone="0600000000",
            payment_method="PERCENTAGE",
            payment_percentage=Decimal("50.00"),
        )
        self.student_a = Student.objects.create(
            name="Alice Benali",
            parent_contact="0612345678",
            parent_name="Fatima Benali",
            is_active=True,
        )
        self.student_b = Student.objects.create(
            name="Bilal Benali",
            parent_contact="0612345678",   # Same parent phone — sibling
            parent_name="Fatima Benali",
            is_active=True,
        )
        self.student_c = Student.objects.create(
            name="Chaimae Karimi",
            parent_contact="0698765432",
            parent_name="Said Karimi",
            is_active=True,
        )

    # ── Home page loads without login ────────────────────────────────
    def test_kiosk_home_accessible_without_login(self):
        response = self.client.get('/public/kiosk/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rechercher votre enfant")

    # ── Matricule search → single student ───────────────────────────
    def test_search_by_matricule_redirects_to_student(self):
        response = self.client.post('/public/kiosk/search/', {
            'search_query': self.student_c.matricule,
        })
        self.assertRedirects(response, '/public/kiosk/student/', fetch_redirect_response=False)
        self.assertEqual(self.client.session['kiosk_student_id'], self.student_c.id)

    def test_search_by_matricule_case_insensitive(self):
        response = self.client.post('/public/kiosk/search/', {
            'search_query': self.student_c.matricule.lower(),
        })
        self.assertRedirects(response, '/public/kiosk/student/', fetch_redirect_response=False)

    # ── Phone search → single match ──────────────────────────────────
    def test_search_by_phone_single_match_redirects_to_student(self):
        response = self.client.post('/public/kiosk/search/', {
            'search_query': self.student_c.parent_contact,
        })
        self.assertRedirects(response, '/public/kiosk/student/', fetch_redirect_response=False)
        self.assertEqual(self.client.session['kiosk_student_id'], self.student_c.id)

    # ── Phone search → multiple siblings ────────────────────────────
    def test_search_by_phone_multiple_matches_redirects_to_select(self):
        response = self.client.post('/public/kiosk/search/', {
            'search_query': self.student_a.parent_contact,
        })
        self.assertRedirects(response, '/public/kiosk/select/', fetch_redirect_response=False)
        matched = self.client.session['kiosk_search_matches']
        self.assertIn(self.student_a.id, matched)
        self.assertIn(self.student_b.id, matched)

    # ── No match → redirect home with error ─────────────────────────
    def test_search_no_match_redirects_home(self):
        response = self.client.post('/public/kiosk/search/', {
            'search_query': '0699999999',
        })
        self.assertRedirects(response, '/public/kiosk/', fetch_redirect_response=False)

    # ── Select page requires session ─────────────────────────────────
    def test_select_without_session_redirects_home(self):
        response = self.client.get('/public/kiosk/select/')
        self.assertRedirects(response, '/public/kiosk/', fetch_redirect_response=False)

    # ── Select student validates session whitelist ────────────────────
    def test_select_student_not_in_session_rejected(self):
        # Seed a session with only student_a and student_b
        session = self.client.session
        session['kiosk_search_matches'] = [self.student_a.id, self.student_b.id]
        session.save()

        # Attempt to select student_c (not in the match list)
        response = self.client.get(f'/public/kiosk/select/{self.student_c.id}/')
        self.assertRedirects(response, '/public/kiosk/', fetch_redirect_response=False)
        self.assertNotIn('kiosk_student_id', self.client.session)

    # ── Valid selection from whitelist ────────────────────────────────
    def test_select_student_in_session_succeeds(self):
        session = self.client.session
        session['kiosk_search_matches'] = [self.student_a.id, self.student_b.id]
        session.save()

        response = self.client.get(f'/public/kiosk/select/{self.student_a.id}/')
        self.assertRedirects(response, '/public/kiosk/student/', fetch_redirect_response=False)
        self.assertEqual(self.client.session['kiosk_student_id'], self.student_a.id)
        self.assertNotIn('kiosk_search_matches', self.client.session)

    # ── Student detail page requires session ──────────────────────────
    def test_student_page_without_session_redirects_home(self):
        response = self.client.get('/public/kiosk/student/')
        self.assertRedirects(response, '/public/kiosk/', fetch_redirect_response=False)

    # ── Student detail page renders correctly ─────────────────────────
    def test_student_page_renders_with_valid_session(self):
        session = self.client.session
        session['kiosk_student_id'] = self.student_c.id
        session.save()

        response = self.client.get('/public/kiosk/student/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Chaimae Karimi")
        self.assertContains(response, self.student_c.matricule)

    # ── Clear wipes session keys ──────────────────────────────────────
    def test_clear_removes_session_and_redirects_home(self):
        session = self.client.session
        session['kiosk_student_id'] = self.student_c.id
        session['kiosk_search_matches'] = [self.student_a.id]
        session.save()

        response = self.client.get('/public/kiosk/clear/')
        self.assertRedirects(response, '/public/kiosk/', fetch_redirect_response=False)
        self.assertNotIn('kiosk_student_id', self.client.session)
        self.assertNotIn('kiosk_search_matches', self.client.session)

    # ── Inactive student not matched ──────────────────────────────────
    def test_inactive_student_not_found_in_search(self):
        inactive = Student.objects.create(
            name="Inactive Child",
            parent_contact="0611112222",
            is_active=False,
        )
        response = self.client.post('/public/kiosk/search/', {
            'search_query': inactive.parent_contact,
        })
        self.assertRedirects(response, '/public/kiosk/', fetch_redirect_response=False)



