from django.urls import path
from . import views

urlpatterns = [
    # Ana sayfalar
    path('dashboard', views.dashboard, name='dashboard'),
    path('', views.index, name='index'),
    path('applications/', views.application_list, name='application_list'),
    path('applications/<int:pk>/', views.application_detail, name='application_detail'),
    path('applications/add/', views.manual_add_application, name='manual_add_application'),

    # İş başvurusu işlemleri
    path('applications/<int:pk>/update-status/', views.update_application_status, name='update_application_status'),
    path('applications/<int:pk>/delete/', views.delete_application, name='delete_application'),
    path('applications/export/', views.export_applications_to_csv, name='export_applications_to_csv'),

    # E-posta senkronizasyonu
    path('sync-emails/', views.sync_emails, name='sync_emails'),
    path('process-from-csv/', views.process_from_csv, name='process_from_csv'),

    # CSV yönetimi
    path('csv-manager/', views.csv_manager, name='csv_manager'),
    path('csv/download/<str:filename>/', views.download_csv, name='download_csv'),
    path('csv/view/<str:filename>/', views.view_csv_content, name='view_csv_content'),
    path('csv/delete/<str:filename>/', views.delete_csv, name='delete_csv'),

    # Ana analiz dashboard'u
    path('analysis/', views.analysis_dashboard, name='analysis'),

    # JSON API endpoint'leri - interaktif grafikler için
    path('api/status-distribution/', views.get_status_distribution, name='api_status_distribution'),
    path('api/monthly-trend/', views.get_monthly_trend, name='api_monthly_trend'),
    path('api/top-companies/', views.get_top_companies, name='api_top_companies'),
    path('api/success-rate/', views.get_success_rate_by_company, name='api_success_rate'),
    path('api/weekly-activity/', views.get_weekly_activity, name='api_weekly_activity'),
    path('api/statistics/', views.get_application_statistics, name='api_statistics'),

    # Matplotlib grafikleri için (opsiyonel)
    path('api/chart/<str:chart_type>/', views.generate_matplotlib_chart, name='api_matplotlib_chart'),

    # Settings
    path('settings/', views.settings_view, name='settings'),
    path('settings/reset/', views.reset_settings, name='reset_settings'),
    path('settings/test/', views.test_settings, name='test_settings'),

    # Authentication - signup'ı buraya taşıdık
    path('signup/', views.signup, name='signup'),
]