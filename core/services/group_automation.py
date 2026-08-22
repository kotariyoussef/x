"""Authorized WhatsApp group targeting, serialized delivery jobs, automation engine, and group health management."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.models import (
    CourseGroup,
    Level,
    WhatsAppAutomation,
    WhatsAppAutomationRun,
    WhatsAppGroup,
    WhatsAppMessageDelivery,
    WhatsAppMessageJob,
    WhatsAppMessageTemplate,
)
from core.utils import WhatsAppServiceAPI
from core.whatsapp_logging import hash_identifier, log_event, new_correlation_id, safe_error

logger = logging.getLogger(__name__)


# ── 1. Group Resolution & Targeting ──────────────────────────────────────────

def resolve_groups(target_type: str, target_value: str = ''):
    """
    Resolves authorized WhatsApp groups according to explicit targeting rules.
    Only active, automation-enabled, non-blocked, non-archived groups qualify.
    """
    base_qs = WhatsAppGroup.objects.filter(
        is_active=True,
        automation_enabled=True,
        blocked=False,
        archived=False,
    ).exclude(whatsapp_group_id='')

    if target_type == 'ALL_GROUPS':
        return base_qs.order_by('display_name')

    if target_type == 'GROUP_TYPE':
        return base_qs.filter(group_type=target_value).order_by('display_name')

    if target_type == 'COURSE':
        return base_qs.filter(course_group_id=target_value).order_by('display_name')

    if target_type == 'GROUP_IDS':
        if isinstance(target_value, list):
            ids = [int(v) for v in target_value if str(v).isdigit()]
        else:
            ids = [int(v.strip()) for v in str(target_value).split(',') if v.strip().isdigit()]
        return base_qs.filter(id__in=ids).order_by('display_name')

    if target_type == 'LEVEL':
        # Groups linked to course groups in a specific level
        course_group_ids = CourseGroup.objects.filter(level_id=target_value, is_active=True).values_list('id', flat=True)
        return base_qs.filter(course_group_id__in=course_group_ids).order_by('display_name')

    if target_type == 'SCHOOL':
        # Custom type for school groups or matching display_name/type
        return base_qs.filter(group_type='SCHOOL').order_by('display_name')

    return base_qs.none()


def _stable_key(source_event: str, target_type: str, target_value: str, message: str, attachment_path: str) -> str:
    material = json.dumps([source_event, target_type, str(target_value), message, attachment_path], ensure_ascii=True, separators=(',', ':'))
    return hashlib.sha256(material.encode()).hexdigest()


# ── 2. Job Enqueueing ────────────────────────────────────────────────────────

def enqueue_group_message(
    *,
    target_type: str,
    target_value: str = '',
    message: str = '',
    message_type: str = 'group_announcement',
    source_event: str = '',
    attachment_path: str = '',
    created_by=None,
    dry_run: bool = False,
    custom_idempotency_key: Optional[str] = None,
) -> dict[str, Any]:
    """
    Enqueues a message for group delivery with strict idempotency and tracking.
    """
    if not message and not attachment_path:
        raise ValueError('Un message ou une pièce jointe est obligatoire.')

    groups = list(resolve_groups(target_type, target_value))

    if dry_run:
        return {
            'dry_run': True,
            'group_count': len(groups),
            'groups': groups,
            'message_preview': message[:300],
        }

    idempotency_key = custom_idempotency_key or _stable_key(source_event, target_type, str(target_value), message, attachment_path)
    correlation_id = new_correlation_id()

    with transaction.atomic():
        job, created = WhatsAppMessageJob.objects.get_or_create(
            idempotency_key=idempotency_key,
            defaults={
                'correlation_id': correlation_id,
                'target_type': target_type,
                'target_value': str(target_value),
                'message': message,
                'message_type': message_type,
                'source_event': source_event,
                'attachment_path': attachment_path,
                'created_by': created_by,
                'status': 'PENDING',
            },
        )
        if created:
            for group in groups:
                WhatsAppMessageDelivery.objects.create(
                    job=job,
                    group=group,
                    idempotency_key=f'{idempotency_key}:{group.pk}',
                    correlation_id=new_correlation_id(),
                    status='PENDING',
                )

    log_event(
        event='group_job_created' if created else 'group_job_deduplicated',
        operation='enqueue_group_message',
        correlation_id=job.correlation_id,
        result='success',
        group_count=len(groups),
        target_type=target_type,
        is_duplicate=not created,
    )
    return {'job': job, 'created': created, 'group_count': len(groups), 'groups': groups}


def cancel_job(job_id: int) -> bool:
    """Cancels a pending job and any unsent deliveries."""
    with transaction.atomic():
        updated = WhatsAppMessageJob.objects.filter(pk=job_id, status='PENDING').update(
            status='CANCELLED',
            completed_at=timezone.now()
        )
        if updated:
            WhatsAppMessageDelivery.objects.filter(job_id=job_id, status='PENDING').update(
                status='CANCELLED',
                completed_at=timezone.now()
            )
    return bool(updated)


def get_job_progress(job_id: int) -> dict[str, Any]:
    """Returns real-time progress statistics for a WhatsApp message job."""
    try:
        job = WhatsAppMessageJob.objects.get(pk=job_id)
    except WhatsAppMessageJob.DoesNotExist:
        return {'error': 'Job introuvable'}

    deliveries = list(job.deliveries.select_related('group').all())
    total = len(deliveries)
    success_count = sum(1 for d in deliveries if d.status == 'SUCCESS')
    failed_count = sum(1 for d in deliveries if d.status == 'FAILED')
    pending_count = sum(1 for d in deliveries if d.status in ('PENDING', 'RUNNING'))
    skipped_count = sum(1 for d in deliveries if d.status in ('SKIPPED', 'CANCELLED'))

    return {
        'job_id': job.pk,
        'status': job.status,
        'status_display': job.get_status_display(),
        'target_type': job.target_type,
        'total': total,
        'success_count': success_count,
        'failed_count': failed_count,
        'pending_count': pending_count,
        'skipped_count': skipped_count,
        'percent_completed': round(((success_count + failed_count + skipped_count) / total * 100)) if total > 0 else 100,
        'created_at': job.created_at.isoformat() if job.created_at else None,
        'started_at': job.started_at.isoformat() if job.started_at else None,
        'completed_at': job.completed_at.isoformat() if job.completed_at else None,
        'deliveries': [
            {
                'id': d.pk,
                'group_name': d.group.display_name,
                'group_type': d.group.get_group_type_display(),
                'status': d.status,
                'status_display': d.get_status_display(),
                'provider_message_id': d.provider_message_id,
                'error_message': d.error_message,
                'completed_at': d.completed_at.strftime('%H:%M:%S') if d.completed_at else None,
            }
            for d in deliveries
        ]
    }


# ── 3. Queue Processor Worker ────────────────────────────────────────────────

def process_next_job(delay_between_sends: float = 1.0) -> WhatsAppMessageJob | None:
    """
    Processes the next pending job in a controlled, serialized manner.
    Respects rate limits and verifies WhatsApp readiness before sending.
    """
    with transaction.atomic():
        job = WhatsAppMessageJob.objects.select_for_update().filter(status='PENDING').order_by('created_at').first()
        if not job:
            return None

        # Verify WhatsApp service status
        status_info = WhatsAppServiceAPI.get_status()
        if status_info.get('offline') or status_info.get('status') not in ('READY', 'AUTHENTICATED'):
            log_event(
                event='group_job_delayed_offline',
                operation='process_group_job',
                correlation_id=job.correlation_id,
                result='waiting_for_whatsapp',
                state=status_info.get('status', 'OFFLINE')
            )
            return None

        job.status = 'RUNNING'
        job.started_at = timezone.now()
        job.save(update_fields=['status', 'started_at'])

    log_event(
        event='group_job_started',
        operation='process_group_job',
        correlation_id=job.correlation_id,
        result='started',
        group_count=job.deliveries.count()
    )

    pending_deliveries = list(job.deliveries.select_related('group').filter(status='PENDING').order_by('id'))

    for delivery in pending_deliveries:
        with transaction.atomic():
            locked = WhatsAppMessageDelivery.objects.select_for_update().get(pk=delivery.pk)
            if locked.status != 'PENDING' or job.status == 'CANCELLED':
                continue
            locked.status = 'RUNNING'
            locked.started_at = timezone.now()
            locked.save(update_fields=['status', 'started_at'])

        started_at = time.monotonic()
        group = delivery.group

        # Check if group is valid & accessible
        if not group.whatsapp_group_id or group.blocked or group.archived or not group.is_active:
            with transaction.atomic():
                locked.status = 'SKIPPED'
                locked.error_code = 'WA_GROUP_INELIGIBLE'
                locked.error_message = 'Groupe inactif, bloqué ou archivé'
                locked.completed_at = timezone.now()
                locked.save(update_fields=['status', 'error_code', 'error_message', 'completed_at'])
            continue

        log_event(
            event='group_delivery_started',
            operation='send_group_message',
            correlation_id=delivery.correlation_id,
            group_id_hash=hash_identifier(group.whatsapp_group_id, 'group')
        )

        try:
            # Handle message sending
            result = WhatsAppServiceAPI.send_group_message(
                group_id=group.whatsapp_group_id,
                message=job.message,
            )
            success = result.get('success') is True

            with transaction.atomic():
                locked.status = 'SUCCESS' if success else 'FAILED'
                locked.provider_message_id = result.get('messageId', '') if success else ''
                locked.error_code = '' if success else 'WA_GROUP_MESSAGE_ERROR'
                locked.error_message = '' if success else str(result.get('error', 'Échec de l\'envoi'))[:500]
                locked.completed_at = timezone.now()
                locked.save(update_fields=['status', 'provider_message_id', 'error_code', 'error_message', 'completed_at'])

                if success:
                    WhatsAppGroup.objects.filter(pk=group.pk).update(
                        last_message_at=timezone.now(),
                        health_status='HEALTHY',
                    )
                else:
                    WhatsAppGroup.objects.filter(pk=group.pk).update(
                        last_error=str(result.get('error', ''))[:300]
                    )

            log_event(
                event='group_delivery_success' if success else 'group_delivery_failed',
                operation='send_group_message',
                correlation_id=delivery.correlation_id,
                result='success' if success else 'failure',
                group_id_hash=hash_identifier(group.whatsapp_group_id, 'group'),
                duration_ms=round((time.monotonic() - started_at) * 1000),
                error_code='' if success else 'WA_GROUP_MESSAGE_ERROR',
            )

        except Exception as error:
            with transaction.atomic():
                locked.status = 'FAILED'
                locked.error_code = 'WA_INTERNAL_ERROR'
                locked.error_message = str(error)[:500]
                locked.completed_at = timezone.now()
                locked.save(update_fields=['status', 'error_code', 'error_message', 'completed_at'])

            log_event(
                event='group_delivery_failed',
                operation='send_group_message',
                correlation_id=delivery.correlation_id,
                result='failure',
                group_id_hash=hash_identifier(group.whatsapp_group_id, 'group'),
                duration_ms=round((time.monotonic() - started_at) * 1000),
                error_code='WA_INTERNAL_ERROR',
                **safe_error(error)
            )

        # Rate-limiting pause between operations
        if delay_between_sends > 0:
            time.sleep(delay_between_sends)

    # Determine final job status
    statuses = list(job.deliveries.values_list('status', flat=True))
    if statuses and all(status == 'SUCCESS' for status in statuses):
        final_status = 'SUCCESS'
    elif any(status == 'SUCCESS' for status in statuses):
        final_status = 'PARTIAL'
    elif all(status in ('CANCELLED', 'SKIPPED') for status in statuses):
        final_status = 'CANCELLED'
    else:
        final_status = 'FAILED'

    WhatsAppMessageJob.objects.filter(pk=job.pk).update(status=final_status, completed_at=timezone.now())
    job.status = final_status

    log_event(
        event='group_job_completed',
        operation='process_group_job',
        correlation_id=job.correlation_id,
        result=final_status.lower(),
        success_count=statuses.count('SUCCESS'),
        failure_count=statuses.count('FAILED'),
        skipped_count=statuses.count('SKIPPED') + statuses.count('CANCELLED'),
    )
    return job


def process_all_pending_jobs(max_jobs: int = 10, delay_between_sends: float = 1.0) -> int:
    """Processes up to max_jobs pending jobs in the queue."""
    processed = 0
    for _ in range(max_jobs):
        job = process_next_job(delay_between_sends=delay_between_sends)
        if not job:
            break
        processed += 1
    return processed


# ── 4. Automation Engine & Typed Conditions ──────────────────────────────────

def evaluate_automation_conditions(conditions: dict, context: dict) -> tuple[bool, str]:
    """
    Evaluates strictly typed automation conditions without executing arbitrary code.
    Returns (passed: bool, reason: str).
    """
    if not conditions or not isinstance(conditions, dict):
        return True, "Aucune condition spécifique"

    # 1. only_active_students
    if conditions.get('only_active_students') and context.get('student'):
        student = context['student']
        if not getattr(student, 'is_active', True):
            return False, "L'élève n'est pas actif"

    # 2. minimum_amount
    if 'min_amount' in conditions and 'amount' in context:
        try:
            if float(context['amount']) < float(conditions['min_amount']):
                return False, f"Montant inférieur au seuil minimum ({conditions['min_amount']})"
        except (ValueError, TypeError):
            pass

    # 3. level_whitelist
    if 'level_ids' in conditions and isinstance(conditions['level_ids'], list) and conditions['level_ids']:
        level_id = context.get('level_id')
        if not level_id and context.get('student') and getattr(context['student'], 'level_id', None):
            level_id = context['student'].level_id
        if level_id and int(level_id) not in [int(x) for x in conditions['level_ids']]:
            return False, "Le niveau scolaire ne correspond pas aux conditions"

    # 4. only_if_whatsapp_ready
    if conditions.get('require_whatsapp_ready', True):
        status = WhatsAppServiceAPI.get_status()
        if status.get('offline') or status.get('status') not in ('READY', 'AUTHENTICATED'):
            return False, "Service WhatsApp non connecté"

    return True, "Conditions remplies"


def trigger_automation(
    trigger_name: str,
    context: dict,
    user=None,
    source_event_id: str = '',
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """
    Main entry point for event-driven WhatsApp automations.
    Finds all active automations for the trigger, verifies cooldown & conditions,
    renders template, and enqueues jobs idempotently.
    """
    automations = WhatsAppAutomation.objects.filter(
        enabled=True,
        trigger=trigger_name
    ).select_related('template')

    results = []

    for auto in automations:
        correlation_id = new_correlation_id()
        started_at = timezone.now()

        # Cooldown check
        if auto.is_in_cooldown():
            WhatsAppAutomationRun.objects.create(
                automation=auto,
                trigger_event=trigger_name,
                status='SKIPPED',
                correlation_id=correlation_id,
                details={'reason': 'cooldown_active', 'cooldown_seconds': auto.cooldown_seconds},
                completed_at=timezone.now(),
            )
            results.append({'automation': auto.name, 'status': 'SKIPPED', 'reason': 'Cooldown actif'})
            continue

        # Condition check
        passed, reason = evaluate_automation_conditions(auto.conditions, context)
        if not passed:
            WhatsAppAutomationRun.objects.create(
                automation=auto,
                trigger_event=trigger_name,
                status='SKIPPED',
                correlation_id=correlation_id,
                details={'reason': reason},
                completed_at=timezone.now(),
            )
            results.append({'automation': auto.name, 'status': 'SKIPPED', 'reason': reason})
            continue

        # Render template
        template = auto.template
        rendered_msg, missing_vars = template.render(context)
        if missing_vars:
            err_msg = f"Variables de modèle manquantes: {', '.join(missing_vars)}"
            WhatsAppAutomationRun.objects.create(
                automation=auto,
                trigger_event=trigger_name,
                status='FAILED',
                correlation_id=correlation_id,
                error_message=err_msg,
                completed_at=timezone.now(),
            )
            results.append({'automation': auto.name, 'status': 'FAILED', 'error': err_msg})
            continue

        # Build stable idempotency key
        idempotency_key = f"auto:{auto.pk}:{trigger_name}:{source_event_id or ''}:{hashlib.md5(rendered_msg.encode()).hexdigest()[:16]}"

        is_effective_dry_run = dry_run or auto.dry_run_only

        if is_effective_dry_run:
            groups = list(resolve_groups(auto.target_type, auto.target_value))
            WhatsAppAutomationRun.objects.create(
                automation=auto,
                trigger_event=trigger_name,
                status='DRY_RUN',
                groups_targeted=len(groups),
                correlation_id=correlation_id,
                details={'message_preview': rendered_msg[:200], 'group_count': len(groups)},
                completed_at=timezone.now(),
            )
            results.append({
                'automation': auto.name,
                'status': 'DRY_RUN',
                'groups_targeted': len(groups),
                'message_preview': rendered_msg,
            })
            continue

        # Enqueue job
        enqueue_res = enqueue_group_message(
            target_type=auto.target_type,
            target_value=auto.target_value,
            message=rendered_msg,
            message_type=f"auto_{trigger_name.lower()}",
            source_event=f"automation_{auto.pk}",
            created_by=user,
            custom_idempotency_key=idempotency_key,
        )

        job = enqueue_res.get('job')
        auto.last_run_at = timezone.now()
        auto.last_result = 'ENQUEUED'
        auto.save(update_fields=['last_run_at', 'last_result'])

        WhatsAppAutomationRun.objects.create(
            automation=auto,
            job=job,
            trigger_event=trigger_name,
            status='SUCCESS',
            groups_targeted=enqueue_res.get('group_count', 0),
            correlation_id=correlation_id,
            details={'job_id': job.pk if job else None},
            completed_at=timezone.now(),
        )

        results.append({
            'automation': auto.name,
            'status': 'SUCCESS',
            'job_id': job.pk if job else None,
            'groups_targeted': enqueue_res.get('group_count', 0),
        })

    return results


# ── 5. Group Health Verification ─────────────────────────────────────────────

def verify_group_health(group: WhatsAppGroup) -> dict[str, Any]:
    """
    Verifies that a registered WhatsApp group is accessible and valid on WhatsApp Web.
    Updates health status without deleting database records.
    """
    if not group.whatsapp_group_id:
        group.health_status = 'ERROR'
        group.last_error = "Identifiant WhatsApp manquant"
        group.last_verified_at = timezone.now()
        group.save(update_fields=['health_status', 'last_error', 'last_verified_at'])
        return {'success': False, 'status': 'ERROR', 'error': 'No WhatsApp ID'}

    try:
        res = WhatsAppServiceAPI.get_group_info(group.whatsapp_group_id)
        if res.get('success'):
            group.health_status = 'HEALTHY'
            group.last_error = ''
            group.last_verified_at = timezone.now()
            group.participant_count = len(res.get('participants', []))
            if res.get('name') and res['name'] != group.display_name:
                # Group was renamed on WhatsApp; log note but keep display_name or update
                group.last_error = f"Nom WhatsApp distant : '{res['name']}'"
            group.save(update_fields=['health_status', 'last_error', 'last_verified_at', 'participant_count'])
            return {'success': True, 'status': 'HEALTHY', 'participants': group.participant_count}
        else:
            group.health_status = 'ERROR'
            group.last_error = str(res.get('error', 'Groupe introuvable sur WhatsApp'))[:300]
            group.last_verified_at = timezone.now()
            group.save(update_fields=['health_status', 'last_error', 'last_verified_at'])
            return {'success': False, 'status': 'ERROR', 'error': group.last_error}
    except Exception as e:
        group.health_status = 'ERROR'
        group.last_error = str(e)[:300]
        group.last_verified_at = timezone.now()
        group.save(update_fields=['health_status', 'last_error', 'last_verified_at'])
        return {'success': False, 'status': 'ERROR', 'error': str(e)}


def verify_all_groups_health() -> dict[str, int]:
    """Verifies health of all active WhatsApp groups."""
    groups = WhatsAppGroup.objects.filter(is_active=True)
    healthy = 0
    error = 0
    for g in groups:
        res = verify_group_health(g)
        if res.get('success'):
            healthy += 1
        else:
            error += 1
    return {'total': len(groups), 'healthy': healthy, 'error': error}


# ── 6. Group Discovery & Registry ────────────────────────────────────────────

def discover_whatsapp_groups() -> dict[str, Any]:
    """
    Scans WhatsApp for all groups and compares against the Django registry.
    Does NOT automatically import groups; leaves selection to administrators.
    """
    status = WhatsAppServiceAPI.get_status()
    if status.get('offline') or status.get('status') not in ('READY', 'AUTHENTICATED'):
        return {'success': False, 'error': 'Service WhatsApp non connecté'}

    res = WhatsAppServiceAPI.get_groups()
    if not res.get('success'):
        return {'success': False, 'error': res.get('error', 'Impossible de récupérer les groupes WhatsApp')}

    raw_groups = res.get('groups', [])
    registered_ids = set(WhatsAppGroup.objects.values_list('whatsapp_group_id', flat=True))

    discovered = []
    for g in raw_groups:
        gid = g.get('id')
        is_reg = gid in registered_ids
        matched_reg = WhatsAppGroup.objects.filter(whatsapp_group_id=gid).first() if is_reg else None

        discovered.append({
            'whatsapp_group_id': gid,
            'name': g.get('name', 'Sans nom'),
            'participant_count': g.get('participantCount', 0),
            'is_read_only': g.get('isReadOnly', False),
            'is_registered': is_reg,
            'registry_group': matched_reg,
        })

    return {
        'success': True,
        'groups': discovered,
        'total_found': len(discovered),
        'registered_count': sum(1 for d in discovered if d['is_registered']),
        'unregistered_count': sum(1 for d in discovered if not d['is_registered']),
    }


def import_whatsapp_group(
    whatsapp_group_id: str,
    display_name: str,
    group_type: str = 'CUSTOM',
    course_group_id: Optional[int] = None,
    sync_enabled: bool = True,
    automation_enabled: bool = True,
) -> tuple[WhatsAppGroup, bool]:
    """
    Imports a discovered WhatsApp group into the Django registry safely.
    """
    course_group = CourseGroup.objects.filter(pk=course_group_id).first() if course_group_id else None

    group, created = WhatsAppGroup.objects.get_or_create(
        whatsapp_group_id=whatsapp_group_id,
        defaults={
            'display_name': display_name,
            'group_type': group_type,
            'course_group': course_group,
            'is_active': True,
            'sync_enabled': sync_enabled,
            'automation_enabled': automation_enabled,
            'health_status': 'HEALTHY',
            'last_verified_at': timezone.now(),
        }
    )
    if not created:
        # Update metadata
        group.display_name = display_name
        group.group_type = group_type
        if course_group:
            group.course_group = course_group
        group.is_active = True
        group.save()

    return group, created
