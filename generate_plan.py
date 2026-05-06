import os
import json
import random
import time
from datetime import datetime
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
    'models/gemini-3.1-pro-preview',
    'models/deep-research-preview-04-2026',
    'models/gemini-3-flash-preview',
    'models/gemini-2.5-pro'
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
    2. تفحصها في جوجل تريندز.
    3. ترجع فقط الكلمات التي مؤشر اهتمامها فوق المتوسط (أكبر من 40/100).
    """
    print(f"   [Data] Fetching real autocomplete suggestions for: {category}...")
    real_keywords =[]
    
    # 1. جلب الاقتراحات الحقيقية من محرك بحث جوجل
    try:
        url = f"http://suggestqueries.google.com/complete/search?client=firefox&q={urllib.parse.quote(category)}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        response = urllib.request.urlopen(req)
        content = response.read().decode('utf-8')
        suggestions = json.loads(content)[1]
    except Exception as e:
        print(f"   ⚠️ فشل جلب الاقتراحات: {e}")
        suggestions = [category] # نستخدم اسم القسم كبديل

    # 2. فحص الكلمات في جوجل تريندز
    print(f"   [Data] Checking Trends interest for {len(suggestions)} keywords...")
    try:
        pytrend = TrendReq(hl='ar-EG', tz=360) # موجه للمنطقة العربية/مصر
        valid_keywords =[]
        
        # نأخذ أول 5 اقتراحات لعدم حظر الـ IP من جوجل تريندز
        for kw in suggestions[:5]: 
            pytrend.build_payload(kw_list=[kw], timeframe='today 1-m') # تريند اخر شهر
            interest_over_time_df = pytrend.interest_over_time()
            
            if not interest_over_time_df.empty:
                # حساب متوسط الاهتمام في اخر شهر
                avg_interest = interest_over_time_df[kw].mean()
                if avg_interest >= 40: # شرطك: مؤشر الاهتمام يجب ألا يكون ضعيفاً
                    valid_keywords.append({"keyword": kw, "trend_score": round(avg_interest, 1)})
            time.sleep(2) # انتظار لتجنب الحظر
            
        return valid_keywords
    except Exception as e:
        print(f"   ⚠️ فشل الاتصال بجوجل تريندز: {e}")
        return[{"keyword": kw, "trend_score": "N/A"} for kw in suggestions[:5]]

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
بصفتك خبيرًا في تحسين محركات البحث (SEO) وصناعة المحتوى الكتابي المتوافق مع معايير جوجل الجديدة اخر الاحداث معاييرها وأحدث الأحداث (Trends of {current_date})،
أريدك أن تنشئ لي خطة محتوى بناءً على هذه البيانات "الحقيقية" فقط، ممنوع اختراع أو تخمين أي أرقام بحث.

الكلمات المفتاحية الحقيقية الموثقة ومؤشر التريند الخاص بها:
{data_text}

المطلوب:
1- استخدام أداة البحث في جوجل (Google Search) للبحث عن مقالات المنافسين لهذه الكلمات اليوم.
2- اقتراح (20) عنوان مقال بناءً على نتائج البحث الحالية والفعليّة (Real-time data) مستخرج من:
اقتراحات جوجل التلقائية الحالية (تم البحث أيضًا عن).
قسم "الناس أيضًا يسألون" (People Also Ask).
قسم أسئلة أخرى.
أحدث ما يبحث عنه الناس الآن في مجال {category}.
أدوات تحليل الكلمات المفتاحية (مثل Google Keyword Planner، Ubersuggest، SEMrush، Ahrefs، Keywordtool.io، AnswerThePublic، Google Trends، واي ادوات اخري).

3- كل عنوان يجب أن يكون قابل للبحث، احترافي وجذاب ومشوق للزائر لزيادة نسبة النقر إلى الظهور (CTR).

4- قدم النتائج في جدول احترافي يحتوي على الأعمدة التالية:
عنوان المقال
الكلمة المستهدفة
وصف ميتا
هدف المقال للزائر او للقارئ في حدود 20 كلمة
نسبة المنافسة على الكلمة
متوسط عدد عمليات البحث الشهرية
سعر الكلمة المفتاحية (Cost Per Click)

5- كل عنوان يجب أن يكون بين 70 إلى 80 حرفًا.

6- لكل عنوان، أنشئ وصفًا ميتا (Meta Description) يحتوي على الكلمة المفتاحية، يكون احترافي وفضولي ومشوقًا وجذابًا ويتراوح طوله بين 100 إلى 150 حرفًا.

{exclusion_prompt}

CRITICAL FINAL INSTRUCTION: After creating the professional table based on REAL-TIME Search data, your final and ONLY output must be a valid JSON array of objects.
Convert the table you created into this JSON format. Each object in the array must have these exact English keys, corresponding to the table columns:
- "title" (for a'enwan almaqal)
- "keyword" (for alklimat almustahdafa)
- "meta_description" (for wasf mita)
- "goal" (for hadaf almaqal lilzayir)
- "competition" (for nisbat almunafasa)
- "search_volume" (for mutawasit eadad eamaliat albahth)
- "cpc" (for saer alklimat almuftahia)

Do not include any text, explanation, or markdown formatting like ```json before or after the JSON array itself.
"""

# <--- التغيير الثاني هنا: أعدنا حلقة المحاولة والتنقل بين النماذج مع تفعيل البحث
def generate_plan_for_category(category, excluded_titles):
    if not GEMINI_API_KEYS:
        raise ValueError("No Gemini API keys found.")
    
    # إعداد العميل (Client) للمكتبة الجديدة
    api_key = random.choice(GEMINI_API_KEYS)
    client = genai.Client(api_key=api_key)
    prompt = get_content_plan_prompt(category, excluded_titles)

    # حلقة المرور على النماذج
    for model_name in GEMINI_MODELS:
        print(f"   - Attempting with model: {model_name}...")
        try:
            # تعريف أداة البحث بالصيغة الجديدة
            config = types.GenerateContentConfig(
                tools=[{"google_search": {}}]
            )
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config
            )
            cleaned_response = response.text.strip().replace("```json", "").replace("```", "")
            new_articles = json.loads(cleaned_response)
            if isinstance(new_articles, list):
                print(f"   🎉 Success! Generated {len(new_articles)} new articles with {model_name}.")
                return new_articles # نجحنا، نرجع بالنتيجة ونخرج من الدالة
        except Exception as e:
            # إذا فشل، نطبع الخطأ وننتقل للنموذج التالي
            print(f"   ❌ Failed with {model_name}. Reason: {e}")
            time.sleep(2) # انتظار ثانيتين قبل المحاولة التالية
    
    # إذا فشلت كل النماذج في الحلقة
    raise RuntimeError(f"All models failed to generate a plan for category: {category}")


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
