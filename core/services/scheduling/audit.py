from typing import Dict, Any, Optional
from django.contrib.auth.models import User
from core.models import Session, SessionChangeHistory

class AuditService:
    @staticmethod
    def log_change(
        session: Session,
        user: Optional[User],
        action: str,
        previous_values: Dict[str, Any],
        new_values: Dict[str, Any],
        change_reason: Optional[str] = None,
        ip_address: Optional[str] = None
    ) -> SessionChangeHistory:
        """
        Explicitly logs a session modification or creation to the SessionChangeHistory model.
        """
        return SessionChangeHistory.objects.create(
            session=session,
            user=user,
            action=action,
            previous_values=previous_values,
            new_values=new_values,
            change_reason=change_reason or "",
            ip_address=ip_address
        )
