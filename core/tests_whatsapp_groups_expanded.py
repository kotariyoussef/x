"""
Tests for the WhatsApp Groups & Automation expansion.

Covers:
  - Group targeting / resolve_groups
  - Enqueueing idempotency and dry-run
  - Template variable extraction and render
  - Automation trigger engine (trigger_automation) with cooldown
  - Typed condition evaluation (evaluate_automation_conditions)
  - Health verification (mocked)
  - View endpoint smoke tests
"""

from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    CourseGroup,
    Level,
    LevelCategory,
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
    verify_group_health,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def make_template(name="Notif", body="Bonjour {{student_name}}."):
    return WhatsAppMessageTemplate.objects.create(name=name, body=body)


def make_wa_group(display_name="Test Group", course_group=None,
                  group_type="PARENTS", is_active=True,
                  automation_enabled=True, blocked=False, archived=False,
                  whatsapp_group_id="123456789@g.us"):
    return WhatsAppGroup.objects.create(
        display_name=display_name,
        whatsapp_group_id=whatsapp_group_id,
        group_type=group_type,
        course_group=course_group,
        is_active=is_active,
        automation_enabled=automation_enabled,
        blocked=blocked,
        archived=archived,
    )


def make_level(name="6eme"):
    cat, _ = LevelCategory.objects.get_or_create(name="Général")
    return Level.objects.get_or_create(name=name, defaults={"category": cat})[0]


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


def make_automation(trigger="STUDENT_ABSENT", enabled=True,
                    cooldown_seconds=0, conditions=None):
    template = make_template(name=f"Template-{trigger}")
    return WhatsAppAutomation.objects.create(
        name=f"Auto-{trigger}",
        trigger=trigger,
        target_type="ALL_GROUPS",
        target_value="",
        template=template,
        enabled=enabled,
        cooldown_seconds=cooldown_seconds,
        conditions=conditions or {},
    )


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
#    Real return: {'job': <obj>, 'created': bool, 'group_count': N, 'groups': [...]}
#    dry_run return: {'dry_run': True, 'group_count': N, 'groups': [...], 'message_preview': ...}
# ===========================================================================

class EnqueueGroupMessageTest(TestCase):
    def setUp(self):
        self.g = make_wa_group()

    def test_creates_job(self):
        result = enqueue_group_message(
            target_type="ALL_GROUPS",
            target_value=None,
            message="Hello everyone",
            source_event="test",
        )
        self.assertTrue(result["created"])
        self.assertIn("job", result)
        self.assertGreater(result["group_count"], 0)

    def test_idempotency_prevents_duplicate(self):
        kwargs = dict(
            target_type="ALL_GROUPS",
            target_value=None,
            message="Hello everyone",
            source_event="test",
        )
        r1 = enqueue_group_message(**kwargs)
        r2 = enqueue_group_message(**kwargs)
        self.assertEqual(r1["job"].pk, r2["job"].pk)
        self.assertFalse(r2["created"])  # second call: not created

    def test_dry_run_does_not_persist(self):
        result = enqueue_group_message(
            target_type="ALL_GROUPS",
            target_value=None,
            message="Dry test",
            source_event="test",
            dry_run=True,
        )
        self.assertTrue(result["dry_run"])
        self.assertEqual(WhatsAppMessageJob.objects.count(), 0)

    def test_no_matching_groups_returns_empty_list(self):
        # GROUP_TYPE "STUDENTS" doesn't exist in DB
        result = enqueue_group_message(
            target_type="GROUP_TYPE",
            target_value="NONEXISTENT_TYPE_XYZ",
            message="No one",
            source_event="test",
        )
        self.assertEqual(result["group_count"], 0)


# ===========================================================================
# 3. Job Progress & Cancel
#    cancel_job returns bool; get_job_progress returns dict with 'error' on miss
# ===========================================================================

class JobProgressTest(TestCase):
    def test_get_progress_for_nonexistent_job(self):
        result = get_job_progress(99999)
        self.assertIn("error", result)

    def test_cancel_nonexistent_job_returns_false(self):
        result = cancel_job(99999)
        self.assertFalse(result)

    def test_cancel_pending_job_returns_true(self):
        make_wa_group()
        r = enqueue_group_message(
            target_type="ALL_GROUPS",
            target_value=None,
            message="Cancel me",
            source_event="cancel-test",
        )
        job_id = r["job"].pk
        result = cancel_job(job_id)
        self.assertTrue(result)
        job = WhatsAppMessageJob.objects.get(pk=job_id)
        self.assertEqual(job.status, "CANCELLED")


