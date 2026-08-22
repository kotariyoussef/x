"""
Tests for the WhatsApp Groups & Automation expansion.

Covers:
  - Group targeting / resolve_groups
  - Enqueueing idempotency
  - Dry-run mode
  - Template variable extraction and render
  - Automation trigger engine and cooldowns
  - Typed condition evaluation
  - Health verification (mocked)
  - View endpoint smoke tests
"""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    CourseGroup,
    Level,
    Teacher,
    WhatsAppAutomation,
    WhatsAppAutomationRun,
    WhatsAppGroup,
    WhatsAppMessageJob,
    WhatsAppMessageTemplate,
)
from core.services.group_automation import (
    cancel_job,
    enqueue_group_message,
    evaluate_automation_conditions,
    get_job_progress,
    resolve_groups,
    trigger_automation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_wa_group(name="Test Group", course_group=None, group_type="PARENTS",
                  is_active=True, automation_enabled=True, blocked=False,
                  archived=False, whatsapp_group_id="123456789@g.us"):
    return WhatsAppGroup.objects.create(
        name=name,
        display_name=name,
        whatsapp_group_id=whatsapp_group_id,
        group_type=group_type,
        course_group=course_group,
        is_active=is_active,
        automation_enabled=automation_enabled,
        blocked=blocked,
        archived=archived,
    )


def make_level(name="6eme"):
    return Level.objects.get_or_create(name=name)[0]


def make_course_group(name="Maths 6A", level=None):
    teacher, _ = Teacher.objects.get_or_create(
        name="Prof Test",
        defaults={"phone": "0600000001"},
    )
    return CourseGroup.objects.get_or_create(
        name=name,
        defaults={
            "subject": "Maths",
            "teacher": teacher,
            "level": level,
            "monthly_price": 300,
        },
    )[0]


# ===========================================================================
# 1. resolve_groups
# ===========================================================================

class ResolveGroupsTest(TestCase):
    def setUp(self):
        self.level = make_level("Terminale")
        self.cg = make_course_group("Physique TL", level=self.level)
        self.g1 = make_wa_group("G1", course_group=self.cg, group_type="STUDENTS")
        self.g2 = make_wa_group("G2", group_type="PARENTS", whatsapp_group_id="aaaaa@g.us")
        self.g_inactive = make_wa_group(
            "G-Inactive", is_active=False, whatsapp_group_id="inactive@g.us"
        )
        self.g_blocked = make_wa_group(
            "G-Blocked", blocked=True, whatsapp_group_id="blocked@g.us"
        )

    def test_all_groups_excludes_inactive_and_blocked(self):
        groups = resolve_groups("ALL_GROUPS", None)
        ids = [g.pk for g in groups]
        self.assertIn(self.g1.pk, ids)
        self.assertIn(self.g2.pk, ids)
        self.assertNotIn(self.g_inactive.pk, ids)
        self.assertNotIn(self.g_blocked.pk, ids)

    def test_group_type_filter(self):
        groups = resolve_groups("GROUP_TYPE", "STUDENTS")
        ids = [g.pk for g in groups]
        self.assertIn(self.g1.pk, ids)
        self.assertNotIn(self.g2.pk, ids)

    def test_course_filter(self):
        groups = resolve_groups("COURSE", self.cg.pk)
        ids = [g.pk for g in groups]
        self.assertIn(self.g1.pk, ids)
        self.assertNotIn(self.g2.pk, ids)

    def test_level_filter(self):
        groups = resolve_groups("LEVEL", self.level.pk)
        ids = [g.pk for g in groups]
        self.assertIn(self.g1.pk, ids)

    def test_group_ids_filter(self):
        groups = resolve_groups("GROUP_IDS", str(self.g2.pk))
        ids = [g.pk for g in groups]
        self.assertIn(self.g2.pk, ids)
        self.assertNotIn(self.g1.pk, ids)

    def test_unknown_target_type_returns_empty(self):
        groups = resolve_groups("UNKNOWN_TYPE", None)
        self.assertEqual(len(groups), 0)


# ===========================================================================
# 2. Enqueueing & Idempotency
# ===========================================================================

class EnqueueGroupMessageTest(TestCase):
    def setUp(self):
        self.g = make_wa_group()

    def test_creates_job_and_delivery(self):
        result = enqueue_group_message(
            target_type="ALL_GROUPS",
            target_value=None,
            message="Hello everyone",
            source_event="test",
        )
        self.assertEqual(result["status"], "queued")
        self.assertGreater(result["deliveries_created"], 0)
        self.assertIsNotNone(result.get("job_id"))

    def test_idempotency_prevents_duplicate(self):
        kwargs = dict(
            target_type="ALL_GROUPS",
            target_value=None,
            message="Hello everyone",
            source_event="test",
        )
        r1 = enqueue_group_message(**kwargs)
        r2 = enqueue_group_message(**kwargs)
        self.assertEqual(r1["job_id"], r2["job_id"])
        self.assertEqual(r2["status"], "already_queued")

    def test_dry_run_does_not_persist(self):
        result = enqueue_group_message(
            target_type="ALL_GROUPS",
            target_value=None,
            message="Dry test",
            source_event="test",
            dry_run=True,
        )
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(WhatsAppMessageJob.objects.count(), 0)

    def test_no_matching_groups_returns_no_targets(self):
        result = enqueue_group_message(
            target_type="GROUP_TYPE",
            target_value="NONEXISTENT",
            message="No one",
            source_event="test",
        )
        self.assertEqual(result["status"], "no_targets")


# ===========================================================================
# 3. Job Progress & Cancel
# ===========================================================================

class JobProgressTest(TestCase):
    def test_get_progress_for_nonexistent_job(self):
        result = get_job_progress(99999)
        self.assertIn("error", result)

    def test_cancel_nonexistent_job(self):
        result = cancel_job(99999)
        self.assertIn("error", result)

    def test_cancel_pending_job(self):
        make_wa_group()
        r = enqueue_group_message(
            target_type="ALL_GROUPS",
            target_value=None,
            message="Cancel me",
            source_event="cancel-test",
        )
        job_id = r["job_id"]
        cancel_result = cancel_job(job_id)
        self.assertEqual(cancel_result["status"], "cancelled")
        job = WhatsAppMessageJob.objects.get(pk=job_id)
        self.assertEqual(job.status, "CANCELLED")


# ===========================================================================
# 4. Template Variable Extraction and Render
# ===========================================================================

class MessageTemplateTest(TestCase):
    def test_extract_variables_basic(self):
        t = WhatsAppMessageTemplate(
            name="Test",
            body="Bonjour {{student_name}}, votre solde est {{amount}} DH.",
        )
        vars_ = t.extract_variables()
        self.assertIn("student_name", vars_)
        self.assertIn("amount", vars_)

    def test_extract_variables_no_vars(self):
        t = WhatsAppMessageTemplate(name="Static", body="Pas de variables.")
        self.assertEqual(t.extract_variables(), [])

    def test_render_fills_variables(self):
        t = WhatsAppMessageTemplate(
            name="Test",
            body="Bonjour {{student_name}}, vous devez {{amount}} DH.",
        )
        rendered = t.render({"student_name": "Ali", "amount": "500"})
        self.assertIn("Ali", rendered)
        self.assertIn("500", rendered)

    def test_render_leaves_missing_vars(self):
        t = WhatsAppMessageTemplate(
            name="Test",
            body="Bonjour {{student_name}}.",
        )
        rendered = t.render({})
        self.assertIn("{{student_name}}", rendered)


# ===========================================================================
# 5. Automation Condition Evaluation
# ===========================================================================

class ConditionEvaluationTest(TestCase):
    def test_empty_conditions_always_pass(self):
        automation = WhatsAppAutomation(conditions=[])
        self.assertTrue(evaluate_automation_conditions(automation, {}))

    def test_equals_condition_pass(self):
        automation = WhatsAppAutomation(
            conditions=[{"field": "level", "op": "equals", "value": "Terminale"}]
        )
        self.assertTrue(
            evaluate_automation_conditions(automation, {"level": "Terminale"})
        )

    def test_equals_condition_fail(self):
        automation = WhatsAppAutomation(
            conditions=[{"field": "level", "op": "equals", "value": "Terminale"}]
        )
        self.assertFalse(
            evaluate_automation_conditions(automation, {"level": "Primaire"})
        )

    def test_contains_condition_pass(self):
        automation = WhatsAppAutomation(
            conditions=[{"field": "subject", "op": "contains", "value": "Math"}]
        )
        self.assertTrue(
            evaluate_automation_conditions(automation, {"subject": "Mathematiques"})
        )

    def test_contains_condition_fail(self):
        automation = WhatsAppAutomation(
            conditions=[{"field": "subject", "op": "contains", "value": "Physics"}]
        )
        self.assertFalse(
            evaluate_automation_conditions(automation, {"subject": "Mathematiques"})
        )

    def test_gt_condition_pass(self):
        automation = WhatsAppAutomation(
            conditions=[{"field": "count", "op": "gt", "value": "3"}]
        )
        self.assertTrue(evaluate_automation_conditions(automation, {"count": 5}))

    def test_gt_condition_fail(self):
        automation = WhatsAppAutomation(
            conditions=[{"field": "count", "op": "gt", "value": "3"}]
        )
        self.assertFalse(evaluate_automation_conditions(automation, {"count": 2}))

    def test_multiple_conditions_all_must_pass(self):
        automation = WhatsAppAutomation(
            conditions=[
                {"field": "level", "op": "equals", "value": "Terminale"},
                {"field": "count", "op": "gt", "value": "0"},
            ]
        )
        self.assertTrue(
            evaluate_automation_conditions(
                automation, {"level": "Terminale", "count": 1}
            )
        )
        self.assertFalse(
            evaluate_automation_conditions(
                automation, {"level": "Terminale", "count": 0}
            )
        )


# ===========================================================================
# 6. Automation Trigger & Cooldown
# ===========================================================================

class TriggerAutomationTest(TestCase):
    def setUp(self):
        self.group = make_wa_group()
        self.template = WhatsAppMessageTemplate.objects.create(
            name="Absence notif",
            body="Absence de {{student_name}} signalee.",
        )
        self.automation = WhatsAppAutomation.objects.create(
            name="Absence Auto",
            trigger_event="STUDENT_ABSENT",
            target_type="ALL_GROUPS",
            target_value="",
            message_template=self.template,
            is_active=True,
            cooldown_minutes=60,
            conditions=[],
        )

    def test_trigger_creates_audit_run(self):
        with patch(
            "core.services.group_automation.enqueue_group_message",
            return_value={"status": "queued", "job_id": 1, "deliveries_created": 1},
        ):
            trigger_automation(
                self.automation,
                context={"student_name": "Sara"},
                source_event="STUDENT_ABSENT:123",
            )
        run = WhatsAppAutomationRun.objects.filter(automation=self.automation).first()
        self.assertIsNotNone(run)

    def test_cooldown_prevents_second_trigger(self):
        WhatsAppAutomationRun.objects.create(
            automation=self.automation,
            trigger_event="STUDENT_ABSENT",
            status="SUCCESS",
            triggered_at=timezone.now() - timedelta(minutes=10),
        )
        with patch(
            "core.services.group_automation.enqueue_group_message"
        ) as mock_enqueue:
            trigger_automation(
                self.automation,
                context={"student_name": "Sara"},
                source_event="STUDENT_ABSENT:124",
            )
            mock_enqueue.assert_not_called()

    def test_inactive_automation_not_triggered(self):
        self.automation.is_active = False
        self.automation.save()
        with patch(
            "core.services.group_automation.enqueue_group_message"
        ) as mock_enqueue:
            trigger_automation(
                self.automation,
                context={},
                source_event="STUDENT_ABSENT:125",
            )
            mock_enqueue.assert_not_called()


# ===========================================================================
# 7. Health Verification (mocked)
# ===========================================================================

class HealthVerificationTest(TestCase):
    def setUp(self):
        self.group = make_wa_group()

    @patch("core.services.group_automation.WhatsAppServiceAPI")
    def test_verify_health_marks_healthy(self, MockAPI):
        instance = MockAPI.return_value
        instance.get_group_info.return_value = {
            "id": "123456789@g.us",
            "name": "Test Group",
            "participants": [{"id": "213600000001@c.us"}],
        }
        from core.services.group_automation import verify_group_health
        result = verify_group_health(self.group)
        self.assertTrue(result["healthy"])

    @patch("core.services.group_automation.WhatsAppServiceAPI")
    def test_verify_health_marks_unhealthy_on_error(self, MockAPI):
        instance = MockAPI.return_value
        instance.get_group_info.side_effect = Exception("Connection refused")
        from core.services.group_automation import verify_group_health
        result = verify_group_health(self.group)
        self.assertFalse(result["healthy"])


# ===========================================================================
# 8. View Smoke Tests (authenticated)
# ===========================================================================

class WhatsAppViewSmokeTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username="admin_test", password="testpass123"
        )
        self.client = Client()
        self.client.login(username="admin_test", password="testpass123")
        self.wa_group = make_wa_group()
        self.template = WhatsAppMessageTemplate.objects.create(
            name="Test Template",
            body="Hello {{name}}",
        )
        self.automation = WhatsAppAutomation.objects.create(
            name="Test Auto",
            trigger_event="STUDENT_ABSENT",
            target_type="ALL_GROUPS",
            target_value="",
            message_template=self.template,
            is_active=True,
            cooldown_minutes=0,
            conditions=[],
        )

    def _get(self, url_name, *args):
        url = reverse(f"core:{url_name}", args=args if args else None)
        return self.client.get(url)

    def test_whatsapp_groups_list(self):
        self.assertEqual(self._get("whatsapp_groups").status_code, 200)

    def test_whatsapp_group_detail(self):
        self.assertEqual(self._get("whatsapp_group_detail", self.wa_group.pk).status_code, 200)

    def test_whatsapp_group_edit(self):
        self.assertEqual(self._get("whatsapp_group_edit", self.wa_group.pk).status_code, 200)

    def test_whatsapp_group_send(self):
        self.assertEqual(self._get("whatsapp_group_send").status_code, 200)

    def test_whatsapp_group_discover(self):
        self.assertEqual(self._get("whatsapp_group_discover").status_code, 200)

    def test_whatsapp_templates_list(self):
        self.assertEqual(self._get("whatsapp_templates").status_code, 200)

    def test_whatsapp_template_create(self):
        self.assertEqual(self._get("whatsapp_template_create").status_code, 200)

    def test_whatsapp_template_edit(self):
        self.assertEqual(self._get("whatsapp_template_edit", self.template.pk).status_code, 200)

    def test_whatsapp_automations_list(self):
        self.assertEqual(self._get("whatsapp_automations").status_code, 200)

    def test_whatsapp_automation_create(self):
        self.assertEqual(self._get("whatsapp_automation_create").status_code, 200)

    def test_whatsapp_automation_edit(self):
        self.assertEqual(self._get("whatsapp_automation_edit", self.automation.pk).status_code, 200)

    def test_whatsapp_automation_runs(self):
        self.assertEqual(self._get("whatsapp_automation_runs", self.automation.pk).status_code, 200)

    def test_whatsapp_history(self):
        self.assertEqual(self._get("whatsapp_history").status_code, 200)

    def test_whatsapp_group_job_nonexistent(self):
        self.assertEqual(self._get("whatsapp_group_job", 99999).status_code, 404)
