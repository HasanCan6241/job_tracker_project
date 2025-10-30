from django.shortcuts import get_object_or_404, redirect
from django.http import HttpResponse
from django.core.paginator import Paginator
from .gmail_service import GmailService
from .gemini_service import GeminiService
import os
from django.shortcuts import render
from django.db.models import Count, Q
from django.utils import timezone
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import pandas as pd
from .models import JobApplication, EmailProcessingLog, UserProfile
import io
import base64
from django.db.models.functions import TruncMonth, TruncWeek
from .models import SystemSettings
from .forms import SystemSettingsForm
from .utils import get_system_setting, refresh_settings_cache
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
from django.core.exceptions import ValidationError
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required


# Mevcut signup ve logout fonksiyonlarınız - değişmeyecek
def signup(request):
    """Kullanıcı kayıt sayfası"""
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)  # Kayıt olduktan sonra otomatik giriş yap
            messages.success(request, 'Hesabınız başarıyla oluşturuldu! Hoş geldiniz!')
            return redirect('dashboard')
        else:
            messages.error(request, 'Kayıt sırasında hata oluştu. Lütfen bilgileri kontrol edin.')
    else:
        form = UserCreationForm()

    return render(request, 'jobs/signup.html', {'form': form})


def custom_logout(request):
    """Custom logout view - GET ve POST metodlarını kabul eder"""
    if request.user.is_authenticated:
        username = request.user.username
        logout(request)
        messages.info(request, f'Başarıyla çıkış yaptınız, {username}. Görüşmek üzere!')

    return redirect('login')


def index(request):
    """
    Ana sayfa view fonksiyonu
    İş takip sistemi tanıtım sayfasını render eder
    """
    context = {
        'page_title': 'İş Takip Sistemi',
        'meta_description': 'Gmail API ve Gemini AI ile otomatik iş başvuru takip sistemi',
    }
    return render(request, 'jobs/index.html', context)

@login_required(login_url='login')  # Kullanıcı girişi gereklidir
def analysis_dashboard(request):
    """Giriş yapan kullanıcıya özel analiz dashboard sayfası"""
    user = request.user

    user_applications = JobApplication.objects.filter(user=user)

    context = {
        'total_applications': user_applications.count(),
        'companies_count': user_applications.values('company_name').distinct().count(),
        'this_month_applications': user_applications.filter(
            application_date__month=timezone.now().month,
            application_date__year=timezone.now().year
        ).count(),
        'pending_applications': user_applications.filter(
            status__in=['received', 'reviewing', 'interview', 'waiting']
        ).count()
    }

    return render(request, 'jobs/analysis.html', context)


def get_status_distribution(request):
    """Kullanıcıya özel başvuru durumlarının dağılımını JSON olarak döndürür"""
    # Giriş yapmış kullanıcının başvurularını filtrele
    status_data = JobApplication.objects.filter(user=request.user).values('status').annotate(
        count=Count('id')
    ).order_by('-count')

    # Türkçe etiketleri ekle
    status_labels = {
        'received': 'Başvuru Alındı',
        'reviewing': 'İnceleniyor',
        'interview': 'Mülakat Aşaması',
        'accepted': 'Kabul Edildi',
        'rejected': 'Reddedildi',
        'waiting': 'Geri Dönüş Bekleniyor'
    }

    data = {
        'labels': [status_labels.get(item['status'], item['status']) for item in status_data],
        'data': [item['count'] for item in status_data],
        'colors': [
            '#17a2b8',  # received - info
            '#ffc107',  # reviewing - warning
            '#fd7e14',  # interview - orange
            '#28a745',  # accepted - success
            '#dc3545',  # rejected - danger
            '#6c757d'  # waiting - secondary
        ]
    }

    return JsonResponse(data)


def get_monthly_trend(request):
    """Kullanıcıya özel aylık başvuru trendini döndürür"""
    # Son 12 ayın verilerini al (sadece bu kullanıcıya ait)
    end_date = timezone.now()
    start_date = end_date - timedelta(days=365)

    monthly_data = JobApplication.objects.filter(
        user=request.user,  # Sadece oturum açan kullanıcının verileri
        application_date__gte=start_date
    ).annotate(
        month=TruncMonth('application_date')
    ).values('month').annotate(
        count=Count('id')
    ).order_by('month')

    # Eksik ayları 0 ile doldur
    months = {}
    current_date = start_date.replace(day=1)

    while current_date <= end_date:
        months[current_date.strftime('%Y-%m')] = 0
        if current_date.month == 12:
            current_date = current_date.replace(year=current_date.year + 1, month=1)
        else:
            current_date = current_date.replace(month=current_date.month + 1)

    # Gerçek verileri ekle
    for item in monthly_data:
        key = item['month'].strftime('%Y-%m')
        months[key] = item['count']

    data = {
        'labels': [datetime.strptime(month, '%Y-%m').strftime('%m/%Y') for month in sorted(months.keys())],
        'data': [months[month] for month in sorted(months.keys())]
    }

    return JsonResponse(data)


