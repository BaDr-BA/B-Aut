import os
import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

def get_blogger_service():
    """
    يقوم هذا التابع بإنشاء اتصال مع واجهة برمجة تطبيقات بلوجر
    باستخدام التوكن المحفوظ في متغيرات البيئة
    """
    
    # 1. تجميع بيانات الاعتماد من البيئة
    client_id = os.environ.get("BLOGGER_CLIENT_ID")
    client_secret = os.environ.get("BLOGGER_CLIENT_SECRET")
    refresh_token = os.environ.get("BLOGGER_REFRESH_TOKEN")
    
    if not all([client_id, client_secret, refresh_token]):
        raise ValueError("❌ بيانات اعتماد بلوجر ناقصة. تأكد من إضافتها في GitHub Secrets.")

    # 2. إنشاء كائن الاعتماد (Credentials) مباشرة باستخدام Refresh Token
    # هذا يغنينا عن عملية تسجيل الدخول اليدوية كل مرة
    creds = Credentials(
        None, # لا يوجد access token مبدئي، سنقوم بجلبه
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret
    )

    # 3. تحديث التوكن (لأن الـ Access Token بيموت كل ساعة)
    request = google.auth.transport.requests.Request()
    creds.refresh(request)

    # 4. بناء الخدمة
    service = build('blogger', 'v3', credentials=creds)
    return service

def create_draft_post(title, content, labels, description):
    """
    إنشاء مسودة جديدة في بلوجر
    """
    try:
        service = get_blogger_service()
        blog_id = os.environ.get("BLOGGER_BLOG_ID")

        # تجهيز جسم المقال
        body = {
            "kind": "blogger#post",
            "title": title,
            "content": content, # هنا سيتم وضع المحتوى (HTML)
            "labels": labels,   # قائمة بالأقسام (Categories)
            "status": "DRAFT"   # مهم جداً: جعلها مسودة وليست منشورة
        }

        # تنفيذ الطلب
        posts = service.posts()
        result = posts.insert(blogId=blog_id, body=body, isDraft=True).execute()

        print(f"✅ تم إنشاء المسودة بنجاح: {result['title']}")
        print(f"🔗 رابط المعاينة: {result['url']}")
        return result['id'] # نرجع الـ ID عشان لو هنحتاجه بعدين

    except Exception as e:
        print(f"❌ حدث خطأ أثناء النشر في بلوجر: {e}")
        return None

# --- كود تجريبي صغير (عشان لما نشغله نتأكد إنه شغال) ---
if __name__ == "__main__":
    # هذا الجزء سيعمل فقط لو شغلت الملف ده لوحده للتجربة
    print("جاري تجربة الاتصال ببلوجر...")
    test_title = "تجربة اتصال أتمتة Python"
    test_content = "<h1>أهلاً بك</h1><p>هذه تجربة لإنشاء مسودة أوتوماتيكية.</p>"
    test_labels = ["تجارب", "أتمتة"]
    
    # تأكد من وجود المتغيرات في جهازك لو بتجرب محلياً، أو سيعتمد على GitHub Actions
    try:
        create_draft_post(test_title, test_content, test_labels, "وصف تجريبي")
    except Exception as err:
        print(f"Error: {err}")
