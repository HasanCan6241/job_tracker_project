from django.core.cache import cache
from django.conf import settings as django_settings


from django.conf import settings as django_settings
from django.core.cache import cache
from .models import SystemSettings

def get_system_setting(user, key, default=None):
    """
    Belirli bir kullanıcının sistem ayarlarını getir
    Önce cache, sonra veritabanı, en sonunda Django settings fallback
    """
    try:
        # Kullanıcıya özel cache anahtarı
        cache_key = f'system_settings_{user.id}'
        cached_settings = cache.get(cache_key)

        if cached_settings is None:
            # Veritabanından getir
            db_settings = SystemSettings.get_user_settings(user)

            if db_settings:
                cache.set(cache_key, db_settings, 300)  # 5 dakika cache
                cached_settings = db_settings

        if cached_settings:
            mapping = {
                'EMAIL_SCAN_DAYS': 'email_scan_days',
                'EMAIL_SCAN_LIMIT': 'email_scan_limit',
                'EMAIL_BATCH_SIZE': 'email_batch_size',
                'GEMINI_API_KEY': 'gemini_api_key',
                'GEMINI_CACHE_TTL': 'gemini_cache_ttl',
            }

            if key in mapping:
                db_value = getattr(cached_settings, mapping[key], None)
                if db_value is not None:
                    return db_value

        # fallback: settings.py
        return getattr(django_settings, key, default)

    except Exception as e:
        print(f"[get_system_setting] Hata: {e}")
        return getattr(django_settings, key, default)



def refresh_settings_cache():
    """Settings cache'ini yenile"""
    try:
        from .models import SystemSettings
        cache.delete('system_settings')
        fresh_settings = SystemSettings.get_active_settings()
        if fresh_settings:
            cache.set('system_settings', fresh_settings, 300)
        return True
    except Exception as e:
        print(f"Cache yenileme hatası: {e}")
        return False