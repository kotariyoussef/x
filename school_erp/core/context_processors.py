"""
Context processor: injects `conflict_count` into every template context
so the base sidebar can display a live badge on the "Conflits" link.

The count is computed cheaply (schedule-only conflicts, O(n²) on schedules)
and cached per-request so it's called at most once per page.
"""
from django.core.cache import cache
from django.conf import settings


def conflicts_count(request):
    """
    Returns {'conflict_count': <int>} with the total number of active
    schedule conflicts (room + teacher overlaps).

    Results are cached for 2 minutes so every page load doesn't trigger
    a full scan.  The cache is invalidated by the post_save signal on
    CourseGroupSchedule (see models.py).
    """
    CACHE_KEY = 'sidebar_conflict_count'
    CACHE_TTL = getattr(settings, 'CONFLICT_CACHE_TTL', 120)  # 2 minutes instead of 30 seconds

    count = cache.get(CACHE_KEY)
    if count is None:
        try:
            from .utils import detect_all_conflicts
            data = detect_all_conflicts()
            # Only schedule conflicts matter for the sidebar badge
            count = len(data.get('schedule_conflicts', []))
        except Exception:
            count = 0
        cache.set(CACHE_KEY, count, CACHE_TTL)

    return {'conflict_count': count}


def whatsapp_status(request):
    """
    Returns {'whatsapp_connected': True/False} to show status indicator in main sidebar.
    Cached for 30 seconds to prevent slowing down page loads.
    """
    CACHE_KEY = 'sidebar_whatsapp_status'
    CACHE_TTL = 30  # Increased from 5 seconds to 30 seconds
    
    connected = cache.get(CACHE_KEY)
    if connected is None:
        try:
            from .utils import WhatsAppServiceAPI
            status_data = WhatsAppServiceAPI.get_status()
            connected = not status_data.get('offline', True) and status_data.get('status') == 'READY'
        except Exception:
            connected = False
        cache.set(CACHE_KEY, connected, CACHE_TTL)
        
    return {'whatsapp_connected': connected}


def school_info(request):
    """
    Returns configurable school settings to be available in all templates.
    """
    return {
        'SCHOOL_NAME': getattr(settings, 'SCHOOL_NAME', 'Afnane center'),
        'SCHOOL_ADDRESS': getattr(settings, 'SCHOOL_ADDRESS', 'Rue Marrakech, Im 16, Ap N 3, 2ème Étage, Khouribga'),
        'SCHOOL_PHONE': getattr(settings, 'SCHOOL_PHONE', '0707477911 / 0661569522'),
        'SCHOOL_EMAIL': getattr(settings, 'SCHOOL_EMAIL', 'contact@centre-tonaroz.com'),
        'SCHOOL_LOGO_PATH': getattr(settings, 'SCHOOL_LOGO_PATH', 'images/tonaroz_logo.svg'),
    }
