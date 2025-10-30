import base64
import email
import re
import csv
import pandas as pd
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
import os
import json
from django.conf import settings
import time
from .utils import get_system_setting


class GmailService:
    SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

    def __init__(self, user=None):
        self.service = None
        self.user = user
        self.authenticate()

        # Kullanıcıya özel ayarları al
        if self.user:
            from .models import SystemSettings
            settings_obj = SystemSettings.get_cached_user_settings(self.user)
            self.default_days = settings_obj.email_scan_days if settings_obj else 5
            self.default_max_results = settings_obj.email_scan_limit if settings_obj else 50000
            self.batch_size = settings_obj.email_batch_size if settings_obj else 10
        else:
            # Fallback değerler
            self.default_days = 5
            self.default_max_results = 50000
            self.batch_size = 10

        # Kullanıcıya özel CSV klasörü
        self.csv_folder = self._get_user_csv_folder()
        os.makedirs(self.csv_folder, exist_ok=True)

    def _get_user_csv_folder(self):
        """Kullanıcıya özel CSV klasörünü döndür"""
        base_folder = os.path.join(settings.BASE_DIR, 'email_exports')

        if self.user:
            return os.path.join(base_folder, f'user_{self.user.id}')
        else:
            return os.path.join(base_folder, 'general')

    def get_user_csv_files(self):
        """Sadece kullanıcının CSV dosyalarını getir"""
        csv_files = []

        if not os.path.exists(self.csv_folder):
            return csv_files

        for filename in os.listdir(self.csv_folder):
            if filename.startswith('gmail_emails_') and filename.endswith('.csv'):
                csv_info = self.get_csv_info(filename)
                if csv_info:
                    csv_files.append(csv_info)

        return csv_files

    def is_user_csv_file(self, filename):
        """Dosyanın kullanıcıya ait olup olmadığını kontrol et"""
        file_path = os.path.join(self.csv_folder, filename)
        return os.path.exists(file_path)

    def authenticate(self):
        """Gmail API kimlik doğrulaması"""
        creds = None
        credentials_path = os.path.join(settings.BASE_DIR, 'credentials.json')
        token_path = os.path.join(settings.BASE_DIR, 'token.json')

        # Token dosyası varsa yükle
        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, self.SCOPES)

        # Token geçersizse veya yoksa yenile/oluştur
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    credentials_path, self.SCOPES)
                creds = flow.run_local_server(port=8080)

            # Token'ı kaydet
            with open(token_path, 'w') as token:
                token.write(creds.to_json())

        self.service = build('gmail', 'v1', credentials=creds)

    def get_recent_emails(self, days=None, max_results=None, include_processed=True, save_to_csv=True):
        """
        Son X günün gelen e-postalarını getir ve CSV'ye kaydet

        Args:
            days: Kaç günlük mailleri getir (default: settings'ten)
            max_results: Maksimum mail sayısı (default: settings'ten)
            include_processed: True ise tüm mailler, False ise sadece okunmamış mailler
            save_to_csv: True ise CSV'ye kaydet
        """
        days = days or self.default_days
        max_results = max_results or self.default_max_results

        try:
            # Tarih filtresi oluştur - sadece gelen kutusundaki mailleri al
            after_date = datetime.now() - timedelta(days=days)
            query = f'in:inbox category:primary after:{after_date.strftime("%Y/%m/%d")}'

            # include_processed=False ise sadece okunmamış mailleri al
            if not include_processed:
                query += ' is:unread'

            print(f"Gmail sorgusu: {query}")
            print(f"Tarih aralığı: {after_date.strftime('%Y-%m-%d')} - {datetime.now().strftime('%Y-%m-%d')}")
            print(f"Maksimum mail (istenen): {max_results}")
            print(f"Tüm mailler dahil: {'Evet' if include_processed else 'Hayır (sadece okunmamış)'}")

            # Tüm mesajları topla (pagination ile)
            all_messages = []
            next_page_token = None
            page_count = 0

            while len(all_messages) < max_results:
                page_count += 1
                print(f"Sayfa {page_count} yükleniyor...")

                # Gmail API isteği
                request_params = {
                    'userId': 'me',
                    'q': query,
                    'maxResults': min(500, max_results - len(all_messages))  # Gmail max 500
                }

                if next_page_token:
                    request_params['pageToken'] = next_page_token

                results = self.service.users().messages().list(**request_params).execute()

                messages = results.get('messages', [])
                all_messages.extend(messages)

                total_available = results.get('resultSizeEstimate', len(all_messages))
                print(f"Sayfa {page_count}: {len(messages)} mail - Toplam: {len(all_messages)}/{total_available}")

                # Sonraki sayfa var mı?
                next_page_token = results.get('nextPageToken')
                if not next_page_token or not messages:
                    print("Tüm sayfalar yüklendi!")
                    break

                # Rate limit için kısa bekleme
                time.sleep(0.5)

            print(f"TOPLAM BULUNAN MAIL: {len(all_messages)}")
            print(f"Gmail'de mevcut toplam: {total_available}")

            # Mail detaylarını çek
            emails = []
            processed_count = 0

            # Batch halinde işle (API rate limit için)
            for i in range(0, len(all_messages), self.batch_size):
                batch = all_messages[i:i + self.batch_size]

                for message in batch:
                    email_data = self.get_email_details(message['id'])
                    if email_data:
                        emails.append(email_data)
                        processed_count += 1

                        if processed_count % 50 == 0:  # Her 50 mailde rapor
                            print(f"İşlenen mail: {processed_count}/{len(all_messages)}")

                # Batch'ler arası kısa bekleme (rate limit için)
                if i + self.batch_size < len(all_messages):
                    time.sleep(0.3)

            print(f"TOPLAM İŞLENEN MAIL: {len(emails)}")

            # CSV'ye kaydet
            if save_to_csv and emails:
                csv_filename = self.save_emails_to_csv(emails)
                print(f"E-postalar CSV'ye kaydedildi: {csv_filename}")
                return emails, csv_filename

            return emails, None

        except Exception as e:
            print(f"Gmail API hatası: {str(e)}")
            return [], None

    def save_emails_to_csv(self, emails):
        """E-postaları CSV dosyasına kaydet"""
        try:
            # Dosya adı (tarih ve saat ile)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            csv_filename = f"gmail_emails_{timestamp}.csv"
            csv_path = os.path.join(self.csv_folder, csv_filename)

            # CSV için veri hazırla
            csv_data = []
            for email_data in emails:
                csv_row = {
                    'id': email_data['id'],
                    'subject': email_data['subject'],
                    'sender': email_data['sender'],
                    'sender_email': email_data['sender_email'],
                    'date': email_data['date'].strftime('%Y-%m-%d %H:%M:%S'),
                    'is_read': email_data['is_read'],
                    'body_preview': email_data['body_preview'],
                    'body_full': email_data['body'][:5000],  # İlk 5000 karakter (Excel limiti için)
                    'body_length': len(email_data['body']),
                }
                csv_data.append(csv_row)

            # Pandas ile CSV'ye kaydet (Türkçe karakterler için)
            df = pd.DataFrame(csv_data)
            df.to_csv(csv_path, index=False, encoding='utf-8-sig')  # utf-8-sig Excel için

            print(f"CSV dosyası oluşturuldu: {csv_path}")
            print(f"Toplam satır: {len(csv_data)}")

            return csv_filename

        except Exception as e:
            print(f"CSV kaydetme hatası: {str(e)}")
            return None

    def read_emails_from_csv(self, csv_filename):
        """CSV dosyasından e-postaları oku"""
        try:
            csv_path = os.path.join(self.csv_folder, csv_filename)

            if not os.path.exists(csv_path):
                print(f"CSV dosyası bulunamadı: {csv_path}")
                return []

            # Pandas ile oku
            df = pd.read_csv(csv_path, encoding='utf-8-sig')

            # DataFrame'i dict formatına çevir
            emails = []
            for _, row in df.iterrows():
                email_data = {
                    'id': row['id'],
                    'subject': row['subject'],
                    'sender': row['sender'],
                    'sender_email': row['sender_email'],
                    'date': datetime.strptime(row['date'], '%Y-%m-%d %H:%M:%S'),
                    'is_read': row['is_read'],
                    'body_preview': row['body_preview'],
                    'body': row['body_full'],
                }
                emails.append(email_data)

            print(f"CSV'den {len(emails)} e-posta okundu: {csv_filename}")
            return emails

        except Exception as e:
            print(f"CSV okuma hatası: {str(e)}")
            return []

    def get_latest_csv_file(self):
        """En son oluşturulmuş CSV dosyasını getir"""
        try:
            csv_files = [f for f in os.listdir(self.csv_folder) if f.startswith('gmail_emails_') and f.endswith('.csv')]

            if not csv_files:
                return None

            # Dosya adındaki tarihe göre sırala (en yeni önce)
            csv_files.sort(reverse=True)
            return csv_files[0]

        except Exception as e:
            print(f"CSV dosyası arama hatası: {str(e)}")
            return None

    def get_csv_info(self, csv_filename):
        """CSV dosyası hakkında bilgi getir"""
        try:
            csv_path = os.path.join(self.csv_folder, csv_filename)

            if not os.path.exists(csv_path):
                return None

            # Dosya boyutu
            file_size = os.path.getsize(csv_path)
            file_size_mb = file_size / (1024 * 1024)

            # Dosya oluşturma tarihi
            creation_time = datetime.fromtimestamp(os.path.getctime(csv_path))

            # Satır sayısı (başlık hariç)
            df = pd.read_csv(csv_path, encoding='utf-8-sig')
            row_count = len(df)

            return {
                'filename': csv_filename,
                'path': csv_path,
                'size_mb': round(file_size_mb, 2),
                'created_at': creation_time,
                'row_count': row_count,
                'columns': list(df.columns)
            }

        except Exception as e:
            print(f"CSV bilgi alma hatası: {str(e)}")
            return None

    def get_email_details(self, message_id):
        """Belirli bir e-postanın detaylarını getir"""
        try:
            message = self.service.users().messages().get(
                userId='me',
                id=message_id,
                format='full'
            ).execute()

            headers = message['payload'].get('headers', [])

            # Header bilgilerini çıkar
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '')
            sender = next((h['value'] for h in headers if h['name'] == 'From'), '')
            date_str = next((h['value'] for h in headers if h['name'] == 'Date'), '')

            # E-posta içeriğini çıkar
            body = self.extract_email_body(message['payload'])

            # Tarihi parse et
            try:
                email_date = email.utils.parsedate_to_datetime(date_str)
            except:
                email_date = datetime.now()

            # Ek bilgiler
            sender_email = self.extract_sender_email(sender)

            return {
                'id': message_id,
                'subject': subject,
                'sender': sender,
                'sender_email': sender_email,
                'date': email_date,
                'body': body,
                'body_preview': body[:200] + '...' if len(body) > 200 else body,
                'raw_message': message,
                'is_read': 'UNREAD' not in message.get('labelIds', [])
            }
        except Exception as e:
            print(f"E-posta detay hatası (ID: {message_id}): {str(e)}")
            return None

    def extract_email_body(self, payload):
        """E-posta içeriğini çıkar - Geliştirilmiş versiyon"""
        body = ""

        try:
            if 'parts' in payload:
                # Multipart email - öncelik sırasına göre işle
                body = self._extract_from_multipart(payload['parts'])
            elif payload.get('body') and 'data' in payload['body']:
                # Single part email
                data = payload['body']['data']
                body = self._decode_base64_content(data)

                # HTML ise temizle
                if payload.get('mimeType') == 'text/html':
                    body = self._clean_html_content(body)

        except Exception as e:
            print(f"E-posta body çıkarma hatası: {str(e)}")
            return "İçerik okunamadı"

        return self._clean_and_normalize_text(body)

    def _extract_from_multipart(self, parts):
        """Multipart e-postalardan içerik çıkar"""
        text_content = ""
        html_content = ""

        # Önce tüm part'ları tara
        for part in parts:
            try:
                # Nested parts varsa recursive işle
                if 'parts' in part:
                    nested_content = self._extract_from_multipart(part['parts'])
                    if nested_content:
                        return nested_content

                mime_type = part.get('mimeType', '')
                body_data = part.get('body', {})

                if not body_data.get('data'):
                    continue

                decoded_content = self._decode_base64_content(body_data['data'])

                # Öncelik: text/plain > text/html > diğerleri
                if mime_type == 'text/plain':
                    text_content = decoded_content
                    break  # text/plain bulunca dur
                elif mime_type == 'text/html' and not text_content:
                    html_content = decoded_content
                elif mime_type.startswith('text/') and not text_content and not html_content:
                    text_content = decoded_content

            except Exception as e:
                print(f"Part işleme hatası: {str(e)}")
                continue

        # En uygun içeriği döndür
        if text_content:
            return text_content
        elif html_content:
            return self._clean_html_content(html_content)

        return ""

    def _decode_base64_content(self, data):
        """Base64 kodlanmış içeriği çöz"""
        try:
            # Gmail API'sinden gelen data URL-safe base64 encoded
            decoded_bytes = base64.urlsafe_b64decode(data)

            # Encoding tespiti ve çözümleme
            try:
                return decoded_bytes.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    return decoded_bytes.decode('iso-8859-1')
                except UnicodeDecodeError:
                    try:
                        return decoded_bytes.decode('windows-1252')
                    except UnicodeDecodeError:
                        return decoded_bytes.decode('utf-8', errors='replace')

        except Exception as e:
            print(f"Base64 decode hatası: {str(e)}")
            return ""

    def _clean_html_content(self, html_content):
        """HTML içeriğini temizle ve düz metne çevir"""
        if not html_content:
            return ""

        try:
            # BeautifulSoup kullanımı (eğer mevcut ise)
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html_content, 'html.parser')

                # Script ve style taglarını kaldır
                for script in soup(["script", "style"]):
                    script.decompose()

                # Metin çıkar
                text = soup.get_text()

            except ImportError:
                # BeautifulSoup yoksa regex ile basit temizlik
                text = self._simple_html_cleanup(html_content)

        except Exception as e:
            print(f"HTML temizleme hatası: {str(e)}")
            text = self._simple_html_cleanup(html_content)

        return text

    def _simple_html_cleanup(self, html_content):
        """BeautifulSoup olmadan basit HTML temizleme"""
        import re

        # Script ve style içeriklerini kaldır
        html_content = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        html_content = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL | re.IGNORECASE)

        # HTML taglarını kaldır
        html_content = re.sub(r'<[^>]+>', ' ', html_content)

        # HTML entity'lerini çöz
        import html
        html_content = html.unescape(html_content)

        return html_content

    def _clean_and_normalize_text(self, text):
        """Metni temizle, linkleri kaldır ve normalize et"""
        if not text:
            return ""

        import re

        # --- YENİ EKLENEN KISIM BAŞLANGICI ---

        # 1. Adım: Belirli anahtar ifadelerden sonrasını kes (daha agresif temizlik)
        # Bu, "İş ilanını görüntüleyin:" veya "Unsubscribe" gibi linklerden önceki
        # metni koruyup sonrasını tamamen atar.
        stop_phrases = [
            "İş ilanını görüntüleyin:",
            "View job:",
            "İlanı görüntüle:",
            "Görüntüle:",
            "Unsubscribe",
            "Abonelikten çık",
        ]
        for phrase in stop_phrases:
            # Büyük/küçük harf duyarsız arama yap
            if re.search(phrase, text, re.IGNORECASE):
                # Phrase'in bulunduğu yerden itibaren metni kes
                text = text.split(re.search(phrase, text, re.IGNORECASE).group(0))[0]

        # 2. Adım: Metin içinde kalan tüm URL'leri temizle
        # http, https ile başlayan ve boşluk, satır sonu gibi bir karakterle biten tüm linkleri bulur ve siler.
        text = re.sub(r'https?:\/\/\S+', '', text)

        # www ile başlayan linkleri de temizle (http olmadan yazılmışlarsa)
        text = re.sub(r'www\.\S+', '', text)

        # --- YENİ EKLENEN KISIM SONU ---

        # Fazla boşlukları temizle
        text = re.sub(r'\s+', ' ', text)

        # Satır sonlarını normalize et
        text = re.sub(r'\r\n|\r|\n', '\n', text)

        # Fazla satır atlamalarını temizle (3'ten fazla ardışık newline)
        text = re.sub(r'\n{4,}', '\n\n\n', text)

        # Başlangıç ve sonundaki boşlukları temizle
        text = text.strip()

        # Çok uzun boşlukları kısalt
        text = re.sub(r' {3,}', '  ', text)

        # Özel kontrol karakterlerini temizle
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x84\x86-\x9f]', '', text)

        return text

    def extract_sender_email(self, sender_string):
        """Gönderen string'inden e-posta adresini çıkar"""
        email_pattern = r'[\w\.-]+@[\w\.-]+\.\w+'
        match = re.search(email_pattern, sender_string)
        return match.group(0) if match else sender_string

    def get_email_stats(self, days=None):
        """Gelen kutusundaki e-posta istatistiklerini getir"""
        days = days or self.default_days

        try:
            after_date = datetime.now() - timedelta(days=days)
            # Sadece gelen kutusundaki mailleri say
            query = f'in:inbox after:{after_date.strftime("%Y/%m/%d")}'

            results = self.service.users().messages().list(
                userId='me',
                q=query,
                maxResults=1000  # Sadece sayım için
            ).execute()

            total_emails = results.get('resultSizeEstimate', 0)

            # Okunmamış gelen mailleri say
            unread_query = query + ' is:unread'
            unread_results = self.service.users().messages().list(
                userId='me',
                q=unread_query,
                maxResults=1000
            ).execute()

            unread_emails = unread_results.get('resultSizeEstimate', 0)

            return {
                'total_emails': total_emails,
                'unread_emails': unread_emails,
                'read_emails': total_emails - unread_emails,
                'days_scanned': days,
                'date_range': f"{after_date.strftime('%Y-%m-%d')} - {datetime.now().strftime('%Y-%m-%d')}",
                'scope': 'Sadece gelen kutusu'
            }

        except Exception as e:
            print(f"İstatistik hatası: {str(e)}")
            return None

    def mark_as_read(self, message_id):
        """E-postayı okundu olarak işaretle"""
        try:
            self.service.users().messages().modify(
                userId='me',
                id=message_id,
                body={'removeLabelIds': ['UNREAD']}
            ).execute()
            return True
        except Exception as e:
            print(f"Okundu işaretleme hatası: {str(e)}")
            return False