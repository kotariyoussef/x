"""Authorized WhatsApp group targeting and serialized delivery jobs."""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.models import WhatsAppGroup, WhatsAppMessageDelivery, WhatsAppMessageJob
from core.utils import WhatsAppServiceAPI
from core.whatsapp_logging import hash_identifier, log_event, new_correlation_id, safe_error


def resolve_groups(target_type: str, target_value: str = ''):
    groups = WhatsAppGroup.objects.filter(
        is_active=True,
        automation_enabled=True,
        blocked=False,
        archived=False,
    )
    if target_type == 'ALL_GROUPS':
        return groups.order_by('id')
    if target_type == 'GROUP_TYPE':
        return groups.filter(group_type=target_value).order_by('id')
    if target_type == 'COURSE':
        return groups.filter(course_group_id=target_value).order_by('id')
    if target_type == 'GROUP_IDS':
        ids = [value.strip() for value in target_value.split(',') if value.strip().isdigit()]
        return groups.filter(id__in=ids).order_by('id')
    return groups.none()


def _stable_key(source_event: str, target_type: str, target_value: str, message: str, attachment_path: str) -> str:
    material = json.dumps([source_event, target_type, target_value, message, attachment_path], ensure_ascii=True, separators=(',', ':'))
    return hashlib.sha256(material.encode()).hexdigest()


def enqueue_group_message(*, target_type: str, target_value: str = '', message: str = '', message_type: str = 'group_announcement', source_event: str = '', attachment_path: str = '', created_by=None, dry_run: bool = False) -> dict[str, Any]:
    if not message and not attachment_path:
        raise ValueError('A message or attachment is required.')
    groups = list(resolve_groups(target_type, target_value))
    if dry_run:
        return {'dry_run': True, 'group_count': len(groups), 'groups': groups}
    idempotency_key = _stable_key(source_event, target_type, target_value, message, attachment_path)
    correlation_id = new_correlation_id()
    with transaction.atomic():
        job, created = WhatsAppMessageJob.objects.get_or_create(
            idempotency_key=idempotency_key,
            defaults={
                'correlation_id': correlation_id,
                'target_type': target_type,
                'target_value': target_value,
                'message': message,
                'message_type': message_type,
                'source_event': source_event,
                'attachment_path': attachment_path,
                'created_by': created_by,
            },
        )
        if created:
            for group in groups:
                WhatsAppMessageDelivery.objects.create(
                    job=job,
                    group=group,
                    idempotency_key=f'{idempotency_key}:{group.pk}',
                    correlation_id=new_correlation_id(),
                )
    log_event(event='group_job_created' if created else 'group_job_deduplicated', operation='enqueue_group_message', correlation_id=job.correlation_id, result='success', group_count=len(groups), target_type=target_type)
    return {'job': job, 'created': created, 'group_count': len(groups)}


def cancel_job(job_id: int) -> bool:
    updated = WhatsAppMessageJob.objects.filter(pk=job_id, status='PENDING').update(status='CANCELLED', completed_at=timezone.now())
    if updated:
        WhatsAppMessageDelivery.objects.filter(job_id=job_id, status='PENDING').update(status='CANCELLED', completed_at=timezone.now())
    return bool(updated)


def process_next_job() -> WhatsAppMessageJob | None:
    with transaction.atomic():
        job = WhatsAppMessageJob.objects.select_for_update().filter(status='PENDING').order_by('created_at').first()
        if not job:
            return None
        job.status = 'RUNNING'
        job.started_at = timezone.now()
        job.save(update_fields=['status', 'started_at'])

    log_event(event='group_job_started', operation='process_group_job', correlation_id=job.correlation_id, result='started', group_count=job.deliveries.count())
    for delivery in job.deliveries.select_related('group').filter(status='PENDING').order_by('id'):
        with transaction.atomic():
            locked = WhatsAppMessageDelivery.objects.select_for_update().get(pk=delivery.pk)
            if locked.status != 'PENDING' or job.status == 'CANCELLED':
                continue
            locked.status = 'RUNNING'
            locked.started_at = timezone.now()
            locked.save(update_fields=['status', 'started_at'])
        started_at = time.monotonic()
        log_event(event='group_delivery_started', operation='send_group_message', correlation_id=delivery.correlation_id, group_id_hash=hash_identifier(delivery.group.whatsapp_group_id, 'group'))
        try:
            result = WhatsAppServiceAPI.send_group_message(delivery.group.whatsapp_group_id, job.message)
            success = result.get('success') is True
            with transaction.atomic():
                locked.status = 'SUCCESS' if success else 'FAILED'
                locked.provider_message_id = result.get('messageId', '') if success else ''
                locked.error_code = '' if success else 'WA_GROUP_MESSAGE_ERROR'
                locked.error_message = '' if success else str(result.get('error', 'Group message failed'))[:500]
                locked.completed_at = timezone.now()
                locked.save(update_fields=['status', 'provider_message_id', 'error_code', 'error_message', 'completed_at'])
                if success:
                    WhatsAppGroup.objects.filter(pk=delivery.group_id).update(last_message_at=timezone.now())
            log_event(event='group_delivery_success' if success else 'group_delivery_failed', operation='send_group_message', correlation_id=delivery.correlation_id, result='success' if success else 'failure', group_id_hash=hash_identifier(delivery.group.whatsapp_group_id, 'group'), duration_ms=round((time.monotonic() - started_at) * 1000), error_code='' if success else 'WA_GROUP_MESSAGE_ERROR')
        except Exception as error:
            locked.status = 'FAILED'
            locked.error_code = 'WA_INTERNAL_ERROR'
            locked.error_message = str(error)[:500]
            locked.completed_at = timezone.now()
            locked.save(update_fields=['status', 'error_code', 'error_message', 'completed_at'])
            log_event(event='group_delivery_failed', operation='send_group_message', correlation_id=delivery.correlation_id, result='failure', group_id_hash=hash_identifier(delivery.group.whatsapp_group_id, 'group'), duration_ms=round((time.monotonic() - started_at) * 1000), error_code='WA_INTERNAL_ERROR', **safe_error(error))

    statuses = list(job.deliveries.values_list('status', flat=True))
    if statuses and all(status == 'SUCCESS' for status in statuses):
        final_status = 'SUCCESS'
    elif any(status == 'SUCCESS' for status in statuses):
        final_status = 'PARTIAL'
    else:
        final_status = 'FAILED'
    WhatsAppMessageJob.objects.filter(pk=job.pk).update(status=final_status, completed_at=timezone.now())
    job.status = final_status
    log_event(event='group_job_completed', operation='process_group_job', correlation_id=job.correlation_id, result=final_status.lower(), success_count=statuses.count('SUCCESS'), failure_count=statuses.count('FAILED'))
    return job