def get_top_companies(request):
    """Kullanıcının en çok başvuru yaptığı şirketleri döndürür"""
    # Sadece oturum açmış kullanıcının başvurularını filtrele
    company_data = JobApplication.objects.filter(
        user=request.user
    ).values('company_name').annotate(
        count=Count('id')
    ).order_by('-count')[:10]  # En çok başvuru yapılan ilk 10 şirket

    data = {
        'labels': [item['company_name'] for item in company_data],
        'data': [item['count'] for item in company_data]
    }

    return JsonResponse(data)


def get_success_rate_by_company(request):
    """Kullanıcının şirketlere göre başarı oranını döndürür"""
    # Sadece oturum açmış kullanıcının verilerini filtrele
    companies = JobApplication.objects.filter(
        user=request.user
    ).values('company_name').annotate(
        total=Count('id')
    ).filter(total__gte=2).order_by('-total')[:10]  # En az 2 başvuru olan şirketler

    company_success = []

    for company in companies:
        company_name = company['company_name']
        total = company['total']

        accepted = JobApplication.objects.filter(
            user=request.user,
            company_name=company_name,
            status='accepted'
        ).count()

        interview = JobApplication.objects.filter(
            user=request.user,
            company_name=company_name,
            status='interview'
        ).count()

        # Başarı oranını hesapla (kabul + mülakat / toplam)
        success_rate = ((accepted + interview) / total) * 100 if total > 0 else 0

        company_success.append({
            'company': company_name,
            'total': total,
            'success_rate': round(success_rate, 1),
            'accepted': accepted,
            'interview': interview
        })

    # Başarı oranına göre sırala
    company_success.sort(key=lambda x: x['success_rate'], reverse=True)

    data = {
        'labels': [item['company'] for item in company_success],
        'success_rates': [item['success_rate'] for item in company_success],
        'totals': [item['total'] for item in company_success]
    }

    return JsonResponse(data)

def get_weekly_activity(request):
    """Kullanıcının son 8 haftalık başvuru aktivitesini döndürür"""
    end_date = timezone.now()
    start_date = end_date - timedelta(weeks=8)

    # Sadece oturum açmış kullanıcının başvurularını filtrele
    weekly_data = JobApplication.objects.filter(
        user=request.user,
        application_date__gte=start_date
    ).annotate(
        week=TruncWeek('application_date')
    ).values('week').annotate(
        count=Count('id')
    ).order_by('week')

    # Eksik haftaları 0 ile doldur
    weeks = {}
    current_date = start_date

    while current_date <= end_date:
        # Haftanın başına git (Pazartesi)
        week_start = current_date - timedelta(days=current_date.weekday())
        week_key = week_start.strftime('%Y-%m-%d')
        weeks[week_key] = 0
        current_date += timedelta(weeks=1)

    # Gerçek verileri ekle
    for item in weekly_data:
        key = item['week'].strftime('%Y-%m-%d')
        weeks[key] = item['count']

    data = {
        'labels': [datetime.strptime(week, '%Y-%m-%d').strftime('%d/%m') for week in sorted(weeks.keys())],
        'data': [weeks[week] for week in sorted(weeks.keys())]
    }

    return JsonResponse(data)


def get_application_statistics(request):
    """Kullanıcının kişisel başvuru istatistiklerini döndürür"""
    # Sadece oturum açmış kullanıcının başvurularını filtrele
    user_applications = JobApplication.objects.filter(user=request.user)
    total = user_applications.count()

    if total == 0:
        return JsonResponse({
            'total': 0,
            'accepted': 0,
            'rejected': 0,
            'pending': 0,
            'acceptance_rate': 0,
            'rejection_rate': 0,
            'response_rate': 0
        })

    accepted = user_applications.filter(status='accepted').count()
    rejected = user_applications.filter(status='rejected').count()
    pending = user_applications.filter(
        status__in=['received', 'reviewing', 'interview', 'waiting']
    ).count()

    # Oranları hesapla
    acceptance_rate = (accepted / total) * 100 if total > 0 else 0
    rejection_rate = (rejected / total) * 100 if total > 0 else 0
    response_rate = ((accepted + rejected) / total) * 100 if total > 0 else 0

    data = {
        'total': total,
        'accepted': accepted,
        'rejected': rejected,
        'pending': pending,
        'acceptance_rate': round(acceptance_rate, 1),
        'rejection_rate': round(rejection_rate, 1),
        'response_rate': round(response_rate, 1)
    }

    return JsonResponse(data)


