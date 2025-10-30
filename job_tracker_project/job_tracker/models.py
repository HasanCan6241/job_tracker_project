from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.cache import cache
from django.contrib.auth.models import User


class JobApplication(models.Model):
    STATUS_CHOICES = [
        #('received', 'Başvuru Alındı'),
        ('pending', 'İş Başvurusu Beklemede'),
        ('reviewing', 'Başvuru İnceleniyor'),
        ('interview', 'Mülakat Aşaması'),
        ('accepted', 'İş Başvurusu Kabul Edildi'),
        ('rejected', 'İş Başvurusu Reddedildi'),

    ]

    # Kullanıcı ile ilişki - HER İŞ BAŞVURUSU BİR KULLANICIYA AIT
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        verbose_name="Kullanıcı",
        related_name='job_applications'
    )

    company_name = models.CharField(max_length=200, verbose_name="Şirket Adı")
    position = models.CharField(max_length=200, verbose_name="Pozisyon")
    email_sender = models.EmailField(verbose_name="Gönderen E-posta")
    application_date = models.DateTimeField(verbose_name="Başvuru Tarihi")
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='received',
        verbose_name="Durum"
    )
    email_subject = models.CharField(max_length=300, verbose_name="E-posta Konusu")
    email_content = models.TextField(verbose_name="E-posta İçeriği")
    gmail_message_id = models.CharField(max_length=100, verbose_name="Gmail Mesaj ID")
    extracted_info = models.JSONField(blank=True, null=True, verbose_name="Çıkarılan Bilgiler")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-application_date']
        verbose_name = "İş Başvurusu"
        verbose_name_plural = "İş Başvuruları"
        # Aynı kullanıcıda aynı gmail mesaj ID'si tekrar edemez
        unique_together = ['user', 'gmail_message_id']

    def __str__(self):
        return f"{self.user.username} - {self.company_name} - {self.position}"


class EmailProcessingLog(models.Model):
    # Kullanıcı ile ilişki - HER LOG BİR KULLANICIYA AIT
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        verbose_name="Kullanıcı",
        related_name='email_processing_logs'
    )

    processed_at = models.DateTimeField(auto_now_add=True)
    total_emails = models.IntegerField(default=0)
    job_applications_found = models.IntegerField(default=0)
    success = models.BooleanField(default=True)
    error_message = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-processed_at']
        verbose_name = "E-posta İşlem Kaydı"
        verbose_name_plural = "E-posta İşlem Kayıtları"

    def __str__(self):
        return f"{self.user.username} - {self.processed_at.strftime('%d.%m.%Y %H:%M')}"


class SystemSettings(models.Model):
    """Kullanıcıya özel sistem ayarlarını veritabanında saklayan model"""

    # Kullanıcı ile ilişki
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        verbose_name="Kullanıcı",
        related_name='system_settings'
    )

    # Gmail ayarları
    email_scan_days = models.PositiveIntegerField(
        default=5,
        validators=[MinValueValidator(1), MaxValueValidator(365)],
        help_text="E-posta tarama için geri gidilecek gün sayısı (1-365)",
        verbose_name="E-posta Tarama Günü"
    )

    email_scan_limit = models.PositiveIntegerField(
        default=50000,
        validators=[MinValueValidator(100), MaxValueValidator(500000)],
        help_text="Maksimum taranacak e-posta sayısı (100-500000)",
        verbose_name="E-posta Tarama Limiti"
    )

    email_batch_size = models.PositiveIntegerField(
        default=10,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text="Batch işleme boyutu (1-100)",
        verbose_name="E-posta Batch Boyutu"
    )

    # Gemini ayarları
    gemini_api_key = models.CharField(
        max_length=500,
        help_text="Gemini API anahtarı",
        verbose_name="Gemini API Anahtarı",
        blank=True
    )

    gemini_cache_ttl = models.PositiveIntegerField(
        default=60,
        validators=[MinValueValidator(1), MaxValueValidator(1440)],
        help_text="Cache TTL dakika cinsinden (1-1440)",
        verbose_name="Gemini Cache TTL (Dakika)"
    )

    # Gmail API ayarları
    gmail_credentials = models.JSONField(
        blank=True,
        null=True,
        verbose_name="Gmail API Kimlik Bilgileri",
        help_text="Gmail API için OAuth2 token bilgileri"
    )

    # Sistem ayarları
    is_active = models.BooleanField(default=False, verbose_name="Aktif mi?")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Sistem Ayarları"
        verbose_name_plural = "Sistem Ayarları"
        ordering = ['-updated_at']

    def __str__(self):
        return f"{self.user.username} - Sistem Ayarları - {self.updated_at.strftime('%d.%m.%Y %H:%M')}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Kullanıcıya özel cache'i temizle
        self.clear_cache()

    @classmethod
    def get_user_settings(cls, user):
        """Kullanıcının aktif ayarlarını getir, yoksa varsayılan oluştur"""
        if not user or not user.is_authenticated:
            return None

        try:
            # Önce aktif ayarları ara
            settings = cls.objects.filter(user=user, is_active=True).first()
            if settings:
                return settings

            # Aktif ayar yoksa en son ayarları al
            settings = cls.objects.filter(user=user).order_by('-created_at').first()
            if settings:
                # En son ayarları aktif yap
                cls.objects.filter(user=user, is_active=True).update(is_active=False)
                settings.is_active = True
                settings.save()
                return settings

            # Hiç ayar yoksa yeni oluştur
            default_settings = cls._get_default_settings()
            settings = cls.objects.create(user=user, is_active=True, **default_settings)
            return settings

        except Exception as e:
            # Hata durumunda default ayarlarla yeni kayıt oluştur
            print(f"get_user_settings error: {e}")
            default_settings = cls._get_default_settings()
            return cls.objects.create(user=user, is_active=True, **default_settings)

    @classmethod
    def _get_default_settings(cls):
        """Varsayılan ayar değerlerini döndür"""
        from django.conf import settings as django_settings

        return {
            'email_scan_days': getattr(django_settings, 'EMAIL_SCAN_DAYS', 5),
            'email_scan_limit': getattr(django_settings, 'EMAIL_SCAN_LIMIT', 50000),
            'email_batch_size': getattr(django_settings, 'EMAIL_BATCH_SIZE', 10),
            'gemini_api_key': getattr(django_settings, 'GEMINI_API_KEY', ''),
            'gemini_cache_ttl': getattr(django_settings, 'GEMINI_CACHE_TTL', 60),
        }

    def clear_cache(self):
        """Kullanıcıya özel cache anahtarlarını temizle"""
        from django.core.cache import cache
        cache.delete(f'system_settings_{self.user.id}')

    @classmethod
    def get_cached_user_settings(cls, user):
        """Kullanıcının cache'lenmiş ayarlarını getir"""
        if not user or not user.is_authenticated:
            return None

        from django.core.cache import cache
        cache_key = f'system_settings_{user.id}'
        settings = cache.get(cache_key)

        if settings is None:
            settings = cls.get_user_settings(user)
            if settings:
                cache.set(cache_key, settings, 300)  # 5 dakika cache

        return settings


