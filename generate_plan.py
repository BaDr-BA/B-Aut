import os
import json
import random
import time
from datetime import datetime
import urllib.request             # <-- لجلب اقتراحات جوجل
import urllib.parse               # <-- لتحليل الروابط
from github import Github, Auth
from google import genai
from google.genai import types

# --- الإعدادات الأساسية ---
GEMINI_API_KEYS = [
    os.environ.get("GEMINI_API_KEY_1"),
    os.environ.get("GEMINI_API_KEY_2"),
    os.environ.get("GEMINI_API_KEY_3"),
    os.environ.get("GEMINI_API_KEY_4"),
    os.environ.get("GEMINI_API_KEY_5"),
    os.environ.get("GEMINI_API_KEY_6"),
]
GEMINI_API_KEYS = [key for key in GEMINI_API_KEYS if key]

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO_NAME = "BaDr-BA/B-Aut"

BLOG_CATEGORIES = ["أدوات AI", "شروحات AI", "ربح من AI", "برومبتات AI", "أتمتة AI"]

# سيتم تجربتها بالترتيب من الأقوى للأسرع
GEMINI_MODELS =[
    'gemini-2.5-flash',         # نسخة فلاش الجديدة (عادة تكون متاحة مجاناً وسريعة جداً)
    'gemini-2.0-flash-001',     # النسخة المستقرة الرسمية من 2.0
    'gemini-flash-latest',      # هذا السطر سحابي، سيجلب أحدث نسخة فلاش متاحة لحسابك دائماً
    'gemini-pro-latest'         # هذا السطر سيجلب أحدث نسخة برو 1.5 متاحة لحسابك
]

PLANS_DIRECTORY = "plans"
PUBLISHED_TITLES_FILE_PATH = "published_titles.txt"
MINIMUM_ARTICLES_THRESHOLD = 17

# --- إعدادات فلترة السيو (اتركها None لو أردت أن يكتب من دماغه بدون قيود) ---
TARGET_MIN_SEARCH_VOLUME = 1000  # الحد الأدنى لعمليات البحث
TARGET_MIN_CPC = None            # الحد الأدنى لسعر النقرة بالدولار

# --- (الكود البرمجي) ---

def get_github_repo():
    if not GITHUB_TOKEN:
        raise ValueError("GitHub Token not found.")
    auth = Auth.Token(GITHUB_TOKEN)
    return Github(auth=auth).get_repo(GITHUB_REPO_NAME)

def get_file_content(repo, file_path):
    try:
        return repo.get_contents(file_path).decoded_content.decode('utf-8')
    except Exception:
        return None

def upload_or_update_github_file(repo, file_path, content, commit_message):
    try:
        existing_file = repo.get_contents(file_path)
        repo.update_file(existing_file.path, commit_message, content, existing_file.sha)
        print(f"✅ File updated: {file_path}")
    except Exception:
        repo.create_file(file_path, commit_message, content)
        print(f"✅ File created: {file_path}")

import urllib.request
import urllib.parse

def get_deep_google_suggestions(category):
    """
    تقوم بجلب اقتراحات جوجل الأساسية، ثم تبحث بداخلها (اقتراحات الاقتراحات).
    هذا يضمن لك كلمات مفتاحية (طويلة الذيل Long-tail) عليها بحث حقيقي وضخم.
    """
    print(f"   [Data] Fetching deep autocomplete suggestions for: {category}...")
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    final_keywords = set() # نستخدم set لمنع التكرار
    
    try:
        # 1. جلب الاقتراحات الأساسية
        url = f"http://suggestqueries.google.com/complete/search?client=firefox&q={urllib.parse.quote(category)}&hl=ar"
        req = urllib.request.Request(url, headers=headers)
        response = urllib.request.urlopen(req)
        main_suggestions = json.loads(response.read().decode('utf-8'))[1]
        
        for word in main_suggestions[:5]:
            final_keywords.add(word)
            
            # 2. جلب اقتراحات فرعية لكل كلمة رئيسية (التعمق)
            sub_url = f"http://suggestqueries.google.com/complete/search?client=firefox&q={urllib.parse.quote(word)}&hl=ar"
            sub_req = urllib.request.Request(sub_url, headers=headers)
            try:
                sub_response = urllib.request.urlopen(sub_req)
                sub_suggestions = json.loads(sub_response.read().decode('utf-8'))[1]
                for sub_word in sub_suggestions[:4]:
                    final_keywords.add(sub_word)
            except:
                pass
            time.sleep(10) # استراحة 10 ثواني لمنع الحظر
            
        print(f"   [Data] Successfully found {len(final_keywords)} highly searched keywords.")
        print(f"   [Data] The fetched keywords are: {list(final_keywords)}")
        return list(final_keywords)
        
    except Exception as e:
        print(f"   ⚠️ فشل جلب الاقتراحات: {e}")
        return [category]