def generate_matplotlib_chart(request, chart_type):
    """Matplotlib ile grafik oluşturur ve base64 olarak döndürür"""

    # Türkçe karakter desteği için
    plt.rcParams['font.family'] = ['DejaVu Sans']

    if chart_type == 'status_pie':
        # Durum dağılımı pasta grafiği
        status_data = JobApplication.objects.filter(
            user=request.user
        ).values('status').annotate(
            count=Count('id')
        )

        if not status_data:
            return JsonResponse({'error': 'Veri bulunamadı'}, status=404)

        labels = [item['status'] for item in status_data]
        sizes = [item['count'] for item in status_data]

        plt.figure(figsize=(10, 8))
        plt.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=90)
        plt.title('Başvuru Durumları Dağılımı')
        plt.axis('equal')

    elif chart_type == 'monthly_bar':
        # Aylık başvuru bar grafiği
        monthly_data = JobApplication.objects.filter(
            user=request.user,
            application_date__gte=timezone.now() - timedelta(days=365)
        ).annotate(
            month=TruncMonth('application_date')
        ).values('month').annotate(
            count=Count('id')
        ).order_by('month')

        if not monthly_data:
            return JsonResponse({'error': 'Veri bulunamadı'}, status=404)

        months = [item['month'].strftime('%m/%Y') for item in monthly_data]
        counts = [item['count'] for item in monthly_data]

        plt.figure(figsize=(12, 6))
        plt.bar(months, counts, color='skyblue', alpha=0.7)
        plt.title('Aylık Başvuru Sayıları')
        plt.xlabel('Ay')
        plt.ylabel('Başvuru Sayısı')
        plt.xticks(rotation=45)
        plt.tight_layout()

    else:
        return JsonResponse({'error': 'Geçersiz grafik tipi'}, status=400)

    # Grafiği base64'e çevir
    buffer = io.BytesIO()
    plt.savefig(buffer, format='png', dpi=300, bbox_inches='tight')
    buffer.seek(0)
    image_base64 = base64.b64encode(buffer.getvalue()).decode()
    plt.close()

    return JsonResponse({
        'image': f'data:image/png;base64,{image_base64}'
    })

@login_required(login_url='login')
def dashboard(request):
    """User-specific dashboard view"""
    user = request.user

    # Get all queries through the user's related manager
    total_applications = JobApplication.objects.filter(user=user).count()
    recent_applications = JobApplication.objects.filter(user=user).order_by('-created_at')[:5]

    # Status statistics
    status_counts = {}
    for choice in JobApplication.STATUS_CHOICES:
        status_counts[choice[1]] = JobApplication.objects.filter(
            user=user,
            status=choice[0]
        ).count()

    # Last processing record
    last_processing = None
    if hasattr(user, 'emailprocessinglog_set'):
        last_processing = user.emailprocessinglog_set.order_by('-processed_at').first()

    # CSV files list - KULLANICIYA ÖZEL
    gmail_service = GmailService(user=user)  # Kullanıcı parametresi eklendi
    csv_files = gmail_service.get_user_csv_files()  # Kullanıcıya özel dosyalar

    # Sort CSV files by creation date
    csv_files.sort(key=lambda x: x['created_at'], reverse=True)

    # Recent trend (last 7 days)
    last_week = timezone.now() - timedelta(days=7)
    recent_trend = JobApplication.objects.filter(
        user=user,
        created_at__gte=last_week
    ).count()

    context = {
        'total_applications': total_applications,
        'recent_applications': recent_applications,
        'status_counts': status_counts,
        'last_processing': last_processing,
        'csv_files': csv_files[:5],
        'recent_trend': recent_trend,
    }

    return render(request, 'jobs/dashboard.html', context)


def application_list(request):
    """Kullanıcıya özel iş başvuruları listesi"""
    # Sadece oturum açmış kullanıcının başvurularını al
    applications = JobApplication.objects.filter(user=request.user).order_by('-created_at')

    # Filtreleme
    search = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')

    if search:
        applications = applications.filter(
            Q(company_name__icontains=search) |
            Q(position__icontains=search) |
            Q(email_sender__icontains=search)
        )

    if status_filter:
        applications = applications.filter(status=status_filter)

    # Sayfalama - sayfa başına 20 başvuru
    paginator = Paginator(applications, 20)
    page_number = request.GET.get('page')
    applications = paginator.get_page(page_number)

    # İstatistikler
    total_count = JobApplication.objects.filter(user=request.user).count()
    filtered_count = applications.paginator.count if hasattr(applications, 'paginator') else 0

    context = {
        'applications': applications,
        'search': search,
        'status_filter': status_filter,
        'status_choices': JobApplication.STATUS_CHOICES,
        'total_count': total_count,
        'filtered_count': filtered_count,
    }

    return render(request, 'jobs/application_list.html', context)

