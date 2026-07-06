"""
core/signals.py
───────────────
Session change detection + WhatsApp notification pipeline.

Flow:
  pre_save  → snapshot (status, date, start_time, room_id) before DB write
  post_save → compare snapshot to saved values; if changed, send WA messages
"""
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

_SNAPSHOT_ATTR = '_pre_save_snapshot'


def _build_cancellation_message(session) -> str:
    date_str = session.date.strftime('%d/%m/%Y')
    return (
        f"Séance annulée\n\n"
        f"Groupe : {session.group.name}\n"
        f"Date : {date_str}\n"
        f"Heure : {session.start_time.strftime('%H:%M')} - {session.end_time.strftime('%H:%M')}\n\n"
        f"La séance du {date_str} a été annulée. "
        f"Nous nous excusons pour la gêne occasionnée."
    )


def _build_change_message(session, changes: list) -> str:
    date_str = session.date.strftime('%d/%m/%Y')
    change_lines = '\n'.join(f'  - {c}' for c in changes)
    return (
        f"Modification de séance\n\n"
        f"Groupe : {session.group.name}\n"
        f"Date : {date_str}\n"
        f"Heure : {session.start_time.strftime('%H:%M')} - {session.end_time.strftime('%H:%M')}\n"
        f"Salle : {session.room.name}\n\n"
        f"Les informations suivantes ont change :\n{change_lines}"
    )


def _notify(phone: str, message: str, student=None, message_type: str = 'session_reminder'):
    """Send a WhatsApp message and log it. Never raises."""
    try:
        from .utils import WhatsAppServiceAPI
        from .models import WhatsAppSendLog

        result = WhatsAppServiceAPI.send_message(phone, message)
        WhatsAppSendLog.objects.create(
            student=student,
            phone=phone,
            message_type=message_type,
            message_preview=message[:300],
            status='SENT' if result.get('success') else 'FAILED',
            error_message=result.get('error', '') if not result.get('success') else '',
        )
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Signal receivers
# ──────────────────────────────────────────────────────────────────────────────

@receiver(pre_save, sender='core.Session')
def session_pre_save_snapshot(sender, instance, **kwargs):
    """Capture the pre-save state so post_save can diff it."""
    if not instance.pk:
        setattr(instance, _SNAPSHOT_ATTR, None)
        return
    try:
        old = sender.objects.get(pk=instance.pk)
        setattr(instance, _SNAPSHOT_ATTR, {
            'status':     old.status,
            'date':       old.date,
            'start_time': old.start_time,
            'end_time':   old.end_time,
            'room_id':    old.room_id,
        })
    except sender.DoesNotExist:
        setattr(instance, _SNAPSHOT_ATTR, None)


@receiver(post_save, sender='core.Session')
def session_post_save_notify(sender, instance, created, **kwargs):
    """
    After a Session is saved, diff against snapshot and send WA notifications
    for cancellations or meaningful schedule changes (date, time, room).
    """
    if created:
        return

    snapshot = getattr(instance, _SNAPSHOT_ATTR, None)
    if snapshot is None:
        return

    now_cancelled = (
        snapshot['status'] != 'CANCELLED'
        and instance.status == 'CANCELLED'
    )

    schedule_changes = []
    if instance.date != snapshot['date']:
        schedule_changes.append(
            f"Date : {snapshot['date'].strftime('%d/%m/%Y')} → {instance.date.strftime('%d/%m/%Y')}"
        )
    if instance.start_time != snapshot['start_time']:
        schedule_changes.append(
            f"Heure début : {snapshot['start_time'].strftime('%H:%M')} → {instance.start_time.strftime('%H:%M')}"
        )
    if instance.end_time != snapshot.get('end_time') and snapshot.get('end_time') is not None:
        schedule_changes.append(
            f"Heure fin : {snapshot['end_time'].strftime('%H:%M')} → {instance.end_time.strftime('%H:%M')}"
        )
    if instance.room_id != snapshot['room_id']:
        try:
            from .models import Room
            old_room = Room.objects.filter(pk=snapshot['room_id']).first()
            old_room_name = old_room.name if old_room else str(snapshot['room_id'])
        except Exception:
            old_room_name = str(snapshot['room_id'])
        schedule_changes.append(f"Salle : {old_room_name} → {instance.room.name}")

    if not now_cancelled and not schedule_changes:
        return

    if now_cancelled:
        message = _build_cancellation_message(instance)
        msg_type = 'absence_notification'
    else:
        message = _build_change_message(instance, schedule_changes)
        msg_type = 'session_reminder'

    # Notify enrolled students via parent contact
    try:
        enrolled_students = (
            instance.group.students
            .filter(is_active=True, enrollment__is_active=True)
            .distinct()
        )
        for student in enrolled_students:
            phone = student.parent_contact or student.phone
            if phone:
                _notify(phone, message, student=student, message_type=msg_type)
    except Exception:
        pass

    # Notify the teacher (substitute takes precedence over primary teacher)
    try:
        teacher = instance.substitute_teacher or instance.group.teacher
        if teacher and teacher.phone:
            teacher_label = "[Remplaçant]" if instance.substitute_teacher else "[Professeur]"
            _notify(
                teacher.phone,
                f"{teacher_label} {message}",
                student=None,
                message_type=msg_type,
            )
    except Exception:
        pass