# ===========================================================================
# 4. Template Variable Extraction and Render
#    render() returns (rendered_text, missing_vars_list)
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
        rendered, missing = t.render({"student_name": "Ali", "amount": "500"})
        self.assertIn("Ali", rendered)
        self.assertIn("500", rendered)
        self.assertEqual(missing, [])

    def test_render_reports_missing_vars(self):
        t = WhatsAppMessageTemplate(name="Test", body="Bonjour {{student_name}}.")
        rendered, missing = t.render({})
        self.assertIn("student_name", missing)

    def test_render_replaces_single_brace(self):
        t = WhatsAppMessageTemplate(name="Test", body="Hello {name}.")
        rendered, missing = t.render({"name": "Sara"})
        self.assertIn("Sara", rendered)
        self.assertEqual(missing, [])


# ===========================================================================
# 5. Automation Condition Evaluation
#    evaluate_automation_conditions(conditions_dict, context_dict) -> (bool, str)
#    Key: always mock WhatsAppServiceAPI.get_status so require_whatsapp_ready passes
# ===========================================================================

MOCK_READY_STATUS = {"status": "READY", "offline": False}


class ConditionEvaluationTest(TestCase):
    def _eval(self, conditions, context):
        """Helper that mocks WhatsApp status so require_whatsapp_ready doesn't interfere."""
        with patch(
            "core.services.group_automation.WhatsAppServiceAPI.get_status",
            return_value=MOCK_READY_STATUS,
        ):
            return evaluate_automation_conditions(conditions, context)

    def test_empty_dict_always_passes(self):
        passed, _ = self._eval({}, {})
        self.assertTrue(passed)

    def test_none_conditions_passes(self):
        passed, _ = self._eval(None, {})
        self.assertTrue(passed)

    def test_min_amount_passes_when_sufficient(self):
        passed, _ = self._eval({"min_amount": "100"}, {"amount": 500})
        self.assertTrue(passed)

    def test_min_amount_fails_when_below_threshold(self):
        passed, reason = self._eval({"min_amount": "500"}, {"amount": 50})
        self.assertFalse(passed)
        self.assertIn("seuil", reason)

    def test_level_ids_whitelist_passes(self):
        passed, _ = self._eval({"level_ids": [1, 2, 3]}, {"level_id": 2})
        self.assertTrue(passed)

    def test_level_ids_whitelist_fails(self):
        passed, _ = self._eval({"level_ids": [1, 2]}, {"level_id": 99})
        self.assertFalse(passed)

    def test_only_active_students_passes_for_active(self):
        class FakeStudent:
            is_active = True
        passed, _ = self._eval(
            {"only_active_students": True},
            {"student": FakeStudent()},
        )
        self.assertTrue(passed)

    def test_only_active_students_blocks_inactive(self):
        class FakeStudent:
            is_active = False
        passed, reason = self._eval(
            {"only_active_students": True},
            {"student": FakeStudent()},
        )
        self.assertFalse(passed)

    def test_require_whatsapp_not_ready_blocks(self):
        """Without mocking, an offline WhatsApp should block."""
        with patch(
            "core.services.group_automation.WhatsAppServiceAPI.get_status",
            return_value={"status": "LOADING", "offline": True},
        ):
            passed, reason = evaluate_automation_conditions(
                {"require_whatsapp_ready": True}, {}
            )
        self.assertFalse(passed)


# ===========================================================================
# 6. Automation Trigger & Cooldown
# ===========================================================================

class TriggerAutomationTest(TestCase):
    def setUp(self):
        make_wa_group()  # Need at least one eligible group

    def test_trigger_creates_audit_run(self):
        auto = make_automation(trigger="STUDENT_ABSENT", enabled=True)
        job = WhatsAppMessageJob.objects.create(
            target_type="ALL_GROUPS",
            message="Test",
            idempotency_key="test-job-key-123",
            correlation_id="corr-123",
        )
        with patch(
            "core.services.group_automation.enqueue_group_message",
            return_value={"job": job, "created": True, "group_count": 1},
        ):
            with patch(
                "core.services.group_automation.WhatsAppServiceAPI.get_status",
                return_value=MOCK_READY_STATUS,
            ):
                trigger_automation("STUDENT_ABSENT", context={"student_name": "Sara"})
        run = WhatsAppAutomationRun.objects.filter(automation=auto).first()
        self.assertIsNotNone(run)
        self.assertEqual(run.status, "SUCCESS")

    def test_cooldown_prevents_repeated_trigger(self):
        auto = make_automation(
            trigger="PAYMENT_RECEIVED",
            enabled=True,
            cooldown_seconds=3600,
        )
        auto.last_run_at = timezone.now() - timezone.timedelta(minutes=5)
        auto.save(update_fields=["last_run_at"])

        with patch(
            "core.services.group_automation.enqueue_group_message"
        ) as mock_enqueue:
            trigger_automation("PAYMENT_RECEIVED", context={})
            mock_enqueue.assert_not_called()

        skipped = WhatsAppAutomationRun.objects.filter(
            automation=auto, status="SKIPPED"
        ).first()
        self.assertIsNotNone(skipped)

    def test_disabled_automation_not_triggered(self):
        auto = make_automation(trigger="ANNOUNCEMENT_PUBLISHED", enabled=False)
        with patch(
            "core.services.group_automation.enqueue_group_message"
        ) as mock_enqueue:
            trigger_automation("ANNOUNCEMENT_PUBLISHED", context={})
            mock_enqueue.assert_not_called()

    def test_missing_template_vars_results_in_failed_run(self):
        auto = make_automation(trigger="STUDENT_ABSENT", enabled=True)
        auto.template.body = "Dear {{student_name}}"
        auto.template.save()
        with patch(
            "core.services.group_automation.WhatsAppServiceAPI.get_status",
            return_value=MOCK_READY_STATUS,
        ):
            trigger_automation("STUDENT_ABSENT", context={})
        failed_run = WhatsAppAutomationRun.objects.filter(
            automation=auto, status="FAILED"
        ).first()
        self.assertIsNotNone(failed_run)