@login_required(login_url='login')  # login_url ile giriş sayfasına yönlendir
def application_detail(request, pk):
    """İş başvurusu detay"""
    application = get_object_or_404(JobApplication, pk=pk, user=request.user)

    context = {
        'application': application,
    }

    return render(request, 'jobs/application_detail.html', context)


@login_required(login_url='login')
def settings_view(request):
    """Giriş yapan kullanıcıya özel sistem ayarları sayfası"""

    user = request.user
    # Kullanıcıya ait en son ayarları al (aktif olsun ya da olmasın)
    current_settings = SystemSettings.objects.filter(user=user).order_by('-created_at').first()

    if request.method == 'POST':
        # Yeni instance oluşturmak için None geç
        form = SystemSettingsForm(request.POST)

        if form.is_valid():
            try:
                # Kullanıcının mevcut aktif ayarlarını pasif yap
                SystemSettings.objects.filter(user=user, is_active=True).update(is_active=False)

                # Yeni ayarları kaydet
                new_settings = form.save(commit=False)
                new_settings.user = user
                new_settings.is_active = True
                new_settings.save()

                # Cache'i temizle
                from django.core.cache import cache
                cache.delete(f'system_settings_{user.id}')

                messages.success(
                    request,
                    'Sistem ayarları başarıyla güncellendi. Değişiklikler hemen aktif oldu.'
                )
                return redirect('settings')

            except ValidationError as e:
                messages.error(request, f'Doğrulama hatası: {e}')
            except Exception as e:
                messages.error(request, f'Ayarlar kaydedilirken hata oluştu: {str(e)}')
        else:
            messages.error(request, 'Form verilerinde hatalar var. Lütfen kontrol edin.')
    else:
        # Form için initial değerleri ayarla
        if current_settings:
            form = SystemSettingsForm(initial={
                'email_scan_days': current_settings.email_scan_days,
                'email_scan_limit': current_settings.email_scan_limit,
                'email_batch_size': current_settings.email_batch_size,
                'gemini_api_key': current_settings.gemini_api_key,
                'gemini_cache_ttl': current_settings.gemini_cache_ttl,
            })
        else:
            # İlk kez ayar yapıyorsa default değerlerle form oluştur
            form = SystemSettingsForm()

    # Kullanıcıya ait son 5 ayar geçmişi
    settings_history = SystemSettings.objects.filter(user=user).order_by('-created_at')[:5]

    context = {
        'form': form,
        'current_settings': current_settings,
        'settings_history': settings_history,
        'page_title': 'Sistem Ayarları'
    }

    return render(request, 'jobs/settings.html', context)


@login_required(login_url='login')
@require_http_methods(["POST"])
def reset_settings(request):
    """Giriş yapan kullanıcıya ait ayarları varsayılan değerlere sıfırla"""
    user = request.user
    try:
        # Kullanıcının mevcut aktif ayarlarını pasif yap
        SystemSettings.objects.filter(user=user, is_active=True).update(is_active=False)

        # Kullanıcı için varsayılan ayarları oluştur
        default_settings = SystemSettings.create_default(user=user)

        # Cache'i yenile (kullanıcı bazlı ise)
        refresh_settings_cache()

        messages.success(request, 'Ayarlar varsayılan değerlere sıfırlandı.')

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success', 'message': 'Ayarlar sıfırlandı.'})

    except Exception as e:
        messages.error(request, f'Ayarlar sıfırlanırken hata oluştu: {str(e)}')

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'status': 'error', 'message': str(e)})

    return redirect('settings')


@login_required
def test_settings(request):
    """Mevcut ayarları test et"""
    user = request.user

    try:
        settings = SystemSettings.get_active_settings(user=user)

        # Test sonuçları
        test_results = {
            'gmail_settings': {
                'scan_days': settings.email_scan_days,
                'scan_limit': settings.email_scan_limit,
                'batch_size': settings.email_batch_size,
                'status': 'OK'
            },
            'gemini_settings': {
                'api_key_length': len(settings.gemini_api_key) if settings.gemini_api_key else 0,
                'api_key_valid': len(settings.gemini_api_key) > 10 if settings.gemini_api_key else False,
                'cache_ttl': settings.gemini_cache_ttl,
                'status': 'OK' if settings.gemini_api_key and len(settings.gemini_api_key) > 10 else 'HATA'
            }
        }

        return JsonResponse({
            'status': 'success',
            'results': test_results,
            'message': 'Ayarlar test edildi.'
        })

    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'Test edilirken hata oluştu: {str(e)}'
        })


