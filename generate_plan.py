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
    'gemma-4-31b-it',
    'gemini-2.5-flash'
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

# متغيرات عالمية لتتبع مسار النماذج والمفاتيح
CURRENT_MODEL_INDEX = 0
CURRENT_KEY_INDEX = 0
CURRENT_KEY = None

def get_smart_client_and_model(repo, force_rotate=False):
    """
    محرك الطاقة لسكريبت الخطط (يتجنب مفتاح الكاتب ويدور على النماذج)
    """
    global CURRENT_KEY_INDEX, CURRENT_MODEL_INDEX, CURRENT_KEY
    
    status_file = "shared_api_status.json"
    excluded_keys = []
    
    try:
        content = repo.get_contents(status_file).decoded_content.decode('utf-8')
        status_data = json.loads(content)
        if "writer" in status_data:
            excluded_keys.append(status_data["writer"])
    except: pass

    if force_rotate:
        print(f"   🔄 Switching API Key for Model: {GEMINI_MODELS[CURRENT_MODEL_INDEX]}")
        CURRENT_KEY_INDEX += 1
        if CURRENT_KEY_INDEX >= len(GEMINI_API_KEYS):
            print(f"   ⚠️ All keys exhausted for {GEMINI_MODELS[CURRENT_MODEL_INDEX]}. Switching to NEXT MODEL!")
            CURRENT_KEY_INDEX = 0
            CURRENT_MODEL_INDEX += 1
            if CURRENT_MODEL_INDEX >= len(GEMINI_MODELS):
                raise Exception("CRITICAL: All Models and All API Keys have been exhausted!")

    while CURRENT_KEY_INDEX in excluded_keys and CURRENT_KEY_INDEX < len(GEMINI_API_KEYS):
        CURRENT_KEY_INDEX += 1
        if CURRENT_KEY_INDEX >= len(GEMINI_API_KEYS):
            CURRENT_KEY_INDEX = 0
            break

    CURRENT_KEY = GEMINI_API_KEYS[CURRENT_KEY_INDEX]
    selected_model = GEMINI_MODELS[CURRENT_MODEL_INDEX]
    
    if force_rotate:
        try:
            new_status = {"planner": CURRENT_KEY_INDEX, "writer": excluded_keys[0] if excluded_keys else -1}
            try:
                file_obj = repo.get_contents(status_file)
                repo.update_file(status_file, "Update planner key", json.dumps(new_status), file_obj.sha)
            except:
                repo.create_file(status_file, "Init API status", json.dumps(new_status))
        except: pass

    client = genai.Client(api_key=CURRENT_KEY)
    return client, selected_model

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
1- استراتيجية منع التكرار (No Keyword Cannibalization): ادمج الكلمات المتشابهة في المعنى والنية في "عنوان مقال واحد شامل". يُمنع منعاً باتاً كتابة أكثر من مقال لنفس نية البحث.
2. اقترح من (10 إلى 20 عنوان مقال) كحد أقصى لتغطية الكلمات. الجودة وعدم التكرار أهم من الوصول للرقم 20.
3- فلترة الكلمات: تجاهل اسم القسم العام، وتجنب تكرار نفس الكلمات المفتاحية لعناوين مختلفة.
4- كل عنوان يجب أن يكون قابل للبحث لزيادة نسبة النقر إلى الظهور (CTR عالي).
5- كل عنوان يجب أن يكون بين 70 إلى 80 حرفًا.
6- قدم النتائج في جدول احترافي يحتوي على الأعمدة التالية:
عنوان المقال
الكلمة المستهدفة
وصف ميتا
هدف المقال للزائر او للقارئ في حدود 30 كلمة
رقم مؤشر التريند

