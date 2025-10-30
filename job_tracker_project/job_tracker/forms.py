from django import forms
from .models import SystemSettings


class SystemSettingsForm(forms.ModelForm):
    """Sistem ayarları formu"""

    class Meta:
        model = SystemSettings
        fields = [
            'email_scan_days',
            'email_scan_limit',
            'email_batch_size',
            'gemini_api_key',
            'gemini_cache_ttl'
        ]

        widgets = {
            'email_scan_days': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'max': '365',
                'step': '1'
            }),
            'email_scan_limit': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '100',
                'max': '500000',
                'step': '100'
            }),
            'email_batch_size': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'max': '100',
                'step': '1'
            }),
            'gemini_api_key': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Gemini API anahtarınızı girin...'
            }),
            'gemini_cache_ttl': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'max': '1440',
                'step': '1'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Form alanları için özel etiketler
        self.fields['email_scan_days'].label = 'E-posta Tarama Günü'
        self.fields['email_scan_limit'].label = 'E-posta Tarama Limiti'
        self.fields['email_batch_size'].label = 'E-posta Batch Boyutu'
        self.fields['gemini_api_key'].label = 'Gemini API Anahtarı'
        self.fields['gemini_cache_ttl'].label = 'Gemini Cache TTL (Dakika)'

        # API key'i opsiyonel yap
        self.fields['gemini_api_key'].required = False

    def clean_email_scan_days(self):
        value = self.cleaned_data['email_scan_days']
        if value < 1 or value > 365:
            raise forms.ValidationError("E-posta tarama günü 1-365 arasında olmalıdır.")
        return value

    def clean_email_scan_limit(self):
        value = self.cleaned_data['email_scan_limit']
        if value < 100 or value > 500000:
            raise forms.ValidationError("E-posta tarama limiti 100-500000 arasında olmalıdır.")
        return value

    def clean_email_batch_size(self):
        value = self.cleaned_data['email_batch_size']
        if value < 1 or value > 100:
            raise forms.ValidationError("E-posta batch boyutu 1-100 arasında olmalıdır.")
        return value

    def clean_gemini_cache_ttl(self):
        value = self.cleaned_data['gemini_cache_ttl']
        if value < 1 or value > 1440:
            raise forms.ValidationError("Gemini cache TTL 1-1440 dakika arasında olmalıdır.")
        return value

    def clean_gemini_api_key(self):
        value = self.cleaned_data.get('gemini_api_key', '').strip()

        # API key boş olabilir (opsiyonel)
        if not value:
            return value

        # Eğer girilmişse minimum uzunluk kontrolü
        if len(value) < 10:
            raise forms.ValidationError("Geçerli bir Gemini API anahtarı girin (en az 10 karakter).")

        return value

    def save(self, commit=True):
        instance = super().save(commit=False)
        # Yeni kayıt için is_active'i True yap
        instance.is_active = True

        if commit:
            instance.save()
        return instance