@login_required(login_url='login')
def sync_emails(request):
    """Gmail'den giriş yapan kullanıcıya ait e-postaları senkronize et ve CSV'ye kaydet"""
    user = request.user

    try:
        # Kullanıcıya özel ayarları al
        from .models import SystemSettings
        settings_obj = SystemSettings.get_cached_user_settings(user)

        if settings_obj:
            scan_days = settings_obj.email_scan_days
            scan_limit = settings_obj.email_scan_limit
        else:
            # Fallback değerler
            scan_days = 5
            scan_limit = 50000

        gmail_service = GmailService(user=user)
        gemini_service = GeminiService()


        # E-postaları getir
        emails, csv_filename = gmail_service.get_recent_emails(
            days=scan_days,
            max_results=scan_limit,
            include_processed=True,
            save_to_csv=True
        )

        if not emails:
            messages.error(request, "E-posta bulunamadı veya CSV oluşturulamadı.")
            return redirect('dashboard')

        total_emails = len(emails)
        job_applications_found = 0
        already_processed = 0

        print(f"Toplam {total_emails} e-posta CSV'den işlenecek...")

        for i, email_data in enumerate(emails, 1):
            print(f"İşleniyor {i}/{total_emails}: {email_data['subject'][:50]}...")

            # Daha önce işlenmiş mi kontrol et (kullanıcı bazlı kontrol)
            if JobApplication.objects.filter(user=user, gmail_message_id=email_data['id']).exists():
                already_processed += 1
                print(f"  → Zaten işlenmiş, atlanıyor")
                continue

            # E-postanın iş başvurusu olup olmadığını kontrol et
            print(f"  → Gemini analiz ediyor...")
            is_job_email = gemini_service.is_job_application_email(
                email_data['subject'],
                email_data['body'],
                email_data['sender']
            )

            if is_job_email:
                print(f"  → İş başvurusu tespit edildi!")

                # İş başvurusu bilgilerini çıkar
                job_info = gemini_service.extract_job_info(
                    email_data['subject'],
                    email_data['body'],
                    email_data['sender']
                )

                # Veritabanına kaydet (user alanı da eklenmeli)
                application = JobApplication.objects.create(
                    user=user,
                    company_name=job_info.get('company_name', 'Bilinmeyen Şirket'),
                    position=job_info.get('position', 'Bilinmeyen Pozisyon'),
                    email_sender=email_data['sender_email'],
                    application_date=email_data['date'],
                    status=job_info.get('status', 'received'),
                    email_subject=email_data['subject'],
                    email_content=email_data['body'][:1000],  # İlk 1000 karakter
                    gmail_message_id=email_data['id'],
                    extracted_info=job_info
                )

                job_applications_found += 1
                print(f"  → Kaydedildi: {application.company_name} - {application.position}")
            else:
                print(f"  → İş başvurusu değil, atlanıyor")

        # İşlem kaydı oluştur (kullanıcı ile birlikte)
        EmailProcessingLog.objects.create(
            user=user,
            total_emails=total_emails,
            job_applications_found=job_applications_found,
            success=True
        )

        # Kullanıcı profilindeki istatistikleri güncelle
        try:
            profile, created = UserProfile.objects.get_or_create(user=user)
            profile.update_application_count()
            profile.last_email_sync = timezone.now()
            profile.save(update_fields=['last_email_sync'])
        except Exception as profile_error:
            print(f"Profil güncelleme hatası: {str(profile_error)}")

        success_message = (
            f"{total_emails} e-posta tarandı, {job_applications_found} yeni iş başvurusu bulundu. "
            f"({already_processed} zaten işlenmiş)"
        )

        if csv_filename:
            success_message += f"\nE-postalar CSV'ye kaydedildi: {csv_filename}"

        messages.success(request, success_message)
        print(f"Senkronizasyon tamamlandı: {job_applications_found} yeni başvuru eklendi")

    except Exception as e:
        print(f"Senkronizasyon hatası: {str(e)}")

        # Hata kaydı oluştur (kullanıcı ile birlikte)
        EmailProcessingLog.objects.create(
            user=user,
            total_emails=0,
            job_applications_found=0,
            success=False,
            error_message=str(e)
        )

        messages.error(request, f"E-posta senkronizasyonu başarısız: {str(e)}")

    return redirect('dashboard')

