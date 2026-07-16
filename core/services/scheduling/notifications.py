from typing import List, Dict, Any, Optional
from django.conf import settings
from core.models import Session, Student

class NotificationService:
    @staticmethod
    def _dispatch_notification(
        recipient_name: str,
        recipient_phone: Optional[str],
        recipient_email: Optional[str],
        subject: str,
        message: str,
        context: Dict[str, Any]
    ):
        """
        Base dispatcher. Currently logs to standard outputs/logs.
        Can be extended with WhatsApp service, Twilio, or SMTP drivers.
        """
        log_msg = (
            f"\n--- NOTIFICATION DISPATCHED ---\n"
            f"To: {recipient_name}\n"
            f"Phone: {recipient_phone or 'N/A'}\n"
            f"Email: {recipient_email or 'N/A'}\n"
            f"Subject: {subject}\n"
            f"Message: {message}\n"
            f"---------------------------------\n"
        )
        import logging
        logger = logging.getLogger('django')
        logger.info(log_msg)
        print(log_msg)

    @classmethod
    def notify_session_change(cls, session: Session, change_type: str, details: str):
        teacher = session.substitute_teacher or (session.group.teacher if session.group else None)
        if teacher:
            cls._dispatch_notification(
                recipient_name=teacher.name,
                recipient_phone=teacher.phone,
                recipient_email=teacher.email,
                subject=f"Modification de cours: {session.group.name if session.group else ''}",
                message=f"Bonjour {teacher.name}, votre cours du {session.date.strftime('%d/%m/%Y')} a été modifié ({change_type}). Détails: {details}",
                context={'session_id': session.id, 'type': change_type}
            )

        students = []
        from core.models import MakeupSession
        makeup_link = MakeupSession.objects.filter(makeup_session=session).first()
        if makeup_link:
            students = makeup_link.students.filter(is_active=True)
        elif session.group:
            students = session.group.students.filter(is_active=True)

        for student in students:
            if student.phone:
                cls._dispatch_notification(
                    recipient_name=student.name,
                    recipient_phone=student.phone,
                    recipient_email="",
                    subject=f"Cours modifié: {session.group.name if session.group else ''}",
                    message=f"Bonjour {student.name}, la séance du {session.date.strftime('%d/%m/%Y')} a été modifiée ({change_type}). Détails: {details}",
                    context={'session_id': session.id, 'student_id': student.id}
                )
            if student.parent_contact:
                cls._dispatch_notification(
                    recipient_name=f"Parent de {student.name} ({student.parent_name or ''})",
                    recipient_phone=student.parent_contact,
                    recipient_email="",
                    subject=f"Avis de modification: {session.group.name if session.group else ''}",
                    message=f"Bonjour, nous vous informons que le cours de votre enfant {student.name} du {session.date.strftime('%d/%m/%Y')} a été modifié ({change_type}). Détails: {details}",
                    context={'session_id': session.id, 'student_id': student.id}
                )

    @classmethod
    def send_session_cancelled(cls, session: Session):
        details = "La séance a été annulée."
        cls.notify_session_change(session, "Annulation", details)

    @classmethod
    def send_session_moved(cls, session: Session):
        details = f"La séance a été déplacée au {session.date.strftime('%d/%m/%Y')} de {session.start_time.strftime('%H:%M')} à {session.end_time.strftime('%H:%M')}."
        cls.notify_session_change(session, "Déplacement", details)

    @classmethod
    def send_room_changed(cls, session: Session):
        details = f"La salle a été modifiée. Nouveau lieu: {session.room.name if session.room else 'N/A'}."
        cls.notify_session_change(session, "Changement de salle", details)

    @classmethod
    def send_teacher_substituted(cls, session: Session):
        teacher_name = session.substitute_teacher.name if session.substitute_teacher else "N/A"
        details = f"Remplacement d'enseignant. Nouveau professeur: {teacher_name}."
        cls.notify_session_change(session, "Enseignant remplacé", details)

    @classmethod
    def send_makeup_session_created(cls, session: Session):
        details = f"Séance de rattrapage programmée le {session.date.strftime('%d/%m/%Y')} de {session.start_time.strftime('%H:%M')} à {session.end_time.strftime('%H:%M')}."
        cls.notify_session_change(session, "Séance de rattrapage", details)

    @classmethod
    def send_schedule_published(cls, session: Session):
        details = f"Le planning pour la séance du {session.date.strftime('%d/%m/%Y')} a été officiellement publié."
        cls.notify_session_change(session, "Publication du planning", details)
