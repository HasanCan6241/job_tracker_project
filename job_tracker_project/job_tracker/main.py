#!/usr/bin/env python3
"""
Standalone Gemini Job Extraction Test Script
Gemini 2.0 Flash Exp modeli ile test
"""

import json
import re
from typing import Dict, Any
import google.generativeai as genai


class JobExtractionTester:
    def __init__(self, api_key: str):
        """Initialize with Gemini API key"""
        genai.configure(api_key=api_key)

        # Gemini 2.0 Flash Exp modelini kullan
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

    def create_job_extraction_prompt(self, subject: str, body: str, sender_email: str) -> str:
        """İyileştirilmiş prompt"""
        return f"""
Sen deneyimli bir iş başvuru analiz uzmanısın. E-postadan iş bilgilerini çıkarıp JSON formatında döndür.

=== E-POSTA ===
Gönderen: {sender_email}
Konu: {subject}
İçerik: {body}

=== ÇIKARIM KURALLARI ===

🏢 ŞİRKET ADI ÇIKARMA:
1. Konu başlığından: "başvurunuz [ŞİRKET] şirketine" → ŞİRKET
2. İçerik satırlarından şirket adı bul

📋 POZİSYON ÇIKARMA:
1. Konu başlığından: "Data Scientist başvurunuz" → "Data Scientist"
2. İçerik satırlarından pozisyon bul
3. TAMAMEN al, kısaltma yapma!

LinkedIn Mail Format Analizi:
- Satır 1: "başvurunuz [ŞİRKET] şirketine gönderildi"
- Satır 2: "[POZİSYON ADI]" ← BURADAN AL!
- Satır 3: "[ŞİRKET ADI]"
- Satır 4: "[KONUM]"

=== ÖRNEKLER ===
Konu: "başvurunuz Yapı Kredi Yatırım şirketine gönderildi"
İçerik: "Data Analysis Intern\\nYapı Kredi Yatırım\\nİstanbul"
→ {{"company_name": "Yapı Kredi Yatırım", "position": "Data Analysis Intern"}}

=== ÇIKTI ===
Sadece bu JSON formatında döndür:
{{
    "company_name": "şirket_adı_veya_Bilinmiyor",
    "position": "tam_pozisyon_adı_veya_Bilinmiyor",
    "status": "received",
    "location": "konum_veya_Bilinmiyor",
    "application_source": "LinkedIn"
}}
"""

    def _clean_json_response(self, response: str) -> str:
        """Gemini response'unu temizle"""
        # ```json bloklarını kaldır
        response = re.sub(r'^```json\s*', '', response.strip(), flags=re.MULTILINE)
        response = re.sub(r'\s*```$', '', response.strip(), flags=re.MULTILINE)

        # İlk { ile son } arasını al
        first_brace = response.find('{')
        last_brace = response.rfind('}')

        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            response = response[first_brace:last_brace + 1]

        return response.strip()

    def test_job_extraction(self, subject: str, body: str, sender_email: str) -> Dict[str, Any]:
        """Test job extraction with debug info"""

        print(f"\n{'=' * 60}")
        print(f"TEST BAŞLANGIÇ")
        print(f"{'=' * 60}")
        print(f"📧 Konu: {subject}")
        print(f"👤 Gönderen: {sender_email}")
        print(f"📝 İçerik: {body[:150]}...")

        try:
            # 1. Prompt oluştur
            prompt = self.create_job_extraction_prompt(subject, body, sender_email)
            print(f"\n🔧 Prompt uzunluğu: {len(prompt)} karakter")

            # 2. API çağrısı
            print(f"\n🚀 Gemini API çağrısı...")
            response = self.model.generate_content(prompt)
            raw_response = response.text

            print(f"\n📨 HAM GEMINI RESPONSE:")
            print(f"Uzunluk: {len(raw_response)} karakter")
            print(f"İçerik:\n{'-' * 40}")
            print(raw_response)
            print(f"{'-' * 40}")

            # 3. JSON temizleme
            cleaned_response = self._clean_json_response(raw_response)
            print(f"\n🧹 TEMİZLENMİŞ RESPONSE:")
            print(cleaned_response)

            # 4. JSON parse
            try:
                job_info = json.loads(cleaned_response)
                print(f"\n✅ JSON PARSE BAŞARILI:")
                print(json.dumps(job_info, indent=2, ensure_ascii=False))

                # 5. Sonuç analizi
                print(f"\n📊 SONUÇ ANALİZİ:")
                print(f"🏢 Şirket: {job_info.get('company_name', 'BULUNAMADI')}")
                print(f"💼 Pozisyon: {job_info.get('position', 'BULUNAMADI')}")
                print(f"📍 Konum: {job_info.get('location', 'BULUNAMADI')}")
                print(f"🔗 Kaynak: {job_info.get('application_source', 'BULUNAMADI')}")

                return job_info

            except json.JSONDecodeError as e:
                print(f"\n❌ JSON PARSE HATASI:")
                print(f"Hata: {e}")
                print(f"Sorunlu JSON: {cleaned_response}")
                return {"error": "JSON parse failed", "raw": cleaned_response}

        except Exception as e:
            print(f"\n💥 GENEL HATA:")
            print(f"Hata tipi: {type(e).__name__}")
            print(f"Hata mesajı: {e}")
            return {"error": str(e)}


