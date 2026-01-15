import os
import json
import random
import time
from github import Github, Auth
import google.generativeai as genai
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# --- الإعدادات والمفاتيح ---
# مفاتيح Gemini (نظام التبديل العشوائي)
GEMINI_API_KEYS = [
    os.environ.get(f"GEMINI_API_KEY_{i}") for i in range(1, 7)
]
GEMINI_API_KEYS = [k for k in GEMINI_API_KEYS if k] # تنظيف القيم الفارغة

# مفاتيح Blogger
CLIENT_ID = os.environ.get("BLOGGER_CLIENT_ID")
CLIENT_SECRET = os.environ.get("BLOGGER_CLIENT_SECRET")
REFRESH_TOKEN = os.environ.get("BLOGGER_REFRESH_TOKEN")
BLOG_ID = os.environ.get("BLOGGER_BLOG_ID")

# إعدادات GitHub
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPO_NAME = "BaDr-BA/B-Aut" # تأكد من اسم المستودع
PLANS_DIR = "plans"

# الموديل المستخدم للكتابة (الأقوى للنصوص الطويلة)
WRITING_MODEL = 'gemini-1.5-pro-latest' 

def get_blogger_service():
    """إنشاء اتصال مع بلوجر باستخدام Refresh Token"""
    creds = Credentials(
        None,
        refresh_token=REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET
    )
    return build('blogger', 'v3', credentials=creds)

def generate_text(prompt):
    """دالة مركزية لتوليد النصوص مع محاولات إعادة في حال الفشل"""
    for _ in range(3): # 3 محاولات
        try:
            key = random.choice(GEMINI_API_KEYS)
            genai.configure(api_key=key)
            model = genai.GenerativeModel(WRITING_MODEL)
            response = model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            print(f"⚠️ Error generating text: {e}. Retrying...")
            time.sleep(5)
    return "" # إرجاع نص فارغ في حال الفشل التام

def create_article_html(article_data):
    """تجميع أجزاء المقال بناءً على البرومبتات المطلوبة"""
    title = article_data['title']
    keyword = article_data['keyword']
    
    print(f"✍️ Writing article: {title}")
    
    html_parts = []
    
    # 1. المقدمة
    p_intro = f"""
    اكتب لي مقدمة لمقال بعنوان ({title}) لنية الباحث كأن خبير بيتكلم احترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو وضمن فيها الكلمة المفتاحية المستهدفة ({keyword}) وتكون المقدمة فقرتين الاولي ثلاث اسطر والثانية ثلاث اسطر.
    فقط اعطني النص بصيغة HTML داخل وسم <p> وبدون عناوين جانبية.
    """
    html_parts.append(generate_text(p_intro))
    time.sleep(3)

    # 2. فقرة تنقيطية
    p_bullets = f"""
    اكتب لي فقرة تنقيطية عن ({keyword}) لنية الباحث تكون اولها مقدمة 200 حرف وتحط النقاط وفي نهايتها ملاحظة 200 حرف مع مرادف اخر للكلمة المفتاحية المستهدفة الأساسية ({keyword}) بشكل طبيعي غير متكلف.
    نسق الإجابة بـ HTML: المقدمة في <p>، النقاط في <ul><li>، والملاحظة في <p> بخط مائل.
    """
    html_parts.append(f"<h2>أهم النقاط حول {keyword}</h2>")
    html_parts.append(generate_text(p_bullets))
    time.sleep(3)

    # 3. فقرة مرقمة
    p_numbered = f"""
    اكتب لي فقرة مرقمة عن خطوات أو مراحل ({keyword}) لنية الباحث تكون اولها مقدمة 200 حرف وتحط الترقيم وفي نهايتها ملاحظة 200 حرف مع مرادف اخر للكلمة المفتاحية المستهدفة الأساسية ({keyword}).
    نسق الإجابة بـ HTML: المقدمة في <p>، القائمة في <ol><li>، والملاحظة في <p>.
    """
    html_parts.append(f"<h2>خطوات عملية</h2>")
    html_parts.append(generate_text(p_numbered))
    time.sleep(3)
    
    # 4. فقرة ايموجية
    p_emoji = f"""
    اكتب لي فقرة ايموجية عن مميزات ({keyword}) لنية الباحث تكون اولها مقدمة 200 حرف وتحط الايموجيات وفي نهايتها ملاحظة 200 حرف.
    نسق الإجابة HTML واستخدم <ul> للقائمة.
    """
    html_parts.append(f"<h2>مميزات {keyword}</h2>")
    html_parts.append(generate_text(p_emoji))
    time.sleep(3)

    # 5. تجربة موقع تقنجي (اللمسة الشخصية)
    p_exp = f"""
    اكتب لي فقرة مميزة بعنوان "خلاصة تجربة موقع تقنجي" حول ({keyword}) بأسلوب شخصي دافئ (First-person perspective) ونصيحة من القلب. الفقرة في حدود 4 أسطر.
    نسقها داخل مربع ملون بـ HTML div style='background-color:#f0f8ff; padding:15px; border-radius:10px; border:1px solid #2196f3'.
    """
    html_parts.append(generate_text(p_exp))
    time.sleep(3)

    # 6. جدول مقارنة
    p_table = f"""
    انشئ لي جدول مقارنة بتنسيق HTML كامل (يأخذ الوان وخط القالب تلقائياً) عن ({keyword}).
    الجدول يجب أن يكون تيفصيلياً ومفيداً.
    """
    html_parts.append(f"<h2>مقارنة تفصيلية</h2>")
    html_parts.append(generate_text(p_table))
    time.sleep(3)

    # 7. الأسئلة الشائعة
    p_faq = f"""
    اكتب لي فقرة 'الأسئلة الشائعة' ذكية عن ({keyword}) تتضمن 5 أسئلة يجري البحث عنها بكثرة.
    نسقها بـ HTML بحيث يكون السؤال في <h3> والإجابة في <p>.
    """
    html_parts.append(f"<h2>الأسئلة الشائعة</h2>")
    html_parts.append(generate_text(p_faq))
    time.sleep(3)

    # 8. الخاتمة
    p_conclusion = f"""
    اكتب لي خاتمة كأن خبير بيتكلم احترافية وتلخص المقال كاملا الذي يتكلم عن ({keyword}) ولا تزيد عن ثلاث اسطر مع دعوة للتعليق.
    نسقها في <p>.
    """
    html_parts.append("<h2>خاتمة</h2>")
    html_parts.append(generate_text(p_conclusion))

    # تجميع الكل
    full_html = "\n".join(html_parts)
    # تنظيف الكود من شوائب Markdown في حال ظهرت
    full_html = full_html.replace("```html", "").replace("```", "")
    
    return full_html