7- لكل عنوان، أنشئ وصفًا ميتا (Meta Description) يحتوي على الكلمة المفتاحية الحقيقية، يكون مهيأ للسيو الجديد ويتراوح طوله بين 100 إلى 150 حرفًا.
8- حدد "نية الباحث" (Search Intent) بدقة شديدة لكل عنوان من ضمن هذه القائمة فقط (اختر نية واحدة أو نيتين كحد أقصى تناسب العنوان):[معلوماتية, ملاحية, استقصائية, شرائية, محلية, معلومة موجزة, وسائط, بحث مجاني, إجرائية, مختلطة, حداثة/تريند, حل مشكلات, ترفيهية, أريد أن أفعل, أريد أن أذهب, موسمية, مقارنة, ضمنية]
9- 🔴 تحذير زمني صارم: نحن نعيش في عام {current_year}. يُمنع منعاً باتاً كتابة سنوات ماضية في العناوين أو الوصف. إذا استدعى العنوان وجود تاريخ، يجب أن يكون {current_year} حصراً، أو اجعل العنوان بدون تاريخ.

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

def generate_plan_for_category(category, excluded_titles, repo):
    if not GEMINI_API_KEYS:
        raise ValueError("No Gemini API keys found.")
    
    # جلب الاقتراحات العميقة (Deep Suggestions)
    real_keywords_list = get_deep_google_suggestions(category)
    prompt = get_content_plan_prompt(category, excluded_titles, real_keywords_list)

    max_retries = 100 # عدد محاولات كافٍ للمرور على كل المفاتيح والنماذج
    force_rot = False
    
    for attempt in range(max_retries):
        client, model_name = get_smart_client_and_model(repo, force_rotate=force_rot)
        force_rot = False # إعادة ضبط للمحاولة القادمة
        
        print(f"      - Attempting with model: {model_name} (Key Index: {CURRENT_KEY_INDEX})...")
        try:
            response = client.models.generate_content(model=model_name, contents=prompt)
            cleaned_response = response.text.strip().replace("```json", "").replace("```", "")
            new_articles = json.loads(cleaned_response)
            
            if isinstance(new_articles, list):
                print(f"      🎉 Success! Generated {len(new_articles)} new articles with {model_name}.")
                return new_articles
                
        except Exception as e:
            error_msg = str(e).lower()
            print(f"      ❌ Failed. Reason: {error_msg[:100]}...")
            if "429" in error_msg or "quota" in error_msg or "500" in error_msg:
                print("      ⚠️ Server issue or quota hit. Rotating key/model...")
                force_rot = True
                time.sleep(5)
            else:
                force_rot = True
                time.sleep(5)

    raise RuntimeError(f"All keys and models failed to generate a plan for category: {category}")

