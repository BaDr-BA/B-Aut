import os
import json
import random
import time
from datetime import datetime
import urllib.request             # <-- لجلب اقتراحات جوجل
import urllib.parse               # <-- لتحليل الروابط
from pytrends.request import TrendReq  # <-- لجلب بيانات جوجل تريندز
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
MINIMUM_ARTICLES_THRESHOLD = 10

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
from pytrends.request import TrendReq

def get_real_keywords_with_trends(category):
    """
    1. تجلب اقتراحات جوجل الحقيقية بناءً على القسم.
    2. تفحصها في جوجل تريندز (عالمياً باللغة العربية).
    3. ترجع فقط الكلمات التي مؤشر اهتمامها فوق المتوسط (أكبر من 40/100).
    """
    print(f"   [Data] Fetching real autocomplete suggestions for: {category}...")
    
    # 1. جلب الاقتراحات الحقيقية من محرك بحث جوجل
    try:
        url = f"http://suggestqueries.google.com/complete/search?client=firefox&q={urllib.parse.quote(category)}&hl=ar"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        response = urllib.request.urlopen(req)
        content = response.read().decode('utf-8')
        suggestions = json.loads(content)[1]
    except Exception as e:
        print(f"   ⚠️ فشل جلب الاقتراحات: {e}")
        suggestions = [category] # نستخدم اسم القسم كبديل

    # 2. فحص الكلمات في جوجل تريندز
    print(f"   [Data] Checking Trends globally for up to 10 keywords...")
    try:
        # hl='ar' تعني الواجهة عربية، geo='' تعني العالم كله (Worldwide)
        pytrend = TrendReq(hl='ar', tz=360) 
        valid_keywords =[]
        
        # نأخذ أول 10 اقتراحات لعدم حظر الـ IP من جوجل تريندز
        for kw in suggestions[:10]: 
            pytrend.build_payload(kw_list=[kw], timeframe='today 1-m', geo='') # تريند اخر شهر
            interest_over_time_df = pytrend.interest_over_time()
            
            if not interest_over_time_df.empty:
                # حساب متوسط الاهتمام في اخر شهر
                avg_interest = interest_over_time_df[kw].mean()
                if avg_interest >= 30: # شرطك: مؤشر الاهتمام يجب ألا يكون ضعيفاً
                    valid_keywords.append({"keyword": kw, "trend_score": round(avg_interest, 1)})
                    print(f"      - Valid Keyword: {kw} (Score: {round(avg_interest, 1)})")
            time.sleep(10) # انتظار لتجنب الحظر
            
        return valid_keywords
    except Exception as e:
        print(f"   ⚠️ فشل الاتصال بجوجل تريندز: {e}")
        return[{"keyword": kw, "trend_score": "N/A"} for kw in suggestions[:10]]

