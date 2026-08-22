import logging
from typing import Dict, List, Optional, Any
from django.conf import settings
from core.utils import WhatsAppUtils, WhatsAppServiceAPI
from core.whatsapp_logging import hash_identifier, log_event, new_correlation_id

logger = logging.getLogger(__name__)


class WhatsAppGroupService:
    """
    Service layer for managing WhatsApp groups for CourseGroups.
    Handles group generation, creation, sync, participant management, and failure safety.
    """

    @classmethod
    def generate_group_name(cls, course_group) -> str:
        """
        Generates a consistent group name for a CourseGroup.
        Example: "School ERP - Physique-Chimie - 3ASC (G23)"
        """
        school_name = getattr(settings, 'SCHOOL_NAME', 'School ERP')
        parts = [school_name]

        if course_group.name:
            parts.append(course_group.name)

        if course_group.level:
            parts.append(str(course_group.level.name))

        group_name = " - ".join(parts)
        # WhatsApp group names have a maximum length of 100 characters
        if len(group_name) > 100:
            group_name = group_name[:97] + "..."
        return group_name

    @classmethod
    def get_course_group_participants(cls, course_group) -> List[str]:
        """
        Collects all parent phone numbers for enrolled active students and the teacher's phone number.
        Phone numbers are cleaned and deduplicated.
        """
        phones = []

        # 1. Teacher phone number
        if course_group.teacher and course_group.teacher.phone:
            phones.append(course_group.teacher.phone)

        # 2. Enrolled students phone numbers & parent contacts
        active_enrollments = course_group.enrollment_set.filter(is_active=True).select_related('student')
        for enrollment in active_enrollments:
            student = enrollment.student
            if student.phone:
                phones.append(student.phone)
            if student.parent_contact:
                phones.append(student.parent_contact)
            if student.parent_contact_2:
                phones.append(student.parent_contact_2)

        # Deduplicate using cleaned phone numbers
        unique_cleaned_phones = []
        seen_cleaned = set()

        for phone in phones:
            cleaned = WhatsAppUtils.clean_phone_number(phone)
            if cleaned and cleaned not in seen_cleaned:
                seen_cleaned.add(cleaned)
                unique_cleaned_phones.append(cleaned)

        return unique_cleaned_phones

    @classmethod
    def create_course_group(cls, course_group) -> Dict[str, Any]:
        """
        Creates a new WhatsApp group for the given CourseGroup and saves group info back to model.
        """
        correlation_id = new_correlation_id()
        log_event(event='group_sync_started', operation='create_group', correlation_id=correlation_id, group_id_hash=hash_identifier(course_group.whatsapp_group_id, 'group'), participant_count=0)
        group_name = cls.generate_group_name(course_group)
        course_group.whatsapp_group_name = group_name
        course_group.save(update_fields=['whatsapp_group_name'])

        participants = cls.get_course_group_participants(course_group)

        logger.info("Creating WhatsApp group with %s participants", len(participants))
        
        response = WhatsAppServiceAPI.create_group(name=group_name, participants=participants)

        if response.get('success'):
            group_id = response.get('groupId')
            invite_link = response.get('inviteLink')

            course_group.whatsapp_group_id = group_id
            if invite_link:
                course_group.whatsapp_group_link = invite_link
            course_group.whatsapp_group_status = 'ACTIVE'
            from django.utils import timezone
            course_group.whatsapp_last_synced_at = timezone.now()
            course_group.save(update_fields=[
                'whatsapp_group_id',
                'whatsapp_group_link',
                'whatsapp_group_status',
                'whatsapp_last_synced_at'
            ])

            logger.info("Successfully created WhatsApp group")
            log_event(event='group_create_success', operation='create_group', correlation_id=correlation_id, result='success', group_id_hash=hash_identifier(group_id, 'group'), participant_count=len(participants))
            return {
                'success': True,
                'group_id': group_id,
                'invite_link': invite_link,
                'participants_count': len(participants)
            }
        else:
            error_msg = response.get('error', 'Unknown error during group creation')
            logger.error("Failed to create WhatsApp group")
            course_group.whatsapp_group_status = 'FAILED'
            course_group.save(update_fields=['whatsapp_group_status'])
            log_event(event='group_create_failed', operation='create_group', correlation_id=correlation_id, result='failure', group_id_hash=hash_identifier(course_group.whatsapp_group_id, 'group'), participant_count=len(participants), error_code='WA_GROUP_ERROR')
            return {
                'success': False,
                'error': error_msg
            }

    @classmethod
    def add_participant(cls, course_group, phone_numbers: List[str]) -> Dict[str, Any]:
        """
        Adds parent/teacher phone numbers to an existing WhatsApp group.
        If adding a participant fails (or is restricted by privacy settings/403/408/etc.),
        automatically sends them a WhatsApp message with the group invite link.
        """
        if not course_group.whatsapp_group_id:
            logger.warning("Cannot add participants because the group ID is missing")
            return {'success': False, 'error': 'No WhatsApp group ID'}

        valid_phones = []
        for p in phone_numbers:
            cleaned = WhatsAppUtils.clean_phone_number(p)
            if cleaned:
                valid_phones.append(cleaned)

        if not valid_phones:
            return {'success': True, 'added': []}

        logger.info("Adding %s participants to WhatsApp group", len(valid_phones))
        correlation_id = new_correlation_id()
        log_event(event='group_add_participants_requested', operation='add_group_participants', correlation_id=correlation_id, group_id_hash=hash_identifier(course_group.whatsapp_group_id, 'group'), participant_count=len(phone_numbers or []))
        response = WhatsAppServiceAPI.add_group_participants(
            group_id=course_group.whatsapp_group_id,
            participants=valid_phones
        )

        invite_sent = []
        results_map = response.get('results') or response.get('result') or {}

        # If adding via API succeeded or partially succeeded, check which numbers failed to be added directly
        failed_phones = []
        if response.get('success'):
            if isinstance(results_map, dict):
                for phone in valid_phones:
                    p_res = results_map.get(phone, {})
                    status_code = p_res.get('status') if isinstance(p_res, dict) else None
                    msg = str(p_res.get('message', '')).lower() if isinstance(p_res, dict) else ''
                    # status 200 = added, 409 = already member. Any other status (e.g. 403, 408) = failure to add directly
                    if status_code and status_code not in (200, 409) and 'already' not in msg:
                        failed_phones.append(phone)
        else:
            failed_phones = valid_phones

        # Auto-send WhatsApp group invite link to any numbers that couldn't be added directly
        if failed_phones and course_group.whatsapp_group_link:
            invite_msg = (
                f"Bonjour,\n\n"
                f"Voici le lien pour rejoindre le groupe WhatsApp de {course_group.name} "
                f"({course_group.level.name if course_group.level else ''}) :\n"
                f"{course_group.whatsapp_group_link}\n\n"
                f"Merci de cliquer sur le lien pour intégrer le groupe."
            )
            for phone in failed_phones:
                try:
                    send_res = WhatsAppServiceAPI.send_message(phone=phone, message=invite_msg)
                    if send_res.get('success'):
                        invite_sent.append(phone)
                        logger.info("Automatically sent a group invite link")
                except Exception as e:
                    logger.error("Failed to auto-send invite link")

        if response.get('success'):
            from django.utils import timezone
            course_group.whatsapp_last_synced_at = timezone.now()
            course_group.save(update_fields=['whatsapp_last_synced_at'])
            log_event(event='group_add_participants_success', operation='add_group_participants', correlation_id=correlation_id, result='success', group_id_hash=hash_identifier(course_group.whatsapp_group_id, 'group'), participant_count=len(valid_phones), failure_count=len(failed_phones))
            return {
                'success': True,
                'added': valid_phones,
                'invite_sent': invite_sent,
                'results': results_map
            }
        else:
            error_msg = response.get('error', 'Failed to add group participants')
            logger.error("Error adding participants to WhatsApp group")
            log_event(event='group_add_participants_failed', operation='add_group_participants', correlation_id=correlation_id, result='failure', group_id_hash=hash_identifier(course_group.whatsapp_group_id, 'group'), participant_count=len(valid_phones), error_code='WA_GROUP_ERROR')
            return {'success': False, 'error': error_msg, 'invite_sent': invite_sent}

    @classmethod
    def remove_participant(cls, course_group, phone_numbers: List[str]) -> Dict[str, Any]:
        """
        Removes parent phone numbers from an existing WhatsApp group.
        """
        if not course_group.whatsapp_group_id:
            return {'success': False, 'error': 'No WhatsApp group ID'}

        valid_phones = []
        for p in phone_numbers:
            cleaned = WhatsAppUtils.clean_phone_number(p)
            if cleaned:
                valid_phones.append(cleaned)

        if not valid_phones:
            return {'success': True, 'removed': []}

        logger.info("Removing %s participants from WhatsApp group", len(valid_phones))
        correlation_id = new_correlation_id()
        log_event(event='group_remove_participants_requested', operation='remove_group_participants', correlation_id=correlation_id, group_id_hash=hash_identifier(course_group.whatsapp_group_id, 'group'), participant_count=len(phone_numbers or []))
        response = WhatsAppServiceAPI.remove_group_participants(
            group_id=course_group.whatsapp_group_id,
            participants=valid_phones
        )

        if response.get('success'):
            from django.utils import timezone
            course_group.whatsapp_last_synced_at = timezone.now()
            course_group.save(update_fields=['whatsapp_last_synced_at'])
            log_event(event='group_remove_participants_success', operation='remove_group_participants', correlation_id=correlation_id, result='success', group_id_hash=hash_identifier(course_group.whatsapp_group_id, 'group'), participant_count=len(valid_phones))
            return {
                'success': True,
                'removed': valid_phones,
                'results': response.get('results') or response.get('result')
            }
        else:
            error_msg = response.get('error', 'Failed to remove group participants')
            logger.error("Error removing participants from WhatsApp group")
            log_event(event='group_remove_participants_failed', operation='remove_group_participants', correlation_id=correlation_id, result='failure', group_id_hash=hash_identifier(course_group.whatsapp_group_id, 'group'), participant_count=len(valid_phones), error_code='WA_GROUP_ERROR')
            return {'success': False, 'error': error_msg}

    @classmethod
    def sync_course_group(cls, course_group) -> Dict[str, Any]:
        """
        Full idempotent synchronization operation:
        1. Checks WhatsApp status.
        2. Ensures group name matches.
        3. If no group ID exists, creates the group.
        4. If group ID exists, queries current participants or syncs all enrolled contacts + teacher.
        5. Returns detailed result status.
        """
        correlation_id = new_correlation_id()
        log_event(event='group_sync_started', operation='sync_group', correlation_id=correlation_id, group_id_hash=hash_identifier(course_group.whatsapp_group_id, 'group'))
        expected_name = cls.generate_group_name(course_group)
        course_group.whatsapp_group_name = expected_name

        target_participants = cls.get_course_group_participants(course_group)

        # 1. Verify WhatsApp service availability
        status_info = WhatsAppServiceAPI.get_status()
        log_event(event='group_sync_groups_loaded', operation='sync_group', correlation_id=correlation_id, state=status_info.get('status'), result='success' if not status_info.get('offline') else 'failure', expected_count=len(target_participants))
        if status_info.get('status') != 'authenticated':
            err = f"WhatsApp service is offline or disconnected (status: {status_info.get('status', 'unknown')})"
            logger.warning(err)
            course_group.whatsapp_group_status = 'FAILED'
            course_group.save(update_fields=['whatsapp_group_status'])
            log_event(event='group_sync_failed', operation='sync_group', correlation_id=correlation_id, result='failure', error_code='WA_NOT_READY')
            return {
                'success': False,
                'group_created': False,
                'group_name': expected_name,
                'group_link': course_group.whatsapp_group_link,
                'group_id': course_group.whatsapp_group_id,
                'added': [],
                'already_members': [],
                'failed': target_participants,
                'warnings': [err]
            }

        # 2. If group not created yet
        if not course_group.whatsapp_group_id:
            res = cls.create_course_group(course_group)
            if res.get('success'):
                log_event(event='group_sync_completed', operation='sync_group', correlation_id=correlation_id, result='success', added_count=len(target_participants), failed_count=0)
                return {
                    'success': True,
                    'group_created': True,
                    'group_name': expected_name,
                    'group_link': course_group.whatsapp_group_link,
                    'group_id': course_group.whatsapp_group_id,
                    'added': target_participants,
                    'already_members': [],
                    'failed': [],
                    'warnings': []
                }
            else:
                log_event(event='group_sync_failed', operation='sync_group', correlation_id=correlation_id, result='failure', failed_count=len(target_participants))
                return {
                    'success': False,
                    'group_created': False,
                    'group_name': expected_name,
                    'group_link': course_group.whatsapp_group_link,
                    'group_id': course_group.whatsapp_group_id,
                    'added': [],
                    'already_members': [],
                    'failed': target_participants,
                    'warnings': [res.get('error')]
                }

        # 3. Group already exists -> query current members or add target participants
        info_res = WhatsAppServiceAPI.get_group_info(course_group.whatsapp_group_id)
        already_members = []
        if info_res.get('success'):
            if info_res.get('inviteLink'):
                course_group.whatsapp_group_link = info_res.get('inviteLink')
            
            existing_participants_raw = info_res.get('participants', [])
            for p in existing_participants_raw:
                if isinstance(p, dict) and 'user' in p:
                    already_members.append(p['user'])

        missing_participants = [p for p in target_participants if p not in already_members]
        log_event(event='group_sync_diff_calculated', operation='sync_group', correlation_id=correlation_id, expected_count=len(target_participants), actual_count=len(already_members), added_count=len(missing_participants), removed_count=0)

        added = []
        failed = []
        warnings = []

        if missing_participants:
            add_res = cls.add_participant(course_group, missing_participants)
            if add_res.get('success'):
                results_map = add_res.get('results') or {}
                for p in missing_participants:
                    p_res = results_map.get(p, {}) if isinstance(results_map, dict) else {}
                    status_code = p_res.get('status') if isinstance(p_res, dict) else None
                    msg = str(p_res.get('message', '')).lower() if isinstance(p_res, dict) else ''
                    if status_code == 409 or 'already' in msg:
                        already_members.append(p)
                    else:
                        added.append(p)
            else:
                failed = missing_participants
                warnings.append(add_res.get('error'))

        from django.utils import timezone
        course_group.whatsapp_group_status = 'ACTIVE'
        course_group.whatsapp_last_synced_at = timezone.now()
        course_group.save(update_fields=['whatsapp_group_name', 'whatsapp_group_link', 'whatsapp_group_status', 'whatsapp_last_synced_at'])

        all_already = list(set(already_members) & set(target_participants)) if already_members else list(set(target_participants) - set(missing_participants) - set(added))

        log_event(event='group_sync_database_updated', operation='sync_group', correlation_id=correlation_id, result='success' if not failed else 'failure', added_count=len(added), removed_count=0, failed_count=len(failed))
        return {
            'success': len(failed) == 0,
            'group_created': False,
            'group_name': expected_name,
            'group_link': course_group.whatsapp_group_link,
            'group_id': course_group.whatsapp_group_id,
            'added': added,
            'already_members': all_already,
            'failed': failed,
            'warnings': warnings
        }
