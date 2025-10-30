import google.generativeai as genai
import json
import re
import logging
from typing import Dict, Any, Optional, Tuple
from django.conf import settings

logger = logging.getLogger(__name__)


class GeminiService:
    """
    Gemini 2.0 Flash Exp modelini kullanarak e-postaları analiz eden ve
    iş başvuru sürecine göre sınıflandıran servis sınıfı.
    """

    def __init__(self):
        """Gemini AI servisini başlat"""
        try:
            genai.configure(api_key=settings.GEMINI_API_KEY)

            # Gemini 2.0 Flash Exp modelini kullan (main.py'deki gibi)
            self.model = genai.GenerativeModel(
                model_name="gemini-2.0-flash-exp",
                generation_config={
                    "temperature": 0.1,
                    "top_p": 0.8,
                    "top_k": 40,
                    "max_output_tokens": 1024,
                    "response_mime_type": "application/json",  # JSON formatı zorla
                }
            )
            logger.info("Gemini servisi başarıyla başlatıldı")
        except Exception as e:
            logger.error(f"Gemini servisi başlatılırken hata: {str(e)}")
            raise

    def _is_notification_email(self, sender_email: str, subject: str, body: str) -> bool:
        """
        E-postanın bildirim/alert maili olup olmadığını kontrol eder.

        Args:
            sender_email: Gönderen e-posta adresi
            subject: E-posta konusu
            body: E-posta içeriği

        Returns:
            bool: True ise bildirim maili (atlanmalı), False ise devam edilmeli
        """
        # Bildirim gönderen adresleri
        notification_senders = {
            'jobalerts-noreply@linkedin.com',
            'alert@indeed.com',
            'noreply@glassdoor.com',
            'alerts@monster.com',
            'noreply@kariyer.net',
            'bildirim@secretcv.com',
            'notification@yenibiris.com',
            'aday@e.kariyer.net'
        }

        # Gönderen adres kontrolü
        if sender_email.lower() in notification_senders:
            logger.info(f"Bildirim adresi tespit edildi, mail atlanıyor: {sender_email}")
            return True

        # Konu ve içerik bazlı bildirim tespiti
        notification_keywords = {
            # Türkçe bildirim anahtar kelimeleri
            'yeni iş ilanı', 'iş ilanı yayınlandı', 'size uygun iş',
            'iş fırsatları', 'günlük iş özeti', 'haftalık özet',
            'iş aramanız için', 'aradığınız iş', 'kariyer fırsatları',
            'iş bildirimi', 'iş uyarısı', 'size özel iş','yeni başvuru güncellemeleri',
            'başvurularınızın durumunu'

            # İngilizce bildirim anahtar kelimeleri
            'new job alert', 'job recommendations', 'daily job digest',
            'weekly job summary', 'job opportunities for you',
            'recommended jobs', 'job notifications', 'jobs you might like',
            'job search alert', 'career opportunities', 'job posting alert'
        }

        combined_text = f"{subject} {body}".lower()

        # Bildirim anahtar kelimesi kontrolü
        for keyword in notification_keywords:
            if keyword in combined_text:
                logger.info(f"Bildirim içeriği tespit edildi, mail atlanıyor: {keyword}")
                return True

        return False

    def _has_job_application_indicators(self, subject: str, body: str, sender_email: str) -> bool:
        """
        E-postada iş başvuru sürecine dair güçlü göstergeler olup olmadığını kontrol eder.

        Args:
            subject: E-posta konusu
            body: E-posta içeriği
            sender_email: Gönderen e-posta adresi

        Returns:
            bool: True ise iş başvuru göstergeleri var, False ise yok
        """
        # Güçlü iş başvuru göstergeleri
        strong_indicators = {
            # Türkçe göstergeler
            'başvurunuz', 'başvuru', 'mülakat', 'görüşme', 'pozisyon',
            'iş başvurusu', 'cv', 'özgeçmiş', 'kariyer', 'insan kaynakları',
            'hr', 'işe alım', 'değerlendirme', 'aday', 'başvuru durumu',
            'işe başlama', 'teklif', 'kabul', 'red', 'maalesef',
            'tebrikler', 'seçildiniz', 'işe alındınız',
            'ön görüşme', 'ikinci görüşme', 'telefon görüşmesi',
            'online görüşme', 'video mülakat', 'yüz yüze görüşme',
            'işe alım süreci', 'aday değerlendirme', 'referans kontrolü',
            'iş başlangıcı', 'deneme süresi', 'iş sözleşmesi',
            'çalışma şartları', 'ücret teklifi', 'iş teklif mektubu',
            'iş onayı', 'iş daveti', 'işe giriş tarihi', 'iş teklifi kabulü',
            'iş teklifi reddi',

            # İngilizce göstergeler
            'application', 'interview', 'position', 'job application',
            'resume', 'cv', 'career', 'human resources', 'hiring',
            'evaluation', 'candidate', 'application status', 'employment',
            'offer', 'accepted', 'rejected', 'unfortunately',
            'congratulations', 'selected', 'hired', 'recruiting',
            'talent', 'opportunity', 'role',
            'screening', 'shortlisted', 'assessment', 'test task',
            'reference check', 'background check', 'job start',
            'trial period', 'employment contract', 'job offer letter',
            'salary offer', 'work conditions', 'start date',
            'onboarding', 'phone interview', 'video interview',
            'final interview', 'job confirmation', 'offer acceptance',
            'offer rejection'
        }

        combined_text = f"{subject} {body}".lower()

        # En az bir güçlü gösterge olmalı
        indicator_count = sum(1 for indicator in strong_indicators if indicator in combined_text)

        # Eğer hiç gösterge yoksa, muhtemelen iş başvurusu değildir
        if indicator_count == 0:
            logger.info(f"İş başvuru göstergesi bulunamadı: {subject[:30]}...")
            return False

        # Çok kısa içerikli mailleri (spam/test olabilir) filtrele
        if len(body.strip()) < 10 or len(subject.strip()) < 3:
            logger.info(f"Çok kısa içerik, iş başvurusu olmayabilir: {subject}")
            return False

        # Test/deneme içeriklerini filtrele
        test_patterns = ['deneme', 'test', 'demo', 'asdf', 'qwerty', 'dedede']
        if any(pattern in combined_text for pattern in test_patterns):
            logger.info(f"Test içeriği tespit edildi: {subject}")
            return False

        logger.info(f"İş başvuru göstergeleri bulundu ({indicator_count} adet)")
        return True

    def _is_valid_job_sender(self, sender_email: str) -> bool:
        """
        E-posta adresinin geçerli iş başvuru kaynağı olup olmadığını kontrol eder.

        Args:
            sender_email: Gönderen e-posta adresi

        Returns:
            bool: True ise geçerli kaynak, False ise değil
        """
        # Geçerli iş başvuru gönderen adresleri
        valid_job_senders = {
            'jobs-noreply@linkedin.com',
            'indeedapply@indeed.com',
            'noreply@glassdoor.com',
            'careers@monster.com'
        }

        # Şirket domain'lerinden gelen mailler için pattern
        company_patterns = [
            r'.*@.*\.com',
            r'.*careers@.*',
            r'.*hr@.*',
            r'.*hiring@.*',
            r'.*jobs@.*',
            r'.*recruitment@.*',
            r'.*talent@.*',
            r'.*@peoplise\.com',
            r'.*@.*inside-pmi\.com',
            r'^noreply@.*'
        ]

        sender_lower = sender_email.lower()

        # Bilinen geçerli adresler
        if sender_lower in valid_job_senders:
            return True

        # Şirket pattern kontrolü
        for pattern in company_patterns:
            if re.match(pattern, sender_lower):
                return True

        return False

    def is_job_application_email(self, subject: str, body: str, sender: str) -> bool:
        """
        E-postanın iş başvuru süreciyle ilgili olup olmadığını belirler.

        Args:
            subject: E-posta konusu
            body: E-posta içeriği
            sender: Gönderen bilgisi

        Returns:
            bool: True ise iş başvuru maili, False ise değil
        """
        try:
            # Sender e-mail adresini çıkar
            sender_email = self._extract_email_from_sender(sender)

            # 1. Bildirim maili kontrolü (öncelikli)
            if self._is_notification_email(sender_email, subject, body):
                logger.info(f"Bildirim maili tespit edildi, atlanıyor: {sender_email}")
                return False

            # 2. İş başvuru göstergelerini kontrol et (yeni eklenen)
            if not self._has_job_application_indicators(subject, body, sender_email):
                logger.info(f"İş başvuru göstergesi yok, atlanıyor: {subject[:30]}...")
                return False

            # 3. Geçerli kaynak kontrolü (isteğe bağlı - çok kısıtlayıcı olmamak için)
            # Belirli kaynaklardan geliyorsa doğrudan kabul et
            if sender_email in ['jobs-noreply@linkedin.com', 'indeedapply@indeed.com']:
                logger.info(f"Geçerli iş başvuru kaynağı: {sender_email}")
                return True

            # 4. Gemini AI ile akıllı analiz
            prompt = self._create_job_detection_prompt(subject, body, sender_email)

            response = self.model.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    temperature=0.05,  # Daha düşük sıcaklık - daha tutarlı sonuçlar
                    max_output_tokens=10,  # Kısa yanıt
                )
            )

            result = response.text.strip().lower()
            logger.info(f"Gemini yanıtı: {result}")

            # Sonucu boolean'a çevir
            is_job_email = result in ['true', 'yes', 'evet', '1', 'job']

            if is_job_email:
                logger.info(f"İş başvuru maili tespit edildi: {subject[:50]}...")
            else:
                logger.info(f"İş başvuru maili değil: {subject[:50]}...")

            return is_job_email

        except Exception as e:
            logger.error(f"İş başvuru tespiti hatası: {str(e)}")
            # Hata durumunda False döndür (güvenlik için)
            return False

    # BU YENİ FONKSİYONU SINIFINIZA EKLEYİN
    def classify_email_status(self, subject: str, body: str) -> str:
        """
        E-postanın içeriğini analiz ederek iş başvuru durumunu sınıflandırır.

        Args:
            subject: E-posta konusu
            body: E-posta içeriği

        Returns:
            str: Sınıflandırılmış durum ('received', 'interview', 'rejected', 'offer', 'reviewing')
        """
        try:
            prompt = self._create_status_classification_prompt(subject, body)

            response = self.model.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    temperature=0.0,  # Durum tespiti için netlik önemli
                    max_output_tokens=20
                )
            )

            # Yanıt metnini temizle (JSON olmadığı için basit strip yeterli)
            status = response.text.strip().lower()

            # Olası bir hataya karşı geçerli durumlar listesi
            valid_statuses = ['received', 'reviewing', 'interview', 'offer', 'rejected']

            if status in valid_statuses:
                logger.info(f"E-posta durumu başarıyla sınıflandırıldı: {status}")
                return status
            else:
                logger.warning(f"Geçersiz durum tespiti: '{status}'. Varsayılan 'received' kullanılacak.")
                return 'received'

        except Exception as e:
            logger.error(f"Durum sınıflandırma hatası: {str(e)}")
            return 'received'  # Hata durumunda varsayılan

    # BU YENİ PROMPT OLUŞTURUCUYU DA SINIFINIZA EKLEYİN
    def _create_status_classification_prompt(self, subject: str, body: str) -> str:
        """İYİLEŞTİRİLMİŞ VE YENİ 'pending' DURUMUNU İÇEREN PROMPT"""
        return f"""
        Sen bir iş başvurusu durumu analistisin. Görevin, aşağıdaki e-postanın içeriğini analiz ederek hangi aşamada olduğunu net bir şekilde belirlemek.

        === E-POSTA İÇERİĞİ ===
        Konu: {subject}
        İçerik: {body[:1500]}

        === SINIFLANDIRMA KURALLARI VE ÖNCELİKLER ===
        Kararını aşağıdaki kurallara göre, en spesifik olandan en genele doğru vererek oluştur:

        1. 'offer' (Teklif Aşaması - En Yüksek Öncelik):
           - İçerikte net bir iş teklifi, maaş, sözleşme veya "ekibimize katıldınız" gibi ifadeler varsa bu kategori seçilmelidir.
           - Anahtar Kelimeler: "iş teklifi", "job offer", "teklifimizi sunmak", "sözleşme", "maaş teklifi", "tebrikler ekibimize katıldınız", "welcome to the team", "offer of employment".

        2. 'interview' (Mülakat Aşaması):
           - Belirli bir tarih/saat için görüşme planlaması, müsaitlik sorulması veya online/yüz yüze mülakat daveti içeriyorsa bu kategori seçilmelidir.
           - Anahtar Kelimeler: "mülakat", "görüşme", "interview", "online görüşme", "telefon mülakatı", "sizi tanımak isteriz", "interview invitation", "müsaitliğiniz", "schedule an interview", "case study", "teknik değerlendirme".

        3. 'rejected' (Reddedildi):
           - Sürecin olumsuz sonuçlandığını bildiren, "maalesef", "üzülerek", "başka bir adayla" gibi ifadeler içeren mailler bu kategoriye girer.
           - Anahtar Kelimeler: "maalesef", "üzülerek belirtmek isteriz ki", "unfortunately", "olumsuz", "süreçte ilerleyemiyoruz", "we have decided not to move forward", "başka bir adayla ilerleme kararı aldık", "kariyerinizde başarılar".

        4. 'pending' (Beklemede/Askıya Alındı - YENİ DURUM):
           - Sürecin ne olumlu ne de olumsuz olarak devam ettiğini, başvurunun beklemeye alındığını veya ileride değerlendirileceğini belirten maillerdir.
           - Anahtar Kelimeler: "beklemeye alınmıştır", "on hold", "havuzumuza ekledik", "ilerideki pozisyonlar için", "keep your CV on file", "şu an aktif bir arayışımız bulunmamaktadır ancak", "we will keep you in mind".

        5. 'reviewing' (Aktif İnceleniyor):
           - Başvurunun alındığı onaylandıktan sonra, İK veya ilgili birim tarafından aktif olarak değerlendirildiğini belirten ara bilgilendirme mailleridir. Otomatik "başvurunuz alındı" mesajından bir sonraki adımdır.
           - Anahtar Kelimeler: "başvurunuzu inceliyoruz", "değerlendirme aşamasındadır", "application under review", "CV'niz ilgili departmana iletilmiştir", "we are reviewing your profile", "shortlisted", "ön değerlendirme".

        6. 'received' (Başvuru Alındı - En Genel Durum):
           - Eğer yukarıdaki kategorilerden hiçbiri değilse ve sadece başvurunun sisteme ulaştığına dair otomatik bir onay mesajı ise bu kategori seçilir.
           - Anahtar Kelimeler: "başvurunuz alınmıştır", "başvurunuz için teşekkürler", "application received", "thank you for applying", "başvurunuz bize ulaştı", "your application has been submitted".

        === ÇIKTI FORMATI ===
        Analiz sonucunda SADECE ve SADECE aşağıdaki 6 kelimeden birini yaz:
        received | reviewing | interview | offer | rejected | pending

        Başka hiçbir açıklama, cümle veya ek metin ekleme. Sadece tek bir kelime.
        """

    # MEVCUT extract_job_info FONKSİYONUNUZU BUNUNLA DEĞİŞTİRİN
    def extract_job_info(self, subject: str, body: str, sender: str) -> Dict[str, Any]:
        """
        İş başvuru mailinden detaylı bilgileri çıkarır ve sınıflandırır.
        """
        try:
            sender_email = self._extract_email_from_sender(sender)

            # ADIM 1: Önce e-postanın durumunu yeni fonksiyonla sınıflandır.
            status = self.classify_email_status(subject, body)

            # ADIM 2: Belirlenen durumu ve diğer bilgileri kullanarak bilgi çıkarma prompt'unu oluştur.
            prompt = self._create_job_extraction_prompt(subject, body, sender_email, status)

            # API çağrısı
            response = self.model.generate_content(prompt)
            result_text = response.text.strip()

            logger.info(f"Gemini ham yanıtı: {result_text[:200]}...")

            # JSON temizleme
            cleaned_response = self._clean_json_response(result_text)
            logger.info(f"Temizlenmiş JSON: {cleaned_response}")

            try:
                job_info = json.loads(cleaned_response)

                # Gerekli alanların varlığını kontrol et ve varsayılan değerler ata
                job_info = self._validate_and_complete_job_info(job_info)

                # Durum alanını, bizim sınıflandırdığımız değerle tekrar teyit et.
                # Bu, LLM'in status'u yanlış yazması durumunda bile doğruluğu garantiler.
                job_info['status'] = status

                # LinkedIn özel durumu için post-processing
                job_info = self._post_process_linkedin_info(job_info, subject, body, sender_email)

                logger.info(
                    f"İş bilgisi başarıyla çıkarıldı: {job_info['company_name']} - {job_info['position']} - Durum: {job_info['status']}")
                return job_info

            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse hatası: {e}, varsayılan değerler kullanılacak")
                default_info = self._create_default_job_info(subject, body, sender_email)
                default_info['status'] = status  # Hata durumunda bile doğru durumu ata
                return default_info

        except Exception as e:
            logger.error(f"İş bilgisi çıkarma hatası: {str(e)}")
            default_info = self._create_default_job_info(subject, body, sender_email)
            default_info['status'] = 'received'  # Genel hata durumunda en güvenli varsayılan
            return default_info

    def create_job_detection_prompt(self, subject: str, body: str, sender_email: str) -> str:
        """Geliştirilmiş iş başvuru tespiti için prompt oluşturur"""
        return f"""
                        Sen bir e-posta analiz uzmanısın. Temel görevin, bu e-postanın bir kişinin yaptığı GERÇEK bir iş başvuru sürecinin parçası mı, yoksa genel bir bildirim/reklam/pazarlama e-postası mı olduğunu belirlemek.

                        === E-POSTA BİLGİLERİ ===
                        Gönderen: {sender_email}
                        Konu: {subject}
                        İçerik: {body[:800]}

                        === DÜŞÜNME SÜRECİ ===
                        1.  Bu e-posta, belirli bir kişiye (aday) yönelik mi yazılmış, yoksa herkese gönderilebilecek genel bir içerik mi?
                        2.  Bir başvuru, mülakat, test veya sonuç gibi spesifik bir süreci ilerletiyor mu?
                        3.  Yoksa sadece "yeni iş ilanları", "fırsatlar", "öneriler" gibi genel bir bildirim mi yapıyor?

                        === KARAR KRİTERLERİ ===
                        - EĞER e-posta bir başvuru onayı, durum güncellemesi, mülakat daveti, test görevi, iş teklifi veya ret bildirimi ise: "true" döndür.
                        - EĞER e-posta bir iş ilanı bildirimi (job alert), reklam, haber bülteni, anket veya alakasız bir konu ise: "false" döndür.

                        === ÇIKTI FORMATI ===
                        Sadece ve sadece "true" veya "false" yaz. Başka hiçbir açıklama ekleme.
                        """

    def _create_job_extraction_prompt(self, subject: str, body: str, sender_email: str, status: str) -> str:
        """
        İYİLEŞTİRİLMİŞ VE ESNEK PROMPT: Farklı kaynaklardan gelen e-postalardaki
        bilgileri akıllıca çıkarmak için genel ilkeler ve çeşitli örnekler kullanır.
        """
        return f"""
        Sen deneyimli bir iş başvuru analiz uzmanısın. Görevin, aşağıdaki e-postanın içeriğini dikkatlice analiz ederek temel iş bilgilerini çıkarmak ve bunları JSON formatında sunmaktır.

        === E-POSTA BİLGİLERİ ===
        Gönderen: {sender_email}
        Konu: {subject}
        İçerik: {body}
        ÖNCEDEN BELİRLENEN DURUM: {status}

        === BİLGİ ÇIKARMA İLKELERİ (Esnek Düşün) ===

        1.  🏢 **ŞİRKET ADI (`company_name`):**
            * Şirket adı genellikle konu başlığında ("...X Şirketi'ne başvurunuz"), metnin başında veya e-posta imzasında yer alır.
            * Gönderen e-posta adresinin domain'i (@sirketadi.com) çok güçlü bir ipucudur.
            * Bulduğun isimden "A.Ş.", "Ltd.", "Holding" gibi son ekleri temizle.

        2.  📋 **POZİSYON (`position`):**
            * Pozisyon adı genellikle tırnak içinde, konu başlığında veya metnin ilk paragraflarında belirtilir.
            * "Software Engineer", "Data Analyst", "Ürün Yöneticisi" gibi bir unvan ara.
            * Pozisyon adını bulduğun gibi, kısaltma yapmadan TAMAMEN al.

        3.  📍 **KONUM (`location`):**
            * "İstanbul", "Ankara", "İzmir, Türkiye" gibi şehir/ülke isimlerini ara.
            * "Remote", "Uzaktan", "Hybrid" veya "Hibrit" gibi çalışma şekli belirten kelimelere dikkat et.
            * Eğer konum bilgisi birden fazla yeri içeriyorsa (örn: "İstanbul veya Ankara"), ilkini al.

        4.  🌐 **BAŞVURU KAYNAĞI (`application_source`):**
            * Bu bilgiyi **gönderen e-posta adresinden** çıkar.
            * Eğer 'linkedin.com' içeriyorsa: "LinkedIn"
            * Eğer 'indeed.com' içeriyorsa: "Indeed"
            * Eğer 'kariyer.net' içeriyorsa: "Kariyer.net"
            * Eğer bilinen bir platform değilse, şirket domain'ini kullan (örn: "hr@google.com" ise kaynak "Google" olur).
            * Emin değilsen "Direct Application" yaz.

        === ÇEŞİTLİ ÖRNEKLER ===

        # ÖRNEK 1: LinkedIn'den Gelen Standart Mail
        Gönderen: jobs-noreply@linkedin.com
        Konu: başvurunuz TeknolojiBank şirketine gönderildi
        İçerik: Data Scientist\nTeknolojiBank\nAnkara, Türkiye
        → {{"company_name": "TeknolojiBank", "position": "Data Scientist", "location": "Ankara", "application_source": "LinkedIn"}}

        # ÖRNEK 2: Doğrudan Şirket İK'sından Gelen Mülakat Daveti
        Gönderen: ik@eticaretsepeti.com
        Konu: Mülakat Daveti: Yazılım Geliştirici (Remote)
        İçerik: Merhaba, Eticaret Sepeti şirketimize yaptığınız Yazılım Geliştirici başvurunuzu aldık...
        → {{"company_name": "Eticaret Sepeti", "position": "Yazılım Geliştirici", "location": "Remote", "application_source": "Eticaret Sepeti"}}

        # ÖRNEK 3: Konum Bilgisi Olmayan Genel Bir Mail
        Gönderen: noreply@genelplatform.com
        Konu: Başvurunuz
        İçerik: Merhaba, 'Junior Marketing Specialist' pozisyonu için başvurunuzu aldık.
        → {{"company_name": "Bilinmiyor", "position": "Junior Marketing Specialist", "location": "Bilinmiyor", "application_source": "Direct Application"}}

        === ÇIKTI ===
        Analizinin sonucunu SADECE aşağıdaki JSON formatında, hiçbir ek açıklama olmadan döndür.
        - `status` alanını SANA VERİLEN "{status}" değeriyle doldur.
        - Eğer bir bilgiyi metinde tüm aramana rağmen kesin olarak bulamazsan, tahmin yürütme, "Bilinmiyor" değerini kullan.

        {{
            "company_name": "çıkarılan_şirket_adı",
            "position": "çıkarılan_tam_pozisyon_adı",
            "status": "{status}",
            "location": "çıkarılan_konum_bilgisi",
            "application_source": "çıkarılan_başvuru_kaynağı"
        }}
        """

    def _clean_json_response(self, response: str) -> str:
        """Gemini response'unu temizle (main.py'den)"""
        # ```json bloklarını kaldır
        response = re.sub(r'^```json\s*', '', response.strip(), flags=re.MULTILINE)
        response = re.sub(r'\s*```$', '', response.strip(), flags=re.MULTILINE)

        # İlk { ile son } arasını al
        first_brace = response.find('{')
        last_brace = response.rfind('}')

        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            response = response[first_brace:last_brace + 1]

        return response.strip()

    def _post_process_linkedin_info(self, job_info: Dict[str, Any], subject: str, body: str, sender_email: str) -> Dict[str, Any]:
        """LinkedIn mesajları için geliştirilmiş post-processing"""

        if 'linkedin.com' not in sender_email:
            return job_info

        # Eğer LLM pozisyon bulamadıysa, kendi analiz et
        if not job_info.get('position') or job_info.get('position') == 'Bilinmiyor':

            # Konu başlığından pozisyon çıkarma
            subject_position_patterns = [
                r'(.+?)\s+başvurunuz',  # "Data Scientist başvurunuz"
                r'şirketindeki\s+(.+?)\s+başvurunuz',  # "şirketindeki AI Engineer başvurunuz"
            ]

            for pattern in subject_position_patterns:
                match = re.search(pattern, subject, re.IGNORECASE)
                if match:
                    position_candidate = match.group(1).strip()
                    if self._is_valid_position(position_candidate):
                        job_info['position'] = position_candidate
                        break

            # İçerikten pozisyon çıkarma
            if not job_info.get('position') or job_info.get('position') == 'Bilinmiyor':
                lines = [line.strip() for line in body.split('\n') if line.strip()]

                for line in lines[:5]:  # İlk 5 satırı kontrol et
                    if self._is_position_line_enhanced(line) and not self._is_company_line(line):
                        position_clean = self._clean_position_name(line)
                        if position_clean and position_clean != job_info.get('company_name', ''):
                            job_info['position'] = position_clean
                            break

        # Eğer LLM şirket bulamadıysa, kendi analiz et
        if not job_info.get('company_name') or job_info.get('company_name') == 'Bilinmiyor':
            linkedin_subject_patterns = [
                r'başvurunuz\s+(.+?)\s+şirketine',  # "başvurunuz Chippin şirketine"
                r'(.+?)\s+şirketindeki',  # "Robopine şirketindeki"
            ]

            for pattern in linkedin_subject_patterns:
                match = re.search(pattern, subject, re.IGNORECASE)
                if match:
                    company_raw = match.group(1).strip()
                    company_clean = self._clean_company_name(company_raw)
                    if company_clean:
                        job_info['company_name'] = company_clean
                        break

        job_info['application_source'] = 'LinkedIn'
        return job_info

    def _is_position_line_enhanced(self, line: str) -> bool:
        """Geliştirilmiş pozisyon satırı tespiti"""

        # Çok yaygın pozisyon kelimeleri
        position_keywords = [
            'engineer', 'mühendis', 'developer', 'geliştirici', 'programmer',
            'scientist', 'bilimci', 'analyst', 'analist', 'specialist', 'uzman',
            'manager', 'müdür', 'director', 'direktör', 'lead', 'lider',
            'consultant', 'danışman', 'coordinator', 'koordinatör',
            'designer', 'tasarımcı', 'architect', 'mimar', 'intern', 'stajyer',
            'trainee', 'associate', 'assistant', 'asistan',

            # Teknoloji alanları
            'data', 'veri', 'ai', 'artificial intelligence', 'yapay zeka',
            'machine learning', 'makine öğrenmesi', 'software', 'yazılım',
            'web', 'mobile', 'mobil', 'frontend', 'backend', 'fullstack',
            'devops', 'cloud', 'bulut', 'security', 'güvenlik',

            # Seviye belirteci
            'senior', 'kıdemli', 'junior', 'jr', 'principal', 'chief', 'head'
        ]

        line_lower = line.lower()

        # En az bir pozisyon kelimesi içeriyor mu?
        has_position_keyword = any(keyword in line_lower for keyword in position_keywords)

        # Satır çok kısa değil ve çok uzun değil (pozisyon adları genelde 2-6 kelime)
        word_count = len(line.split())
        reasonable_length = 1 <= word_count <= 8

        # Şirket belirteci içermiyor
        company_indicators = ['şirket', 'company', 'ltd', 'inc', 'corp', 'holding', 'group']
        not_company = not any(indicator in line_lower for indicator in company_indicators)

        # E-posta, URL, tarih içermiyor
        not_technical = not any(char in line for char in ['@', 'http', '.com', '2024', '2025'])

        return has_position_keyword and reasonable_length and not_company and not_technical

    def _is_valid_position(self, text: str) -> bool:
        """Metinin geçerli bir pozisyon adı olup olmadığını kontrol eder"""

        if not text or len(text.strip()) < 2:
            return False

        text_lower = text.lower().strip()

        # Yasaklı kelimeler (şirket adı, platform adı, vb.)
        forbidden_words = [
            'linkedin', 'indeed', 'glassdoor', 'kariyer.net',
            'şirket', 'company', 'başvuru', 'application',
            'gönderildi', 'sent', 'received', 'alındı'
        ]

        if any(word in text_lower for word in forbidden_words):
            return False

        # Pozisyon belirteci içeriyor mu?
        position_indicators = [
            'engineer', 'developer', 'scientist', 'analyst', 'manager',
            'specialist', 'consultant', 'coordinator', 'designer',
            'mühendis', 'geliştirici', 'bilimci', 'analist', 'uzman',
            'data', 'ai', 'artificial', 'software', 'web', 'mobile'
        ]

        return any(indicator in text_lower for indicator in position_indicators)

    def _clean_position_name(self, position_raw: str) -> str:
        """Pozisyon adını temizle ve düzenle"""
        if not position_raw:
            return ""

        position = position_raw.strip()

        # Özel düzeltmeler
        position = re.sub(r'\(Al\)', '(AI)', position)  # (Al) → (AI)
        position = re.sub(r'\bAl\b', 'AI', position)  # Al → AI

        # Gereksiz karakterleri temizle
        position = re.sub(r'[*\-•→←↑↓]+', '', position).strip()
        position = re.sub(r'\s+', ' ', position)  # Çoklu boşlukları temizle

        # Başındaki/sonundaki gereksiz kelimeleri temizle
        clean_patterns = [
            r'^(pozisyon|position|role|job|iş)\s*:?\s*',
            r'\s*(pozisyon|position|role|job|iş)\s*$'
        ]

        for pattern in clean_patterns:
            position = re.sub(pattern, '', position, flags=re.IGNORECASE).strip()

        return position

    def _clean_company_name(self, company_raw: str) -> str:
        """Şirket adını temizle ve düzenle"""
        if not company_raw:
            return ""

        company = company_raw.strip()

        # Büyük harfleri düzenle
        if company.isupper() and len(company) > 3:
            # "EJDER TURİZM" → "Ejder Turizm"
            company = company.title()

        # Gereksiz kelimeleri temizle (sonunda)
        company = re.sub(r'\s+(şirketi|company|ltd\.?|inc\.?|corp\.?|şti\.?|a\.ş\.?|san\.?tic\.?)$',
                         '', company, flags=re.IGNORECASE).strip()

        # Platform isimlerini engelle
        platform_names = ['linkedin', 'indeed', 'glassdoor', 'kariyer.net', 'monster']
        if company.lower() in platform_names:
            return ""

        return company

    def _is_position_line(self, line: str) -> bool:
        """Satırın pozisyon bilgisi içerip içermediğini kontrol et"""
        position_indicators = [
            'engineer', 'mühendis', 'developer', 'geliştirici', 'specialist', 'uzman',
            'analyst', 'analist', 'manager', 'müdür', 'consultant', 'danışman',
            'scientist', 'data', 'yapay zeka', 'artificial', 'intelligence',
            'software', 'yazılım', 'jr.', 'senior', 'lead', 'principal'
        ]

        line_lower = line.lower()
        return any(indicator in line_lower for indicator in position_indicators)

    def _is_company_line(self, line: str) -> bool:
        """Satırın şirket adı içerip içermediğini kontrol et"""
        company_indicators = [
            'şirket', 'company', 'corp', 'ltd', 'inc', 'a.ş', 'şti',
            'turizm', 'agro', 'teknoloji', 'yazılım', 'group', 'holding'
        ]

        line_lower = line.lower()
        return any(indicator in line_lower for indicator in company_indicators)

    def _extract_location_from_line(self, line: str) -> str:
        """Satırdan konum bilgisini çıkar"""
        # Türk şehirleri ve ilçeleri
        turkish_locations = [
            # Büyükşehirler
            'istanbul', 'ankara', 'izmir', 'bursa', 'antalya', 'konya', 'gaziantep',
            'kocaeli', 'adana', 'şanlıurfa', 'mersin', 'eskişehir', 'trabzon',
        ]

        # Uluslararası şehirler
        international_locations = [
            'london', 'amsterdam', 'berlin', 'paris', 'madrid', 'rome',
            'new york', 'san francisco', 'los angeles', 'chicago', 'boston',

            # Çalışma şekilleri
            'remote', 'hybrid', 'onsite'
        ]

        all_locations = turkish_locations + international_locations
        line_lower = line.lower()

        for location in all_locations:
            if location in line_lower:
                return location.title()

        # Türkiye vb ülke isimleri
        if 'türkiye' in line_lower or 'turkey' in line_lower:
            # Şehir adı varsa şehri döndür
            for location in turkish_locations:
                if location in line_lower:
                    return location.title()
            return 'Türkiye'

        return None

    def _extract_email_from_sender(self, sender: str) -> str:
        """Sender stringinden e-posta adresini çıkarır"""
        # E-posta pattern'i ile çıkar
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        match = re.search(email_pattern, sender)

        if match:
            return match.group(0).lower()

        # Pattern bulunamazsa sender'ı olduğu gibi döndür
        return sender.lower().strip()

    def _validate_and_complete_job_info(self, job_info: Dict[str, Any]) -> Dict[str, Any]:
        """Job info dictionary'sini doğrula ve eksik alanları tamamla"""
        # Geçerli status değerleri
        valid_statuses = ['received', 'reviewing', 'interview', 'accepted', 'rejected', 'notification']

        # Varsayılan değerler
        defaults = {
            'company_name': 'Bilinmiyor',
            'position': 'Bilinmiyor',
            'status': 'received',
            'location': 'Bilinmiyor',
            'application_source': 'E-posta'
        }

        # Her alan için kontrol ve tamamlama
        for key, default_value in defaults.items():
            if key not in job_info or not job_info[key] or job_info[key].strip() == '':
                job_info[key] = default_value
            else:
                # String değerleri temizle
                if isinstance(job_info[key], str):
                    job_info[key] = job_info[key].strip()

        # Status değerini doğrula
        if job_info['status'] not in valid_statuses:
            job_info['status'] = 'received'

        # Şirket adı LinkedIn, Indeed vb ise temizle
        invalid_companies = ['linkedin', 'indeed', 'glassdoor', 'kariyer.net', 'monster']
        if job_info['company_name'].lower() in invalid_companies:
            job_info['company_name'] = 'Bilinmiyor'

        return job_info

    def _create_default_job_info(self, subject: str, body: str, sender_email: str) -> Dict[str, Any]:
        """Hata durumunda varsayılan job info oluşturur"""
        company_name = 'Bilinmiyor'
        position = 'Bilinmiyor'
        location = 'Bilinmiyor'
        application_source = 'E-posta'

        # LinkedIn özel işlem
        if 'linkedin.com' in sender_email:
            application_source = 'LinkedIn'

            # Konu başlığından şirket çıkarma
            linkedin_patterns = [
                r'başvurunuz\s+(.+?)\s+şirketine\s+gönderildi',
                r'başvurunuz\s+(.+?)\s+şirketine',
            ]

            for pattern in linkedin_patterns:
                match = re.search(pattern, subject, re.IGNORECASE)
                if match:
                    company_raw = match.group(1).strip()
                    company_clean = self._clean_company_name(company_raw)
                    if company_clean:
                        company_name = company_clean
                    break

            # Mail içeriğinden pozisyon çıkarma
            lines = [line.strip() for line in body.split('\n') if line.strip()]
            for line in lines:
                if self._is_position_line(line) and not self._is_company_line(line):
                    position_clean = self._clean_position_name(line)
                    if position_clean and position_clean != company_name:
                        position = position_clean
                        break

            # Konum çıkarma
            for line in lines:
                location_found = self._extract_location_from_line(line)
                if location_found:
                    location = location_found
                    break

        # Diğer kaynaklar için
        elif 'indeed.com' in sender_email:
            application_source = 'Indeed'
        elif 'glassdoor' in sender_email:
            application_source = 'Glassdoor'

        return {
            'company_name': company_name,
            'position': position,
            'status': 'received',
            'location': location,
            'application_source': application_source
        }

    def get_status_display(self, status_code: str) -> str:
        """Status kodunu Türkçe açıklamaya çevirir"""
        status_map = {
            'received': 'Başvuru Alındı',
            'reviewing': 'Başvuru İnceleniyor',
            'interview': 'Mülakat Aşaması',
            'accepted': 'İş Başvurusu Kabul Edildi',
            'rejected': 'İş Başvurusu Reddedildi',
            'pending':'İş Başvurusu Beklemede'
        }

        return status_map.get(status_code, 'Bilinmeyen Durum')