def get_content_plan_prompt(category, excluded_titles, verified_data):
    """
    ينشئ البرومبت ويجبر الذكاء الاصطناعي على استخدام البيانات الحقيقية الممررة له فقط!
    """
    # حساب التاريخ الحالي (الشهر والسنة)
    current_date = datetime.now().strftime("%B %Y")
    
    exclusion_prompt = ""
    if excluded_titles:
        titles_text = "\n- ".join(excluded_titles)
        # تعديل بسيط لجعل الرسالة أوضح للنموذج
        exclusion_prompt = f"""
VERY IMPORTANT NOTE: I have already published articles with the following titles.
Do NOT generate these titles again, or titles that are very similar to them:
- {titles_text}
"""

    # تحويل البيانات الحقيقية لنص ليقرأها النموذج
    data_text = "\n".join([f"- Keyword: {item['keyword']} (Trend Score: {item['trend_score']}/100)" for item in verified_data])

    # <<< هنا وضعنا البرومبت الطويل الخاص بك بالكامل >>>
    return f"""
بصفتك خبيرًا في تحسين محركات البحث (SEO) وصناعة المحتوى الكتابي المتوافق مع معايير جوجل الجديدة. هدفنا هو بناء "Topical Authority" (سيطرة موضعية) لموقعي لكي يتصدر عالمياً في البحث العربي.
قمت أنا بسحب هذه الكلمات المفتاحية الحقيقية ومؤشرات نجاحها من جوجل تريندز عالمياً لشهر ({current_date}).
أريدك أن تنشئ لي خطة محتوى بناءً على هذه البيانات "الحقيقية" فقط، ممنوع اختراع أو تخمين أي أرقام بحث.

الكلمات المفتاحية الحقيقية الموثقة ومؤشر التريند الخاص بها:
{data_text}

المطلوب:
1- استخدم ميزة البحث في جوجل (Google Search) لديك الآن للتحقق من المنافسين وتطوير العناوين لهذه الكلمات اليوم.
2- لكل كلمة مفتاحية حقيقية بالأعلى، أريدك أن تقترح (3 إلى 10) عناوين مقالات تغطي الكلمة من "زوايا مختلفة" بناءً على نتائج البحث الحالية والفعليّة (Real-time data).
3- كل عنوان يجب أن يكون قابل للبحث لزيادة نسبة النقر إلى الظهور (CTR عالي).
4- كل عنوان يجب أن يكون بين 70 إلى 80 حرفًا.
5- قدم النتائج في جدول احترافي يحتوي على الأعمدة التالية:
عنوان المقال
الكلمة المستهدفة
وصف ميتا
هدف المقال للزائر او للقارئ في حدود 30 كلمة
رقم مؤشر التريند

6- لكل عنوان، أنشئ وصفًا ميتا (Meta Description) يحتوي على الكلمة المفتاحية الحقيقية، يكون مهيأ للسيو الجديد ويتراوح طوله بين 100 إلى 150 حرفًا.

{exclusion_prompt}

CRITICAL FINAL INSTRUCTION: After creating the professional table based on data, your final and ONLY output must be a valid JSON array of objects.
Convert the table you created into this JSON format. Each object in the array must have these exact English keys, corresponding to the table columns:
- "title" (العنوان الاحترافي من زوايا مختلفة)
- "keyword" (الكلمة المفتاحية الحقيقية المذكورة بالأعلى)
- "meta_description" (وصف الميتا)
- "goal" (هدف المقال في 30 كلمة)
- "trend_score" (رقم مؤشر التريند كما أعطيته لك بالأعلى)

Do not include any text, explanation, or markdown formatting like ```json before or after the JSON array itself.
"""

def generate_plan_for_category(category, excluded_titles):
    if not GEMINI_API_KEYS:
        raise ValueError("No Gemini API keys found.")
    
    # 1. جلب البيانات الحقيقية من جوجل أولاً
    verified_data = get_real_keywords_with_trends(category)
    if not verified_data:
        raise ValueError(f"لم يتم العثور على كلمات لقسم {category}")
        
    prompt = get_content_plan_prompt(category, excluded_titles, verified_data)

    # 2. المرور على مفاتيح API (Rotation) لحل مشكلة الـ Quota Exceeded
    for api_key in GEMINI_API_KEYS:
        print(f"\n   🔄 Trying API Key starting with: {api_key[:8]}...")
        client = genai.Client(api_key=api_key)
        
        # 3. المرور على النماذج
        for model_name in GEMINI_MODELS:
            print(f"      - Attempting with model: {model_name}...")
            try:
                # نرسل الطلب العادي بدون أداة البحث (لأننا أرسلنا بيانات تريندز في البرومبت)
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
                print(f"      ❌ Failed with {model_name}. Reason: {error_msg.split('Details:')[0][:150]}...") # طباعة جزء صغير من الخطأ لعدم زحمة الـ Log
                
                # إذا كان الخطأ يتعلق بالكوتا (429) ننتظر 5 ثوانِ قبل تجربة النموذج التالي
                if "429" in error_msg or "Quota" in error_msg:
                    print("      ⚠️ ضغط على السيرفر أو انتهاء كوتا.. ننتظر 5 ثوانٍ...")
                    time.sleep(5)
                # إذا ظهر خطأ 400 نتجاوز هذا النموذج تماماً
                elif "400" in error_msg:
                    pass 

    # إذا فشلت كل المفاتيح وكل النماذج
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