# ===========================================================================
# 7. Health Verification (mocked WhatsAppServiceAPI)
# ===========================================================================

class HealthVerificationTest(TestCase):
    def setUp(self):
        self.group = make_wa_group()

    @patch("core.services.group_automation.WhatsAppServiceAPI")
    def test_verify_health_marks_healthy(self, MockAPI):
        MockAPI.get_group_info.return_value = {
            "success": True,
            "id": "123456789@g.us",
            "name": "Test Group",
            "participants": [{"id": "213600000001@c.us"}],
        }
        result = verify_group_health(self.group)
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "HEALTHY")
        self.group.refresh_from_db()
        self.assertEqual(self.group.health_status, "HEALTHY")

    @patch("core.services.group_automation.WhatsAppServiceAPI")
    def test_verify_health_marks_unhealthy_on_error(self, MockAPI):
        MockAPI.get_group_info.side_effect = Exception("Connection refused")
        result = verify_group_health(self.group)
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "ERROR")
        self.group.refresh_from_db()
        self.assertEqual(self.group.health_status, "ERROR")


# ===========================================================================
# 8. View Smoke Tests (authenticated superuser)
# ===========================================================================

class WhatsAppViewSmokeTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username="admin_test", password="testpass123"
        )
        self.client = Client()
        self.client.login(username="admin_test", password="testpass123")
        self.wa_group = make_wa_group()
        self.template = make_template(name="View Test Template")
        self.automation = make_automation(trigger="MANUAL")

    def _get(self, url_name, *args):
        url = reverse(f"core:{url_name}", args=args if args else None)
        return self.client.get(url)

    def test_whatsapp_groups_list(self):
        self.assertEqual(self._get("whatsapp_groups").status_code, 200)

    def test_whatsapp_group_detail(self):
        self.assertEqual(
            self._get("whatsapp_group_detail", self.wa_group.pk).status_code, 200
        )

    def test_whatsapp_group_edit(self):
        self.assertEqual(
            self._get("whatsapp_group_edit", self.wa_group.pk).status_code, 200
        )

    def test_whatsapp_group_send(self):
        self.assertEqual(self._get("whatsapp_group_send").status_code, 200)

    def test_whatsapp_group_discover(self):
        self.assertEqual(self._get("whatsapp_group_discover").status_code, 200)

    def test_whatsapp_templates_list(self):
        self.assertEqual(self._get("whatsapp_templates").status_code, 200)

    def test_whatsapp_template_create(self):
        self.assertEqual(self._get("whatsapp_template_create").status_code, 200)

    def test_whatsapp_template_edit(self):
        self.assertEqual(
            self._get("whatsapp_template_edit", self.template.pk).status_code, 200
        )

    def test_whatsapp_automations_list(self):
        self.assertEqual(self._get("whatsapp_automations").status_code, 200)

    def test_whatsapp_automation_create(self):
        self.assertEqual(self._get("whatsapp_automation_create").status_code, 200)

    def test_whatsapp_automation_edit(self):
        self.assertEqual(
            self._get("whatsapp_automation_edit", self.automation.pk).status_code, 200
        )

    def test_whatsapp_automation_runs(self):
        self.assertEqual(
            self._get("whatsapp_automation_runs", self.automation.pk).status_code, 200
        )

    def test_whatsapp_history(self):
        self.assertEqual(self._get("whatsapp_history").status_code, 200)

    def test_whatsapp_group_job_nonexistent_returns_404(self):
        self.assertEqual(self._get("whatsapp_group_job", 99999).status_code, 404)