@login_required(login_url='login')
def process_from_csv(request):
    """Mevcut CSV dosyasından e-postaları işle"""
    if request.method == 'POST':
        csv_filename = request.POST.get('csv_filename')

        if not csv_filename:
            messages.error(request, "CSV dosyası seçilmedi.")
            return redirect('dashboard')

        user = request.user

        try:
            gmail_service = GmailService(user=user)
            gemini_service = GeminiService()

            # CSV'den e-postaları oku
            emails = gmail_service.read_emails_from_csv(csv_filename)

            # emails'in geçerli bir liste olduğunu kontrol et
            if not isinstance(emails, (list, tuple)):
                print(f"Hata: emails beklenen liste değil, tip: {type(emails)}, değer: {emails}")
                messages.error(request, f"CSV okuma hatası: Beklenen veri formatı alınamadı")
                return redirect('dashboard')

            if not emails:
                messages.error(request, f"CSV dosyası bulunamadı veya okunamadı: {csv_filename}")
                return redirect('dashboard')

            total_emails = len(emails)
            job_applications_found = 0
            already_processed = 0

            print(f"CSV'den {total_emails} e-posta işlenecek: {csv_filename}")

            for i, email_data in enumerate(emails, 1):
                # email_data'nın dictionary olduğunu kontrol et
                if not isinstance(email_data, dict):
                    print(f"Uyarı: email_data dictionary değil, tip: {type(email_data)}, değer: {email_data}")
                    continue

                # Gerekli alanların varlığını kontrol et
                required_fields = ['subject', 'body', 'sender', 'id', 'date', 'sender_email']
                missing_fields = [field for field in required_fields if field not in email_data]

                if missing_fields:
                    print(f"Uyarı: Eksik alanlar: {missing_fields}, e-posta atlanıyor")
                    continue

                print(f"İşleniyor {i}/{total_emails}: {email_data['subject'][:50]}...")

                # Daha önce işlenmiş mi kontrol et (KULLANICI BAZLI)
                if JobApplication.objects.filter(user=user, gmail_message_id=email_data['id']).exists():
                    already_processed += 1
                    print(f"  → Zaten işlenmiş, atlanıyor")
                    continue

                # E-postanın iş başvurusu olup olmadığını kontrol et
                print(f"  → Gemini analiz ediyor...")
                try:
                    is_job_email = gemini_service.is_job_application_email(
                        email_data['subject'],
                        email_data['body'],
                        email_data['sender']
                    )

                    # is_job_email'in boolean olduğunu kontrol et
                    if not isinstance(is_job_email, bool):
                        print(f"Uyarı: is_job_email boolean değil, tip: {type(is_job_email)}, değer: {is_job_email}")
                        is_job_email = bool(is_job_email)  # Boolean'a çevir

                except Exception as gemini_error:
                    print(f"  → Gemini analiz hatası: {str(gemini_error)}")
                    continue

                if is_job_email:
                    print(f"  → İş başvurusu tespit edildi!")

                    try:
                        # İş başvurusu bilgilerini çıkar
                        job_info = gemini_service.extract_job_info(
                            email_data['subject'],
                            email_data['body'],
                            email_data['sender']
                        )

                        # job_info'nun dictionary olduğunu kontrol et
                        if not isinstance(job_info, dict):
                            print(f"Uyarı: job_info dictionary değil, tip: {type(job_info)}, değer: {job_info}")
                            # Varsayılan değerlerle dictionary oluştur
                            job_info = {
                                'company_name': 'Bilinmeyen Şirket',
                                'position': 'Bilinmeyen Pozisyon',
                                'status': 'received'
                            }

                        # Veritabanına kaydet (USER ALANI EKLENDİ)
                        application = JobApplication.objects.create(
                            user=user,  # KULLANICI EKLENDİ
                            company_name=job_info.get('company_name', 'Bilinmeyen Şirket'),
                            position=job_info.get('position', 'Bilinmeyen Pozisyon'),
                            email_sender=email_data['sender_email'],
                            application_date=email_data['date'],
                            status=job_info.get('status', 'received'),
                            email_subject=email_data['subject'],
                            email_content=email_data['body'][:1000] if email_data['body'] else '',
                            gmail_message_id=email_data['id'],
                            extracted_info=job_info
                        )

                        job_applications_found += 1
                        print(f"  → Kaydedildi: {application.company_name} - {application.position}")

                    except Exception as extraction_error:
                        print(f"  → İş bilgisi çıkarma hatası: {str(extraction_error)}")
                        continue
                else:
                    print(f"  → İş başvurusu değil, atlanıyor")

            # İşlem kaydı oluştur (KULLANICI İLE BİRLİKTE)
            EmailProcessingLog.objects.create(
                user=user,  # KULLANICI EKLENDİ
                total_emails=total_emails,
                job_applications_found=job_applications_found,
                success=True
            )

            # Kullanıcı profilindeki istatistikleri güncelle
            try:
                profile, created = UserProfile.objects.get_or_create(user=user)
                profile.update_application_count()
                profile.save()
            except Exception as profile_error:
                print(f"Profil güncelleme hatası: {str(profile_error)}")

            messages.success(
                request,
                f"CSV'den {total_emails} e-posta işlendi, {job_applications_found} yeni iş başvurusu bulundu. "
                f"({already_processed} zaten işlenmiş)"
            )

            print(f"CSV işleme tamamlandı: {job_applications_found} yeni başvuru eklendi")

        except Exception as e:
            print(f"CSV işleme hatası: {str(e)}")
            print(f"Hata tipi: {type(e)}")

            # Daha detaylı hata bilgisi
            import traceback
            print(f"Hata detayı: {traceback.format_exc()}")

            # Hata kaydı oluştur (KULLANICI İLE BİRLİKTE)
            EmailProcessingLog.objects.create(
                user=user,  # KULLANICI EKLENDİ
                total_emails=0,
                job_applications_found=0,
                success=False,
                error_message=str(e)
            )

            messages.error(request, f"CSV işleme başarısız: {str(e)}")

    return redirect('dashboard')