def get_content_plan_prompt(category, excluded_titles, real_keywords_list):
    """
    ينشئ البرومبت ويجبر الذكاء الاصطناعي على استخدام البيانات الحقيقية الممررة له فقط!
    """
    # حساب التاريخ الحالي (الشهر والسنة)
    current_date = datetime.now().strftime("%B %Y")
    current_year = datetime.now().strftime("%Y") # 👈 أضفنا استخراج السنة الحالية بدقة
    
    exclusion_prompt = ""
    if excluded_titles:
        titles_text = "\n- ".join(excluded_titles)
        # تعديل بسيط لجعل الرسالة أوضح للنموذج
        exclusion_prompt = f"""
VERY IMPORTANT NOTE: I have already published articles with the following titles.
Do NOT generate these titles again, or titles that are very similar to them:
- {titles_text}
"""

    keywords_text = "\n".join([f"- {kw}" for kw in real_keywords_list])
    # <<< هنا وضعنا البرومبت الطويل الخاص بك بالكامل >>>
    return f"""
بصفتك خبيرًا في تحسين محركات البحث (SEO) وصناعة المحتوى الكتابي المتوافق مع معايير جوجل الجديدة. هدفنا هو بناء "Topical Authority" (سيطرة موضعية) لموقعي لكي يتصدر عالمياً في البحث العربي.
نحن الآن في شهر ({current_date}) من عام ({current_year}).
قمت أنا بسحب هذه الكلمات المفتاحية الحقيقية من بحث جوجل الفعلي (ما يبحث عنه الناس بكثرة الآن):

{keywords_text}

أريدك أن تنشئ لي خطة محتوى بناءً على هذه الكلمات المفتاحية الحقيقية فقط، ممنوع اختراع أو تخمين أي كلمات مفتاحية من عندك.

المطلوب:
1- اختر أقوى الكلمات المفتاحية من القائمة بالأعلى، واقترح 20 عنوان مقال يغطي الكلمات.
2- فلترة الكلمات: تجاهل اسم القسم العام، وتجنب تكرار نفس الكلمات المفتاحية لعناوين مختلفة.
2- كل عنوان يجب أن يكون قابل للبحث لزيادة نسبة النقر إلى الظهور (CTR عالي).
3- كل عنوان يجب أن يكون بين 70 إلى 80 حرفًا.
4- قدم النتائج في جدول احترافي يحتوي على الأعمدة التالية:
عنوان المقال
الكلمة المستهدفة
وصف ميتا
هدف المقال للزائر او للقارئ في حدود 30 كلمة
رقم مؤشر التريند

5- لكل عنوان، أنشئ وصفًا ميتا (Meta Description) يحتوي على الكلمة المفتاحية الحقيقية، يكون مهيأ للسيو الجديد ويتراوح طوله بين 100 إلى 150 حرفًا.
6- حدد "نية الباحث" (Search Intent) بدقة شديدة لكل عنوان من ضمن هذه القائمة فقط (اختر نية واحدة أو نيتين كحد أقصى تناسب العنوان):[معلوماتية, ملاحية, استقصائية, شرائية, محلية, معلومة موجزة, وسائط, بحث مجاني, إجرائية, مختلطة, حداثة/تريند, حل مشكلات, ترفيهية, أريد أن أفعل, أريد أن أذهب, موسمية, مقارنة, ضمنية]
7- 🔴 تحذير زمني صارم: نحن نعيش في عام {current_year}. يُمنع منعاً باتاً كتابة سنوات ماضية في العناوين أو الوصف. إذا استدعى العنوان وجود تاريخ، يجب أن يكون {current_year} حصراً، أو اجعل العنوان بدون تاريخ.

{exclusion_prompt}

CRITICAL FINAL INSTRUCTION: After creating the professional table based on data, your final and ONLY output must be a valid JSON array of objects.
Convert the table you created into this JSON format. Each object in the array must have these exact English keys, corresponding to the table columns:
- "title" (العنوان الاحترافي من زوايا مختلفة)
- "keyword" (الكلمة المفتاحية الحقيقية المذكورة بالأعلى)
- "meta_description" (وصف الميتا)
- "goal" (هدف المقال للزائر في 30 كلمة)
- "search_intent" (نية الباحث التي اخترتها من القائمة المذكورة بالأعلى فقط)


Do not include any text, explanation, or markdown formatting like ```json before or after the JSON array itself.
"""

