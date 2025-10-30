from django.contrib import admin
from .models import SystemSettings


@admin.register(SystemSettings)
class SystemSettingsAdmin(admin.ModelAdmin):
    list_display = ['updated_at', 'email_scan_days', 'email_scan_limit', 'is_active']
    list_filter = ['is_active', 'updated_at']
    readonly_fields = ['created_at', 'updated_at']

    def get_readonly_fields(self, request, obj=None):
        if obj and not obj.is_active:
            return self.readonly_fields + ['is_active']
        return self.readonly_fields