def main():
    # 1. الاتصال بـ GitHub
    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(REPO_NAME)
    
    # 2. اختيار ملف خطة عشوائي (لتنويع الأقسام)
    plan_files = [f for f in repo.get_contents(PLANS_DIR) if f.name.endswith(".json")]
    if not plan_files:
        print("No content plans found.")
        return

    selected_file = random.choice(plan_files)
    print(f"📂 Selected plan: {selected_file.name}")
    
    # قراءة المحتوى
    content_json = json.loads(selected_file.decoded_content.decode("utf-8"))
    
    if not content_json:
        print("Plan is empty.")
        return

    # 3. اختيار المقال الأول
    article_to_write = content_json[0]
    
    # 4. توليد المحتوى
    post_body = create_article_html(article_to_write)
    
    # 5. النشر على Blogger
    try:
        service = get_blogger_service()
        # استخراج اسم القسم من اسم الملف (مثال: content_plan_أدوات AI.json -> أدوات AI)
        category_name = selected_file.name.replace("content_plan_", "").replace(".json", "").replace("_", " ")
        
        post_data = {
            "kind": "blogger#post",
            "blog": {"id": BLOG_ID},
            "title": article_to_write['title'],
            "content": post_body,
            "labels": [category_name],
            "status": "DRAFT"  # أو "LIVE" للنشر المباشر
        }
        
        service.posts().insert(blogId=BLOG_ID, body=post_data).execute()
        print(f"✅ Successfully posted draft: {article_to_write['title']}")
        
        # 6. تحديث ملف الخطة في GitHub (حذف المقال المنشور)
        new_plan = content_json[1:] # حذف العنصر الأول
        updated_content = json.dumps(new_plan, indent=2, ensure_ascii=False)
        repo.update_file(selected_file.path, f"Published: {article_to_write['title']}", updated_content, selected_file.sha)
        print("🗑️ Removed article from plan.")

        # 7. (اختياري) إضافة العنوان للملف المنشور لتجنب التكرار مستقبلاً
        try:
            pub_file = repo.get_contents("published_titles.txt")
            new_pub_content = pub_file.decoded_content.decode("utf-8") + "\n" + article_to_write['title']
            repo.update_file("published_titles.txt", "Add published title", new_pub_content, pub_file.sha)
        except:
            repo.create_file("published_titles.txt", "Create published list", article_to_write['title'])

    except Exception as e:
        print(f"❌ Error publishing to Blogger: {e}")

if __name__ == "__main__":
    main()