@login_required(login_url='login')
def download_csv(request, filename):
    """CSV dosyasını indir - GÜVENLİK KONTROLÜ EKLENDİ"""
    user = request.user

    try:
        gmail_service = GmailService(user=user)

        # GÜVENLİK KONTROLÜ: Dosyanın kullanıcıya ait olup olmadığını kontrol et
        if not gmail_service.is_user_csv_file(filename):
            messages.error(request, "Bu dosyaya erişim yetkiniz yok.")
            return redirect('dashboard')

        csv_path = os.path.join(gmail_service.csv_folder, filename)

        if not os.path.exists(csv_path):
            messages.error(request, f"CSV dosyası bulunamadı: {filename}")
            return redirect('dashboard')

        # Dosyayı indir
        with open(csv_path, 'rb') as file:
            response = HttpResponse(file.read(), content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response

    except Exception as e:
        messages.error(request, f"CSV indirme hatası: {str(e)}")
        return redirect('dashboard')


@login_required(login_url='login')
def view_csv_content(request, filename):
    """CSV dosyasının içeriğini görüntüle - GÜVENLİK KONTROLÜ EKLENDİ"""
    user = request.user

    try:
        gmail_service = GmailService(user=user)

        # GÜVENLİK KONTROLÜ: Dosyanın kullanıcıya ait olup olmadığını kontrol et
        if not gmail_service.is_user_csv_file(filename):
            messages.error(request, "Bu dosyaya erişim yetkiniz yok.")
            return redirect('dashboard')

        csv_path = os.path.join(gmail_service.csv_folder, filename)

        if not os.path.exists(csv_path):
            messages.error(request, f"CSV dosyası bulunamadı: {filename}")
            return redirect('dashboard')

        # CSV'yi oku (ilk 100 satır)
        df = pd.read_csv(csv_path, encoding='utf-8-sig', nrows=100)

        # DataFrame'i HTML tablosuna çevir
        table_html = df.to_html(classes='table table-striped table-bordered', table_id='csvTable')

        csv_info = gmail_service.get_csv_info(filename)

        context = {
            'filename': filename,
            'csv_info': csv_info,
            'table_html': table_html,
            'showing_rows': min(100, len(df)),
            'columns': list(df.columns)
        }

        return render(request, 'jobs/csv_viewer.html', context)

    except Exception as e:
        messages.error(request, f"CSV görüntüleme hatası: {str(e)}")
        return redirect('dashboard')


@login_required(login_url='login')
def delete_csv(request, filename):
    """CSV dosyasını sil - GÜVENLİK KONTROLÜ EKLENDİ"""
    if request.method == 'POST':
        user = request.user

        try:
            gmail_service = GmailService(user=user)

            # GÜVENLİK KONTROLÜ: Dosyanın kullanıcıya ait olup olmadığını kontrol et
            if not gmail_service.is_user_csv_file(filename):
                messages.error(request, "Bu dosyaya erişim yetkiniz yok.")
                return redirect('dashboard')

            csv_path = os.path.join(gmail_service.csv_folder, filename)

            if os.path.exists(csv_path):
                os.remove(csv_path)
                messages.success(request, f"CSV dosyası silindi: {filename}")
            else:
                messages.error(request, f"CSV dosyası bulunamadı: {filename}")

        except Exception as e:
            messages.error(request, f"CSV silme hatası: {str(e)}")

    return redirect('dashboard')


@login_required(login_url='login')
def csv_manager(request):
    """CSV dosyaları yönetim sayfası - KULLANICIYA ÖZEL"""
    user = request.user

    try:
        gmail_service = GmailService(user=user)  # Kullanıcı parametresi eklendi
        csv_files = gmail_service.get_user_csv_files()  # Kullanıcıya özel dosyalar

        # En yeni dosyalar en üstte
        csv_files.sort(key=lambda x: x['created_at'], reverse=True)

        # Sayfalama
        paginator = Paginator(csv_files, 10)
        page_number = request.GET.get('page')
        csv_files_page = paginator.get_page(page_number)

        context = {
            'csv_files': csv_files_page,
            'total_files': len(csv_files),
        }

        return render(request, 'jobs/csv_manager.html', context)

    except Exception as e:
        messages.error(request, f"CSV yönetim hatası: {str(e)}")
        return redirect('dashboard')


@login_required(login_url='login')
def export_applications_to_csv(request):
    """İş başvurularını CSV'ye aktar (sadece giriş yapmış kullanıcının)"""
    user = request.user

    try:
        # Sadece giriş yapmış kullanıcının başvurularını getir
        applications = JobApplication.objects.filter(user=user).order_by('-created_at')

        # CSV için veri hazırla
        csv_data = []
        for app in applications:
            csv_row = {
                'ID': app.id,
                'Şirket': app.company_name,
                'Pozisyon': app.position,
                'Gönderen': app.email_sender,
                'Başvuru Tarihi': app.application_date.strftime('%Y-%m-%d %H:%M:%S'),
                'Durum': app.get_status_display(),
                'E-posta Konusu': app.email_subject,
                'Oluşturma Tarihi': app.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'Gmail ID': app.gmail_message_id,
            }
            csv_data.append(csv_row)

        # DataFrame oluştur ve CSV'ye çevir
        df = pd.DataFrame(csv_data)

        # HTTP response olarak CSV döndür
        response = HttpResponse(content_type='text/csv')
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        response['Content-Disposition'] = f'attachment; filename="job_applications_{user.username}_{timestamp}.csv"'

        # CSV'yi response'a yaz (Türkçe karakterler için)
        df.to_csv(response, index=False, encoding='utf-8-sig')

        return response

    except Exception as e:
        messages.error(request, f"CSV aktarma hatası: {str(e)}")
        return redirect('application_list')


@login_required(login_url='login')
def update_application_status(request, pk):
    """İş başvurusu durumunu güncelle - sadece kendi başvuruları için"""
    if request.method == 'POST':
        # Sadece request.user'a ait başvuruyu getir
        application = get_object_or_404(JobApplication, pk=pk, user=request.user)
        new_status = request.POST.get('status')

        if new_status in [choice[0] for choice in JobApplication.STATUS_CHOICES]:
            old_status = application.get_status_display()
            application.status = new_status
            application.save()

            messages.success(
                request,
                f'Durum "{old_status}" → "{application.get_status_display()}" olarak güncellendi.'
            )
        else:
            messages.error(request, 'Geçersiz durum.')

    return redirect('application_detail', pk=pk)


@login_required(login_url='login')
def delete_application(request, pk):
    """İş başvurusunu sil - sadece kendi başvuruları için"""
    if request.method == 'POST':
        # Sadece request.user'a ait başvuruyu getir
        application = get_object_or_404(JobApplication, pk=pk, user=request.user)
        company_name = application.company_name
        position = application.position

        application.delete()

        messages.success(
            request,
            f'İş başvurusu silindi: {company_name} - {position}'
        )
        return redirect('application_list')

    return redirect('application_detail', pk=pk)

@login_required(login_url='login')
def manual_add_application(request):
    """Manuel iş başvurusu ekleme - kullanıcı ile ilişkilendir"""
    if request.method == 'POST':
        try:
            JobApplication.objects.create(
                user=request.user,  # Kullanıcı ataması burada çok önemli
                company_name=request.POST.get('company_name', ''),
                position=request.POST.get('position', ''),
                email_sender=request.POST.get('email_sender', ''),
                status=request.POST.get('status', 'received'),
                application_date=datetime.now(),
                email_subject='Manuel Ekleme',
                email_content=request.POST.get('notes', ''),
                gmail_message_id=f"manual_{datetime.now().timestamp()}"
            )

            messages.success(request, 'İş başvurusu manuel olarak eklendi.')
            return redirect('application_list')

        except Exception as e:
            messages.error(request, f'Ekleme hatası: {str(e)}')

    context = {
        'status_choices': JobApplication.STATUS_CHOICES,
    }
    return render(request, 'jobs/add_application.html', context)