def main():
    """Ana test fonksiyonu"""

    # API KEY'i buraya girin
    API_KEY = "AIzaSyCrDiIEDqmecqaz-M6rRlNT_-zo2p4AB7w"  # BURAYA API KEY GİRİN!

    if API_KEY == "YOUR_GEMINI_API_KEY_HERE":
        print("❌ HATA: API_KEY değişkenine gerçek Gemini API anahtarınızı girin!")
        print("Google AI Studio'dan API key alabilirsiniz: https://makersuite.google.com/app/apikey")
        return

    # Test oluştur
    tester = JobExtractionTester(API_KEY)

    # Test cases - Sizin örnekleriniz
    test_cases = [
        {
            "name": "TEST 1 - Yapı Kredi Yatırım",
            "subject": "başvurunuz Yapı Kredi Yatırım şirketine gönderildi",
            "body": "Data Analysis Intern\nYapı Kredi Yatırım\nİstanbul, Türkiye",
            "sender": "jobs-noreply@linkedin.com"
        },
        {
            "name": "TEST 2 - Chippin",
            "subject": "başvurunuz Chippin şirketine gönderildi",
            "body": "Data Scientist\nChippin\nİstanbul, Türkiye",
            "sender": "jobs-noreply@linkedin.com"
        },
        {
            "name": "TEST 3 - Joygame",
            "subject": "başvurunuz Joygame Publishing şirketine gönderildi",
            "body": "AI Specialist\nJoygame Publishing\nİstanbul",
            "sender": "jobs-noreply@linkedin.com"
        },
        {
            "name": "TEST 4 - QNB Türkiye",
            "subject": "başvurunuz QNB Türkiye şirketine gönderildi",
            "body": "Data Scientist\nQNB Türkiye\nİstanbul, Türkiye",
            "sender": "jobs-noreply@linkedin.com"
        },
        {
            "name": "TEST 5 - Robopine",
            "subject": "Robopine şirketindeki Artificial Intelligence Engineer başvurunuz",
            "body": "Robopine şirketinden güncellemeleriniz\n----------------------------------------\nBu e-posta, Hasan Can Çelik (Data Scientist / Machine Learning & AI Engineer) için gönderilmiştir\nBuna neden yer verdiğimizi öğrenin: LinkedIn bildirim e-postaları alıyorsunuz.\nAboneliği İptal Edin",
            "sender": "jobs-noreply@linkedin.com"

        },
        {
            "name": "TEST 6 - PMI ",
            "subject": "Your application for Data Scientist (Remote) (​9436​)",
            "body": "We want to thank you for your interest in the position of Data Scientist (Remote) (9436), and for taking the time to apply. We appreciate the effort you put into your application, which was one of many that we received. Although your resume was impressive, we regret to inform you that we have decided not to move forward with your application at this time. We understand how disappointing this news can be and want you to know that we value the time you took to apply. Please know that your profile was given careful consideration, and we appreciate your interest in working with us. At PMI, we are always looking for new talent for exciting opportunities, and we encourage you to keep your profile updated with us. We would love to stay in touch with you about potential future openings. We understand this may be a setback, but we wish you all the best in your job search. We appreciate your interest in PMI and thank you for considering us as a potential employer.",
            "sender": "notification@careers.inside-pmi.com"

        }
    ]

    # Tüm testleri çalıştır
    results = []
    for test_case in test_cases:
        print(f"\n\n🔬 {test_case['name']}")
        result = tester.test_job_extraction(
            test_case["subject"],
            test_case["body"],
            test_case["sender"]
        )
        results.append({
            "test_name": test_case["name"],
            "result": result
        })

    # Özet rapor
    print(f"\n\n{'=' * 80}")
    print(f"📋 ÖZET RAPOR")
    print(f"{'=' * 80}")

    for i, result in enumerate(results, 1):
        print(f"\n{i}. {result['test_name']}:")
        if "error" not in result["result"]:
            r = result["result"]
            print(f"   🏢 Şirket: {r.get('company_name', 'N/A')}")
            print(f"   💼 Pozisyon: {r.get('position', 'N/A')}")
            print(f"   ✅ Durum: BAŞARILI")
        else:
            print(f"   ❌ Durum: HATA - {result['result']['error']}")


if __name__ == "__main__":
    main()