class UserProfile(models.Model):
    """Kullanıcı profil bilgileri için ek model"""
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='profile'
    )

    # Profil bilgileri
    phone = models.CharField(max_length=20, blank=True, verbose_name="Telefon")
    linkedin_url = models.URLField(blank=True, verbose_name="LinkedIn Profili")
    github_url = models.URLField(blank=True, verbose_name="GitHub Profili")

    # İş arama tercihleri
    preferred_locations = models.CharField(
        max_length=500,
        blank=True,
        verbose_name="Tercih Edilen Şehirler",
        help_text="Virgülle ayırın: İstanbul, Ankara, İzmir"
    )
    preferred_positions = models.CharField(
        max_length=500,
        blank=True,
        verbose_name="Tercih Edilen Pozisyonlar",
        help_text="Virgülle ayırın: Python Developer, Full Stack Developer"
    )

    # Statistik bilgileri
    total_applications = models.PositiveIntegerField(default=0, verbose_name="Toplam Başvuru")
    last_email_sync = models.DateTimeField(null=True, blank=True, verbose_name="Son E-posta Senkronizasyonu")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Kullanıcı Profili"
        verbose_name_plural = "Kullanıcı Profilleri"

    def __str__(self):
        return f"{self.user.username} - Profil"

    def update_application_count(self):
        """Kullanıcının toplam başvuru sayısını güncelle"""
        self.total_applications = self.user.job_applications.count()
        self.save(update_fields=['total_applications'])

    def get_success_rate(self):
        """Başarı oranını hesapla"""
        total = self.user.job_applications.count()
        if total == 0:
            return 0

        successful = self.user.job_applications.filter(
            status__in=['accepted', 'interview']
        ).count()

        return round((successful / total) * 100, 1)

    @property
    def recent_applications(self):
        """Son 7 gündeki başvuruları getir"""
        from datetime import timedelta
        week_ago = timezone.now() - timedelta(days=7)
        return self.user.job_applications.filter(
            application_date__gte=week_ago
        ).count()


# Signal'lar - Kullanıcı oluşturulduğunda otomatik profil ve ayarlar oluştur
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Yeni kullanıcı oluşturulduğunda profil oluştur"""
    if created:
        UserProfile.objects.create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    """Kullanıcı kaydedildiğinde profili de kaydet"""
    if hasattr(instance, 'profile'):
        instance.profile.save()


@receiver(post_save, sender=JobApplication)
def update_user_stats(sender, instance, created, **kwargs):
    """Yeni başvuru eklendiğinde kullanıcı istatistiklerini güncelle"""
    if created and hasattr(instance.user, 'profile'):
        instance.user.profile.update_application_count()