def process_manual_keywords(repo):
    """
    تقرأ الكلمات من ملف manual_keywords.txt
    تولد لكل كلمة خطة وتحدد قسمها، وتضعها في صدارة (أول) ملف الـ JSON الخاص بالقسم.
    """
    manual_file_path = "manual_keywords.txt"
    try:
        manual_content = get_file_content(repo, manual_file_path)
        if not manual_content or not manual_content.strip():
            return # الملف فارغ، لا تفعل شيئاً
            
        keywords =[kw.strip() for kw in manual_content.splitlines() if kw.strip()]
        if not keywords: return
        
        print(f"\n🌟 [VIP] Found {len(keywords)} manual keywords. Processing now...")
        
        # اختيار مفتاح للعمل
        api_key = random.choice(GEMINI_API_KEYS)
        client = genai.Client(api_key=api_key)
        model_name = GEMINI_MODELS[0] # نستخدم أقوى نموذج

        current_year = datetime.now().strftime("%Y") # استخراج السنة الحالية
        
        for keyword in keywords:
            print(f"   -> Processing VIP Keyword: {keyword}")
            prompt = f"""
            بصفتك خبيرًا في تحسين محركات البحث (SEO) وصناعة المحتوى الكتابي المتوافق مع معايير جوجل الجديدة. لدي هذه الكلمة المفتاحية التي أريد الكتابة عنها فوراً: "{keyword}"
            
            الأقسام المتاحة في موقعي هي: {BLOG_CATEGORIES}
            
            المطلوب منك:
            1. 🔴 تحذير زمني صارم: نحن نعيش في عام {current_year}. يُمنع منعاً باتاً كتابة سنوات ماضية في العناوين أو الوصف. إذا استدعى العنوان وجود تاريخ، يجب أن يكون {current_year} حصراً، أو اجعل العنوان بدون تاريخ.
            2. حدد "القسم الأنسب" لهذه الكلمة من الأقسام المذكورة بالأعلى فقط بالحرف.
            3. العنوان يجب أن يكون قابل للبحث لزيادة نسبة النقر إلى الظهور (CTR عالي).
            4. العنوان يجب أن يكون بين 70 إلى 80 حرفًا.
            5. اكتب وصف ميتا تشويقي (100-150 حرف).
            6. اكتب هدف المقال للزائر او للقارئ في حدود 30 كلمة
            7. حدد "نية الباحث" (Search Intent) بدقة شديدة للعنوان من ضمن هذه القائمة فقط (اختر نية واحدة أو نيتين كحد أقصى تناسب العنوان):[معلوماتية, ملاحية, استقصائية, شرائية, محلية, معلومة موجزة, وسائط, بحث مجاني, إجرائية, مختلطة, حداثة/تريند, حل مشكلات, ترفيهية, أريد أن أفعل, أريد أن أذهب, موسمية, مقارنة, ضمنية]
            
            CRITICAL FINAL INSTRUCTION:
            أخرج النتيجة بصيغة JSON Object واحد فقط (وليس Array). استخدم هذه المفاتيح:
            "category", "title", "keyword", "meta_description", "goal", "search_intent"
            
            Do not include any text, explanation, or markdown formatting like ```json before or after the JSON itself.
            """
            
            try:
                response = client.models.generate_content(model=model_name, contents=prompt)
                cleaned_response = response.text.strip().replace("```json", "").replace("```", "")
                vip_article = json.loads(cleaned_response)
                
                # استخراج القسم والتأكد منه
                target_category = vip_article.get("category", "")
                if target_category not in BLOG_CATEGORIES:
                    target_category = BLOG_CATEGORIES[0] # لو اخترع قسم غريب، حطه في أول قسم كأمان
                    
                # إزالة مفتاح category لأنه لا يُحفظ داخل الخطة، الخطة نفسها باسم القسم
                del vip_article["category"]
                
                # جلب ملف الخطة الخاص بهذا القسم
                plan_path = f"{PLANS_DIRECTORY}/content_plan_{target_category}.json"
                existing_articles =[]
                content = get_file_content(repo, plan_path)
                if content:
                    try: existing_articles = json.loads(content)
                    except: existing_articles =[]
                
                # إدراج المقال الـ VIP في "المرتبة الأولى" (رقم 0) لكي يكتبه سكريبت الكتابة فوراً
                existing_articles.insert(0, vip_article)
                
                # تحويل الخطة المحدثة إلى نص JSON
                updated_plan_json = json.dumps(existing_articles, indent=2, ensure_ascii=False)
                
                # رفع وتحديث الملف على جيت هاب
                upload_or_update_github_file(repo, plan_path, updated_plan_json, f"🚀 Add VIP Keyword: {keyword}")
                print(f"   ✅ VIP Keyword '{keyword}' added to '{target_category}' plan at index 0!")
                
                time.sleep(10) # استراحة قصيرة لتجنب ضغط الـ API
                
            except Exception as e:
                print(f"   ⚠️ Failed to process VIP keyword '{keyword}': {e}")
                
        # الخطوة الأخيرة: مسح محتوى ملف manual_keywords.txt لكي لا يتم توليد نفس الكلمات غداً!
        try:
            manual_file = repo.get_contents(manual_file_path)
            repo.update_file(manual_file.path, "🧹 Clear processed VIP keywords", "", manual_file.sha)
            print("   🧹 Cleared manual_keywords.txt successfully.")
        except Exception as e:
            print(f"   ⚠️ Could not clear manual_keywords.txt: {e}")

    except Exception as e:
        print(f"   ⚠️ VIP processing overall error: {e}")

if __name__ == "__main__":
    try:
        print("🚀 Starting content plan check...")
        repo = get_github_repo()
        
        # 🔴 تشغيل نظام الكلمات الـ VIP أولاً
        process_manual_keywords(repo)
        
        published_content = get_file_content(repo, PUBLISHED_TITLES_FILE_PATH)
        published_titles = published_content.splitlines() if published_content else []

        # دورة العمل الروتينية لفحص الأقسام
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
                    new_articles = generate_plan_for_category(category, list(all_excluded), repo)
                    
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
