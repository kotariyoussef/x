from unittest.mock import patch
from decimal import Decimal
from django.test import TestCase
from core.models import CourseGroup, Student, Teacher, Enrollment
from core.services.whatsapp import WhatsAppGroupService
from core.utils import WhatsAppUtils

def normalize_phone(phone):
    return WhatsAppUtils.clean_phone_number(phone)

class WhatsAppGroupServiceTestCase(TestCase):
    def setUp(self):
        self.teacher = Teacher.objects.create(
            name="Teacher Test",
            phone="0611223344",
            payment_method="PERCENTAGE",
            payment_percentage=Decimal("50.00")
        )
        self.course_group = CourseGroup.objects.create(
            name="Physique-Chimie",
            subject="Physique",
            monthly_price=Decimal("100.00"),
            teacher=self.teacher
        )
        self.student = Student.objects.create(
            name="Student Test",
            phone="0661234569",
            parent_contact="0661234567",
            parent_contact_2="+212661234568"
        )

    def test_phone_normalization(self):
        self.assertEqual(normalize_phone("0661234567"), "212661234567")
        self.assertEqual(normalize_phone("+212661234567"), "212661234567")
        self.assertEqual(normalize_phone("06 61 23 45 67"), "212661234567")
        self.assertEqual(normalize_phone("invalid"), "")
        self.assertEqual(normalize_phone(""), "")

    def test_group_name_generation(self):
        name = WhatsAppGroupService.generate_group_name(self.course_group)
        self.assertIn("Physique-Chimie", name)

    @patch('core.utils.WhatsAppServiceAPI.get_status')
    @patch('core.utils.WhatsAppServiceAPI.create_group')
    @patch('core.utils.WhatsAppServiceAPI.add_group_participants')
    def test_sync_course_group_creation_and_enrollment(self, mock_add, mock_create, mock_status):
        mock_status.return_value = {"status": "authenticated"}
        mock_create.return_value = {
            "success": True,
            "groupId": "123456@g.us",
            "inviteLink": "https://chat.whatsapp.com/testlink"
        }
        mock_add.return_value = {
            "success": True,
            "results": {
                "212611223344": {"status": 200, "message": "Added"},
                "212661234567": {"status": 200, "message": "Added"},
                "212661234568": {"status": 200, "message": "Added"},
                "212661234569": {"status": 200, "message": "Added"}
            }
        }

        # Create enrollment (signal will run sync_course_group once)
        # Reset group fields to test explicit sync behavior
        Enrollment.objects.create(student=self.student, course_group=self.course_group)
        self.course_group.whatsapp_group_id = ""
        self.course_group.whatsapp_group_link = ""
        self.course_group.save()

        # Sync course group explicitly
        res = WhatsAppGroupService.sync_course_group(self.course_group)

        self.assertTrue(res["success"])
        self.assertTrue(res["group_created"])
        self.assertEqual(res["group_id"], "123456@g.us")
        self.assertEqual(res["group_link"], "https://chat.whatsapp.com/testlink")
        self.assertIn("212611223344", res["added"])
        self.assertIn("212661234567", res["added"])
        self.assertIn("212661234568", res["added"])
        self.assertIn("212661234569", res["added"])

        # Check DB updated
        self.course_group.refresh_from_db()
        self.assertEqual(self.course_group.whatsapp_group_id, "123456@g.us")
        self.assertEqual(self.course_group.whatsapp_group_link, "https://chat.whatsapp.com/testlink")

    @patch('core.utils.WhatsAppServiceAPI.get_status')
    def test_whatsapp_failure_does_not_break_enrollment(self, mock_status):
        mock_status.return_value = {"status": "disconnected"}

        # Attempt to sync on enrollment creation
        enrollment = Enrollment.objects.create(student=self.student, course_group=self.course_group)
        self.assertIsNotNone(enrollment.pk)

        res = WhatsAppGroupService.sync_course_group(self.course_group)
        self.assertFalse(res["success"])
        self.assertIn("offline", res["warnings"][0].lower())

    @patch('core.utils.WhatsAppServiceAPI.get_status')
    @patch('core.utils.WhatsAppServiceAPI.add_group_participants')
    def test_idempotent_sync(self, mock_add, mock_status):
        mock_status.return_value = {"status": "authenticated"}

        self.course_group.whatsapp_group_id = "123456@g.us"
        self.course_group.whatsapp_group_link = "https://chat.whatsapp.com/testlink"
        self.course_group.save()

        mock_add.return_value = {
            "success": True,
            "results": {
                "212611223344": {"status": 409, "message": "Already in group"}
            }
        }

        res = WhatsAppGroupService.sync_course_group(self.course_group)
        self.assertTrue(res["success"])
        self.assertFalse(res["group_created"])
        self.assertIn("212611223344", res["already_members"])

    @patch('core.utils.WhatsAppServiceAPI.send_message')
    @patch('core.utils.WhatsAppServiceAPI.add_group_participants')
    def test_auto_send_invite_link_on_add_failure(self, mock_add, mock_send_msg):
        self.course_group.whatsapp_group_id = "123456@g.us"
        self.course_group.whatsapp_group_link = "https://chat.whatsapp.com/testlink"
        self.course_group.save()

        # Simulate adding failing with status 403 (e.g. privacy restrictions)
        mock_add.return_value = {
            "success": True,
            "results": {
                "212661234567": {"status": 403, "message": "Participant privacy settings prevent direct addition"}
            }
        }
        mock_send_msg.return_value = {"success": True}

        res = WhatsAppGroupService.add_participant(self.course_group, ["212661234567"])

        self.assertTrue(res["success"])
        self.assertIn("212661234567", res["invite_sent"])
        mock_send_msg.assert_called_once()

    @patch('core.utils.WhatsAppServiceAPI.add_group_participants')
    def test_enrollment_signal_auto_adds_participants(self, mock_add):
        self.course_group.whatsapp_group_id = "123456@g.us"
        self.course_group.save()

        mock_add.return_value = {
            "success": True,
            "results": {
                "212661234569": {"status": 200, "message": "Added"},
                "212661234567": {"status": 200, "message": "Added"},
                "212661234568": {"status": 200, "message": "Added"}
            }
        }

        # Creating enrollment fires post_save signal
        Enrollment.objects.create(student=self.student, course_group=self.course_group)

        mock_add.assert_called_once()
        args, kwargs = mock_add.call_args
        added_participants = kwargs.get('participants') or args[1]
        self.assertIn("212661234569", added_participants)
        self.assertIn("212661234567", added_participants)
        self.assertIn("212661234568", added_participants)

    @patch('core.utils.WhatsAppServiceAPI.get_status')
    @patch('core.utils.WhatsAppServiceAPI.remove_group_participants')
    def test_remove_participant_unenrollment(self, mock_remove, mock_status):
        mock_status.return_value = {"status": "authenticated"}

        self.course_group.whatsapp_group_id = "123456@g.us"
        self.course_group.save()

        mock_remove.return_value = {
            "success": True,
            "results": {
                "212661234567": {"status": 200, "message": "Removed"},
                "212661234568": {"status": 200, "message": "Removed"}
            }
        }

        phones = [normalize_phone(self.student.parent_contact), normalize_phone(self.student.parent_contact_2)]
        res = WhatsAppGroupService.remove_participant(self.course_group, phones)
        self.assertTrue(res["success"])
        self.assertIn("212661234567", res["removed"])
        self.assertIn("212661234568", res["removed"])