def generate_plan_for_category(category, excluded_titles):
    if not GEMINI_API_KEYS:
        raise ValueError("No Gemini API keys found.")
    
    # 1. جلب الاقتراحات العميقة (Deep Suggestions)
    real_keywords_list = get_deep_google_suggestions(category)
        
    prompt = get_content_plan_prompt(category, excluded_titles, real_keywords_list)

    # 2. المرور على المفاتيح لتجنب استنفاد الكوتا
    for api_key in GEMINI_API_KEYS:
        print(f"\n   🔄 Trying API Key starting with: {api_key[:8]}...")
        client = genai.Client(api_key=api_key)
        
        for model_name in GEMINI_MODELS:
            print(f"      - Attempting with model: {model_name}...")
            try:
                # نرسل الطلب العادي
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
                
                cleaned_response = response.text.strip().replace("```json", "").replace("```", "")
                new_articles = json.loads(cleaned_response)
                
                if isinstance(new_articles, list):
                    print(f"      🎉 Success! Generated {len(new_articles)} new articles with {model_name}.")
                    return new_articles
                    
            except Exception as e:
                error_msg = str(e)
                print(f"      ❌ Failed with {model_name}. Reason: {error_msg.split('Details:')[0][:150]}...")
                
                if "429" in error_msg or "Quota" in error_msg:
                    print("      ⚠️ ضغط على السيرفر أو انتهاء كوتا.. ننتظر 5 ثوانٍ...")
                    time.sleep(5)
                elif "400" in error_msg:
                    pass 

    raise RuntimeError(f"All keys and models failed to generate a plan for category: {category}")


if __name__ == "__main__":
    try:
        print("🚀 Starting content plan check...")
        repo = get_github_repo()
        
        published_content = get_file_content(repo, PUBLISHED_TITLES_FILE_PATH)
        published_titles = published_content.splitlines() if published_content else []

        for category in BLOG_CATEGORIES:
            print(f"\n🔎 Checking category: '{category}'...")
            plan_path = f"{PLANS_DIRECTORY}/content_plan_{category}.json"
            
            existing_articles = []
            content = get_file_content(repo, plan_path)
            
            if content:
                try: existing_articles = json.loads(content)
                except: existing_articles = []
            
            if len(existing_articles) < MINIMUM_ARTICLES_THRESHOLD:
                print(f"   - Status: Below threshold ({len(existing_articles)}/{MINIMUM_ARTICLES_THRESHOLD}). Regeneration needed.")
                try:
                    all_excluded = set(published_titles + [a['title'] for a in existing_articles])
                    new_articles = generate_plan_for_category(category, list(all_excluded))
                    
                    final_articles = list({a['title']: a for a in existing_articles + new_articles}.values())
                    final_plan_json = json.dumps(final_articles, indent=2, ensure_ascii=False)
                    
                    commit_msg = f"feat: Refresh content plan for '{category}'"
                    upload_or_update_github_file(repo, plan_path, final_plan_json, commit_msg)
                    print(f"   - Plan updated. New total: {len(final_articles)} articles.")

                except (RuntimeError, IOError, ValueError) as e:
                    print(f"   🛑 Regeneration failed for '{category}'. Reason: {e}")
            else:
                print(f"   - Status: Plan is full ({len(existing_articles)} articles). No action needed.")
            
            print("   - Waiting for 180 seconds to avoid rate limiting...")
            time.sleep(180)
        
        print("\n\n🏁 Full check completed.")

    except (ValueError, IOError) as e:
        print(f"\n🛑 Fatal error stopped the process: {e}")
