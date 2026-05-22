import os
import json
import random
import time
import re
import logging
from github import Github, Auth
from google import genai
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.genai import types
from googletrans import Translator
import typing_extensions as typing
from googlesearch import search
from datetime import datetime

# إعداد الـ Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('article_generation.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- وضع الاختبار ---
TEST_MODE = False # اجعله False عندما تعتمد السكريبت نهائياً

GEMINI_MODELS = [
    'gemma-4-31b-it',
    'gemini-2.5-flash'
]

# --- الإعدادات والمفاتيح ---
GEMINI_API_KEYS = [os.environ.get(f"GEMINI_API_KEY_{i}") for i in range(1, 1000) if os.environ.get(f"GEMINI_API_KEY_{i}")]
CURRENT_KEY = None # نخزن فيه المفتاح المختار لهذه الجلسة
CLIENT_ID = os.environ.get("BLOGGER_CLIENT_ID")
CLIENT_SECRET = os.environ.get("BLOGGER_CLIENT_SECRET")
REFRESH_TOKEN = os.environ.get("BLOGGER_REFRESH_TOKEN")
BLOG_ID = os.environ.get("BLOGGER_BLOG_ID")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPO_NAME = "BaDr-BA/B-Aut"
PLANS_DIR = "plans"

# إعدادات الأمان لـ Gemini (لتقليل الحجب)
SAFETY_SETTINGS = [
    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
]

def get_blogger_service():
    creds = Credentials(None, refresh_token=REFRESH_TOKEN, token_uri="https://oauth2.googleapis.com/token", client_id=CLIENT_ID, client_secret=CLIENT_SECRET)
    return build('blogger', 'v3', credentials=creds)

def clean_json_response(text):
    """تنظيف رد Gemini لاستخراج JSON صالح"""
    text = text.replace("```json", "").replace("```", "").strip()
    return text

# متغيرات عالمية لتتبع مسار النماذج والمفاتيح
CURRENT_MODEL_INDEX = 0
CURRENT_KEY_INDEX = 0

def get_smart_client_and_model(force_rotate=False):
    """
    محرك الطاقة الذكي (Shared State & Hierarchical Rotation):
    1. يقرأ ملف shared_api_status.json لتجنب المفتاح الذي يستخدمه السكريبت الآخر.
    2. يطبق قاعدة: (النموذج الأول -> كل المفاتيح) ثم (النموذج الثاني -> كل المفاتيح).
    """
    global CURRENT_KEY_INDEX, CURRENT_MODEL_INDEX, CURRENT_KEY
    
    status_file = "shared_api_status.json"
    excluded_keys = []
    repo = None
    
    # الاتصال السريع بجيت هاب في الخلفية
    try:
        g = Github(auth=Auth.Token(GITHUB_TOKEN))
        repo = g.get_repo(REPO_NAME)
        content = repo.get_contents(status_file).decoded_content.decode('utf-8')
        status_data = json.loads(content)
        if "planner" in status_data:
            excluded_keys.append(status_data["planner"])
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
    
    # تسجيل المفتاح في جيت هاب
    if force_rotate and repo and not TEST_MODE:
        try:
            new_status = {"writer": CURRENT_KEY_INDEX, "planner": excluded_keys[0] if excluded_keys else -1}
            try:
                file_obj = repo.get_contents(status_file)
                repo.update_file(status_file, "Update writer key", json.dumps(new_status), file_obj.sha)
            except:
                repo.create_file(status_file, "Init API status", json.dumps(new_status))
        except: pass

    client = genai.Client(api_key=CURRENT_KEY)
    return client, selected_model

def get_published_posts_for_linking(service):
    """سحب جميع المقالات المنشورة من بلوجر (مهما كان عددها) وتحويلها لروابط نسبية"""
    print("   🌐 Fetching ALL published posts from Blogger for Internal Linking...")
    links_data =[]
    next_page_token = None
    
    try:
        while True:
            # maxResults=500 هو أقصى حد يسمح به بلوجر للطلب الواحد
            request = service.posts().list(blogId=BLOG_ID, status='LIVE', maxResults=500, fetchImages=False, pageToken=next_page_token)
            response = request.execute()
            
            if 'items' in response:
                for post in response['items']:
                    title = post.get('title', '')
                    full_url = post.get('url', '')
                    
                    if title and full_url:
                        # تحويل الرابط الكامل لنسبي
                        relative_url = re.sub(r'^https?://[^/]+', '', full_url)
                        links_data.append({"title": title, "url": relative_url})
                        
            # التحقق مما إذا كان هناك صفحات أخرى من المقالات
            next_page_token = response.get('nextPageToken')
            if not next_page_token:
                break # لا يوجد مقالات أخرى، نخرج من الحلقة
                
        print(f"      ✅ Found {len(links_data)} total posts for linking.")
    except Exception as e:
        print(f"      ⚠️ Failed to fetch posts from Blogger: {e}")
        
    return links_data

def apply_smart_internal_linking(html_content, repo, blogger_service):
    """
    محرك الربط الداخلي الذكي (نسخة الدوران الشامل على كل النماذج والمفاتيح):
    """
    # 1. سحب المقالات
    available_links = get_published_posts_for_linking(blogger_service)
    if not available_links:
        return html_content # لا يوجد مقالات للربط
        
    # تجريد المقال من الـ HTML وأخذ النص كاملاً (بدون قص)
    clean_text = re.sub(r'<[^>]+>', ' ', html_content)
    clean_text = " ".join(clean_text.split())
    
    links_json_str = json.dumps(available_links, ensure_ascii=False)

    prompt = f"""
    بصفتك خبيراً في كتابة المحتوى المتوافق مع معايير السيو الجديد (SEO) وتجربة المستخدم (UX).
    
    هذا هو نص مقالي الجديد (بالكامل):
    "{clean_text}"
    
    وهذه قائمة مقالاتي القديمة (العنوان والرابط النسبي):
    {links_json_str}
    
    المطلوب منك عمل "ربط داخلي بشري" (Internal Linking) احترافي.
    
    القواعد الصارمة:
    1. الروابط السياقية فقط: لا تضف كلمات لمجرد الحشو. استخرج جملة أو كلمة (موجودة فعلاً في نص مقالي الجديد) بشرط أن تكون مرتبطة تماماً بموضوع أحد مقالاتي القديمة
    2. الانسيابية: أريد أن يشعر القارئ أن الرابط جزء لا يتجزأ من المعلومة، وليس مقحماً عليها
    3. استخرج من (2 إلى 15) رابط كحد أقصى حسب طول المقال، وقم بتوزيعها على طول المقال (لا تركزها في فقرة واحدة)
	4. لا تركز الروابط في فقرة واحدة بل اجعلها علي المقال بالكامل ليكون ربط إنسان بشري احترافي
    5. لا تعد كتابة المقال
    
    أخرج النتيجة بصيغة JSON Array فقط، تحتوي على الكلمة الموجودة في النص، والرابط المخصص لها:
    [
      {{"exact_word": "الكلمة أو الجملة الموجودة بالنص", "url": "/2026/05/example.html"}}
    ]
    رد بـ JSON فقط بدون مقدمات أو أي نصوص إضافية.
    """

    links_to_inject =[]
    success = False

    # الدوران الشامل: حلقة للموديلات، وبداخلها حلقة للمفاتيح
    for model_name in GEMINI_MODELS:
        if success: break # لو نجحنا نخرج من حلقة الموديلات
        print(f"\n   ⚙️ Trying Model: {model_name} for Internal Linking...")
        
        for api_key in GEMINI_API_KEYS:
            print(f"      🔄 Testing API Key starting with: {api_key[:8]}...")
            try:
                client = genai.Client(api_key=api_key)
                response = client.models.generate_content(model=model_name, contents=prompt)
                
                links_to_inject = json.loads(clean_json_response(response.text))
                print(f"      ✅ Success! {model_name} with this key suggested {len(links_to_inject)} links.")
                
                # تحديث المفتاح الحالي في السكريبت لكي يُسجل في التاريخ
                global CURRENT_KEY
                CURRENT_KEY = api_key
                
                success = True
                break # نجحنا! نخرج من حلقة المفاتيح
                
            except Exception as e:
                error_msg = str(e).lower()
                if "429" in error_msg or "quota" in error_msg:
                    print(f"      ⚠️ Quota hit on this key. Moving to the next key...")
                else:
                    print(f"      ⚠️ Error: {error_msg[:100]}. Moving to the next key...")
                time.sleep(3) # استراحة قصيرة قبل تجربة المفتاح التالي

    # زراعة الروابط إذا نجحنا
    if success and links_to_inject:
        parts = re.split(r'(<[^>]+>)', html_content)
        
        for link_obj in links_to_inject:
            exact_word = link_obj.get("exact_word", "").strip()
            url = link_obj.get("url", "").strip()
            
            if not exact_word or not url or len(exact_word) < 4: continue
            
            in_heading = False
            in_link = False
            word_injected = False
            
            for i, part in enumerate(parts):
                if word_injected: break
                
                if part.startswith('<h') and not part.startswith('</'): in_heading = True
                elif part.startswith('</h'): in_heading = False
                elif part.startswith('<a'): in_link = True
                elif part.startswith('</a'): in_link = False
                
                if not part.startswith('<') and not in_heading and not in_link:
                    if exact_word in part:
                        replacement = f'<a href="{url}">{exact_word}</a>'
                        parts[i] = part.replace(exact_word, replacement, 1)
                        word_injected = True
                        print(f"      🔗 Injected link on: '{exact_word}'")
                        
        return ''.join(parts)
    else:
        print("   ❌ All models and all keys failed to generate internal links. Proceeding without them.")
        return html_content # نرجع المقال بدون روابط لو فشلت كل المحاولات

def search_google_info(query):
    """البحث في جوجل بالمحتوى الأجنبي الحديث وتلقائياً بالتاريخ الحالي"""
    try:
        # 1. نحسب التاريخ الحالي (الشهر والسنة)
        current_date = datetime.now().strftime("%B %Y") # مثلاً: February 2026
        
        # 2. نضيف كلمات إنجليزية لفرض البحث في المصادر الأجنبية
        # ونضيف التاريخ الحالي لضمان الحداثة
        advanced_query = f"{query} latest news guide {current_date} english"
        
        print(f"   🌐 Googling (Smart): {advanced_query}...")
        
        # 3. نجلب النتائج (lang='en' يفضل النتائج الإنجليزية)
        results = search(advanced_query, num_results=3, advanced=True, sleep_interval=5, lang='en')
        
        context = ""
        for r in results:
            # نترجم العنوان والوصف للعربية عشان Gemini يفهمه ويصيغه في المقال العربي
            # (ملاحظة: Gemini بيفهم إنجليزي كويس جداً، فممكن نبعتله الإنجليزي وهو يترجم ويصيغ)
            context += f"- Source (English): {r.title}\n  Info: {r.description}\n"
            
        if context:
            return context
    except Exception as e:
        print(f"   ⚠️ Google Search failed: {e}")
    return ""
	
def create_permalink_gemini(keyword_arabic):
    """توليد رابط ثابت بالإنجليزية حصراً"""
    try:
        client, selected_model = get_smart_client_and_model()
        # برومبت صارم للترجمة
        prompt = f"""
        Task: Create a professional, short, and SEO-friendly English slug for the Arabic keyword: "{keyword_arabic}".
        
        Rules:
        1. Do NOT translate literally. Understand the meaning and give the best English SEO keyword.
        2. Use max 3-5 words.
        3. Convert to lowercase.
        4. Remove stop words (like 'the', 'of', 'in', 'how-to' if unnecessary).
        5. Replace spaces with hyphens (-).
        6. Remove all special characters.
        7. Output ONLY the slug (e.g. digital-marketing-tips).
        """
        response = client.models.generate_content(model=selected_model, contents=prompt)
        permalink = response.text.strip().lower()
        
        # تنظيف نهائي لأي حروف غير إنجليزية
        permalink = re.sub(r'[^a-z0-9\-]', '', permalink)
        return permalink
    except Exception as e:
        print(f"⚠️ Permalink Error: {e}")
        # خطة بديلة في حال فشل Gemini نستخدم مكتبة re فقط لعمل slug عربي
        return re.sub(r'[^0-9\u0600-\u06FF]+', '-', keyword_arabic).strip('-')

def clean_text_symbols(text):
    """
    إزالة علامات الاقتباس، النجوم المزدوجة، كود القالب المزعج،
    والتعامل الذكي مع علامات التعجب (!) للحفاظ على السيو.
    """
    # 1. إزالة الروابط <a> مع الاحتفاظ بالنص (نضعها في البداية لتنظيف النص الخام)
    text = re.sub(r'<a\s+[^>]*>(.*?)</a>', r'\1', text, flags=re.IGNORECASE)
	
    # 2. تنظيف كود القالب المزعج (keyword_strong) واستبداله بـ bold عادي
    text = re.sub(r'<strong[^>]*id=["\']keyword_strong["\'][^>]*>', '<b>', text)
    
    # 3. إزالة ** المزدوجة
    text = text.replace('**', '')
    
    # 4. إزالة " من النص لكن ليس من HTML attributes
    html_pattern = r'(<[^>]+>)'
    parts = re.split(html_pattern, text)
    cleaned_parts = []
	
    for part in parts:
        if part.startswith('<') and part.endswith('>'):
            cleaned_parts.append(part)
        else:
            # إزالة علامات الاقتباس
            cleaned_part = part.replace('"', '')
            cleaned_parts.append(cleaned_part)
            
    return ''.join(cleaned_parts)

def get_competitors_structure(keyword):
    """
    سحب هياكل أفضل المنافسين من جوجل باستخدام Jina AI.
    تسحب العناوين فقط (H1, H2, H3, H4) لتوفير الكوتا وتركيز التحليل.
    تخطي السوشيال ميديا وحظر Jina AI
    """
    print(f"   🕵️‍♂️ Analyzing top competitors for: {keyword} via Jina AI...")
    competitor_headers = ""
    successful_scrapes = 0
    
    # القائمة السوداء للمواقع التي لا نريد تحليلها (ليست مقالات)
    blacklist =['youtube.com', 'facebook.com', 'x.com', 'instagram.com', 'tiktok.com', 'pinterest.com', 'linkedin.com', 'amazon.', 'reddit.com', 'quora.com', 'apple.com']
    
    try:
        # نجلب 15 نتيجة لكي يكون لدينا احتياطي لو تم حظر بعضها
        urls = list(search(keyword, num_results=15, sleep_interval=2, lang='ar'))
        
        for url in urls:
            if successful_scrapes >= 5: # نكتفي بـ 5 هياكل ناجحة
                break
                
            # تخطي المواقع المحظورة
            if any(domain in url for domain in blacklist):
                continue
                
            print(f"      - Scraping: {url[:60]}...")
            jina_url = f"https://r.jina.ai/{url}"
            req = urllib.request.Request(jina_url, headers={'User-Agent': 'Mozilla/5.0'})
            
            try:
                # نضع مهلة 15 ثانية لكي لا يتعطل السكريبت لو كان موقع المنافس بطيئاً
                response = urllib.request.urlopen(req, timeout=15)
                markdown_content = response.read().decode('utf-8')
                
                # تخطي الأخطاء التي تعيدها Jina AI على هيئة JSON
                if "SecurityCompromiseError" in markdown_content or "Too many requests" in markdown_content:
                    print("      ⚠️ Jina AI blocked this site (DDoS protected). Skipping...")
                    continue
                    
                headers_only =[]
                for line in markdown_content.splitlines():
                    line = line.strip()
                    # نبحث عن العناوين من H1 إلى H4 فقط
                    if line.startswith('#') and 0 < line.count('#') <= 4:
                        # تنظيف شكل العنوان ليكون مقروءاً للذكاء الاصطناعي
                        clean_header = line.replace('#', '').strip()
                        headers_only.append(f"- {clean_header}")
                
                # إذا وجدنا عناوين في هذا الموقع، نضيفها للنتيجة ونزيد العداد
                if headers_only:
                    successful_scrapes += 1
                    competitor_headers += f"\n--- هيكل المنافس رقم {successful_scrapes} ---\n"
                    competitor_headers += "\n".join(headers_only) + "\n"
                    print(f"      ✅ Success! Found {len(headers_only)} headers.")
            
            except Exception as e:
                # إذا حدث أي خطأ (مثل 403 أو Timeout) نتجاهله بهدوء
                print(f"      ⚠️ Failed to scrape (Ignored): {str(e)[:50]}")
            
            time.sleep(5) # استراحة بسيطة لتجنب حظر الـ IP الخاص بك
            
    except Exception as e:
        print(f"   ⚠️ Competitor search failed: {e}")
        
    return competitor_headers

def format_headings_style(html_content):
    """
    تحويل النقطتين : إلى مسافة وعمود ¦ في العناوين H1-H4 فقط
    """
    def replace_colon(match):
        tag_open = match.group(1)
        content = match.group(2)
        tag_close = match.group(3)
        # استبدال : بـ ¦ داخل النص
        new_content = content.replace(':', ' ¦')
        return f"{tag_open}{new_content}{tag_close}"

    # Regex يستهدف h1, h2, h3, h4 ومحتواهم
    pattern = r'(<h[1-4][^>]*>)(.*?)(</h[1-4]>)'
    return re.sub(pattern, replace_colon, html_content, flags=re.DOTALL | re.IGNORECASE)

def generate_article_structure(title, keyword, search_intent="معلوماتية"):
    """توليد هيكل المقال بناءً على تحليل المنافسين الحقيقي (Skyscraper Technique)"""
    
    # 1. سحب هياكل المنافسين الحقيقية
    competitors_data = get_competitors_structure(keyword)
    
    # إذا لم نجد منافسين (لأي خطأ فني)، نضع رسالة بديلة
    if not competitors_data:
        competitors_data = "لم يتم العثور على هياكل للمنافسين. اعتمد على خبرتك الشاملة لإنشاء الهيكل الأفضل."

    prompt = f"""
    أنت خبير SEO محترف ومحلل محتوى بمستوى عالمي.
    مهمتك: كتابة مقال بعنوان "{title}" للكلمة المفتاحية "{keyword}".
    الهدف الأسمى: "تقنية ناطحة السحاب (Skyscraper Technique)".
    نية الباحث (Search Intent) لهذا المقال هي: "{search_intent}".
    بناءً على هذه النية، يجب أن تعكس العناوين ما يبحث عنه الزائر (مثلاً لو النية مقارنة، ضع جداول.. لو معلومة موجزة، ضع الإجابة بالخلاصة في البداية.. وهكذا).
    لقد قمت أنا بسحب العناوين الرئيسية والفرعية (H1, H2, H3, H4) لأفضل 5 مقالات تتصدر نتائج جوجل الآن.
    
    إليك هياكل المنافسين المتصدرين:
    {competitors_data}
    
    المطلوب:
    1. ادرس هياكل المنافسين بالأعلى بعناية.
    2. استنتج "الفجوات" (ما الذي نسوا التحدث عنه؟ ما الزوايا التي تناولوها بسطحية؟).
    3. صمم "هيكل مقال مثالي وأسطوري" يتفوق عليهم جميعاً. يجب أن يكون مقالك هو المرجع الأشمل في هذا الموضوع بحيث لا يحتاج الزائر لقراءة أي مقال آخر.
    4. قدم ترتيبًا منطقيًا للعناوين الرئيسية والفرعية (H2, H3) يضمن تغطية شاملة ومتسلسلة لجميع الجوانب التي ذكرها المنافسون + الجوانب الجديدة التي استنتجتها أنت. لمقال متوافق مع معايير SEO الجديدة والهدف ونية الباحث لتصدر نتائج البحث.
    
    ⚠️ مهم جداً: تجنب تكرار نفس العنوان مرتين كل عنوان يجب أن يكون فريداً ومختلفاً.

    قواعد الهيكل:
    1. يجب أن يغطي نقاط الضعف عند المنافسين.
    2. تسلسل منطقي.
    3. العناوين يجب أن تكون حصرية وجديدة وليست تقليدية.
    4. تجنب تكرار العناوين.
    5. ⛔ ممنوع تماماً استخدام المبالغة الدرامية أو الكلمات الروائية (مثل: فك شفرة، الغوص، رحلة سحرية، هل أنت مستعد، عالم ساحر). كن عملياً وعلمياً.
	6. استخدم علامات الترقيم الصحيحة إذا لزم الأمر مثل النقطتين الرأسيتين (:)، وعلامات الاستفهام (؟).
	
    بجانب كل عنوان، حدد:
    - level: إما "h2" أو "h3" أو "h4" أو "intro" (للمقدمة فقط في البداية)
    - type: نوع المحتوى من هذه القائمة حصراً: [introduction, list_bullet, list_numbered, table, faq, conclusion, text_paragraph, code_prompt_script_box, featured_paragraph, pros_cons, emoji_check_list]
    - title: نص العنوان (يجب أن يكون فريداً)

    يجب أن يكون الرد بصيغة JSON Array فقط، مثل هذا الشكل (مثال):
    [
        {{"level": "intro", "type": "introduction", "title": "مقدمة شاملة"}},
        {{"level": "h2", "type": "text_paragraph", "title": "عنوان رئيسي جذاب 1"}},
        {{"level": "h3", "type": "list_bullet", "title": "قائمة فرعية 1"}},
        {{"level": "h2", "type": "table", "title": "مقارنة شاملة"}},
        {{"level": "h2", "type": "faq", "title": "الأسئلة الشائعة حول {keyword}"}},
        ...
        {{"level": "h2", "type": "conclusion", "title": "خاتمة شاملة"}}
    ]

    ⚠️ رد بـ JSON فقط.
	
    ملاحظات:
    - استخدم "intro" مرة واحدة فقط للمقدمة
    - استخدم "h2" للعناوين الرئيسية
    - استخدم "h3" للعناوين الفرعية
    - لا تكرر نفس العنوان
	- أريد تحليلًا عمليًا مبنيًا على الفجوات ونقاط الضعف لدى المنافسين، وليس مجرد ملخص لمحتواهم. الهدف تصدر نتائج البحث بالمقال الجديد التى يغطى كل الجوانب ونقاط الضعف عند المنافسين
    """

    # محاولة التوليد 3 مرات في حالة الحظر
    max_retries = 3
    for attempt in range(max_retries):
        try:
            client, selected_model = get_smart_client_and_model()
            config = types.GenerateContentConfig(safety_settings=SAFETY_SETTINGS)
            response = client.models.generate_content(model=selected_model, contents=prompt, config=config)
            
            clean_text = clean_json_response(response.text)
            structure = json.loads(clean_text)
            
            # التحقق من التكرار
            titles_seen = set()
            unique_structure = []
            for item in structure:
                if item['title'] not in titles_seen:
                    titles_seen.add(item['title'])
                    unique_structure.append(item)
            
            if len(unique_structure) > 3: # تأكد أن الهيكل محترم مش قصير
                return unique_structure
                
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower():
                wait_time = 20 * (attempt + 1)
                print(f"⚠️ Structure Quota hit! Waiting {wait_time}s... ({attempt+1}/{max_retries})")
                time.sleep(wait_time)
            else:
                print(f"⚠️ Structure Error: {e}")
                # --- التبديل الذكي للمفتاح عند فشل الهيكل ---
                global CURRENT_KEY
                other_keys = [k for k in GEMINI_API_KEYS if k != CURRENT_KEY]
                if other_keys:
                    CURRENT_KEY = random.choice(other_keys)
                    print("🔄 Switched to a new API Key for structure retry.")
                # ---------------------------------------------------
                time.sleep(10)

    # إذا فشلت كل المحاولات، نرفع خطأ ليتم إيقاف العملية والحفاظ على الخطة
    raise Exception("❌ Failed to generate article structure after retries. Aborting to save plan.")

def get_synonyms(keyword):
    """
    توليد مرادفات للكلمة المفتاحية تلقائياً باستخدام Gemini
    """
    try:
        client, selected_model = get_smart_client_and_model()
        prompt = f"""
        أنت خبير SEO الجديد متخصص في البحث عن الكلمات المفتاحية.
        
        المطلوب: أعطني 25 كلمة مرادفة (LSI Keywords) قوية جداً وذات صلة مباشرة بالكلمة الأساسية: "{keyword}"
        
        الشروط:
        1. الكلمات يجب أن تكون ذات صلة مباشرة ومنطقية بالكلمة الأساسية
        2. الكلمات يجب أن تكون من Google Keyword Planner, Ubersuggest, SEMrush, Ahrefs, Keywordtool.io, AnswerThePublic, Google Trends, وغيرهم
        3. تنوّع بين المرادفات بالعربية والإنجليزية (إذا وُجد)
        4. أضف مصطلحات شائعة يستخدمها الباحثون في جوجل (إذا وُجد)
        5. ركّز على الكلمات القصيرة (Short-tail keywords) والكلمات الطويلة (Long-tail keywords) المفيدة للـ SEO الجديد
        6. تجنب الكلمات العامة جداً أو البعيدة عن الموضوع
        
        أعطني النتيجة كقائمة JSON بسيطة فقط، مثال:
        ["مرادف 1", "مرادف 2", "مصطلح مشابه 3", "keyword 4"]
        
        ⚠️ مهم جداً: 
        - لا تضف أي نص أو شرح قبل أو بعد JSON
        - JSON فقط بدون أي كلام
        - لا تستخدم markdown أو ```
        """
        response = client.models.generate_content(model=selected_model, contents=prompt)
        synonyms_text = clean_json_response(response.text)
        
        # محاولة تحويل النص لـ JSON
        synonyms = json.loads(synonyms_text)
        
        # التأكد أنها قائمة وليست dictionary
        if isinstance(synonyms, dict):
            synonyms = list(synonyms.values())
        
        # تنظيف وإضافة الكلمة الأساسية
        synonyms = [s.strip() for s in synonyms if s.strip()]
        if keyword not in synonyms:
            synonyms.insert(0, keyword)
        
        # إزالة التكرار والحد الأقصى 25 كلمة
        synonyms = list(dict.fromkeys(synonyms))[:25]
        
        print(f"   📝 Generated {len(synonyms)} synonyms for '{keyword}'")
        return synonyms
        
    except Exception as e:
        print(f"   ⚠️ Could not generate synonyms: {e}")
        # في حالة الفشل، نرجع الكلمة الأساسية فقط
        return [keyword]

def make_keywords_bold(text, keyword, synonyms_list, global_tracker=None):
    """
    تغميق ذكي:
    - الكلمة الأساسية: مرة واحدة في المقال كله.
    - المرادفات: مرة واحدة لكل مرادف في المقال كله.
    - الحد الأقصى في الفقرة الحالية: كلمة واحدة فقط (سواء أساسية أو مرادف).
    """
    if synonyms_list is None: synonyms_list = []
    if global_tracker is None: global_tracker = set()
    
    # 1. تنظيف النص من أي بولد قديم (لأمان)
    text = re.sub(r'</?(b|strong)>', '', text, flags=re.IGNORECASE)

    # 2. تجهيز القائمة (الأطول أولاً)
    all_terms = [keyword] + synonyms_list
    all_terms = sorted(list(set([t.strip() for t in all_terms if t.strip()])), key=len, reverse=True)
    
    # 3. تقسيم النص لفقرات (على أساس <br> أو <p> أو <div>)
    # لكن هنا النص يأتي كـ "قطعة" واحدة من Gemini، غالباً فقرة أو فقرتين.
    # سنتعامل مع النص المرسل ككتلة واحدة (Block) ونسمح فيه بـ "بولد واحد فقط".
    
    term_bolded_in_this_block = False # هل قمنا بعمل بولد في هذه القطعة؟

    for term in all_terms:
        if term_bolded_in_this_block: break # خلاص عملنا واحد في الفقرة دي، كفاية.
        if term in global_tracker: continue # الكلمة دي اتعملت قبل كده في المقال، فكك منها.
        if len(term) < 2: continue

        # بحث ذكي (Word Boundary)
        pattern = r'(?<![\w\u0600-\u06FF])' + re.escape(term) + r'(?![\w\u0600-\u06FF])'
        
        if re.search(pattern, text, flags=re.IGNORECASE):
            # استبدال أول ظهور فقط
            text = re.sub(pattern, f'<b>{term}</b>', text, count=1, flags=re.IGNORECASE)
            global_tracker.add(term) # سجل إننا استخدمنا الكلمة دي خلاص
            term_bolded_in_this_block = True # سجل إن الفقرة دي خدت نصيبها
            
    return text

def get_content_prompt(section_type, section_title, keyword, synonyms_list=None, search_intent="معلوماتية", article_goal="", next_title="", all_headings=""):
    """اختيار البرومبت المناسب مع مرادفات عشوائية"""
    
    # نرسل كل المرادفات المتاحة (أول 35 مثلاً لتجنب الطول الزائد في البرومبت)
    # ليختار الذكاء الاصطناعي الأنسب منها للسياق
    current_synonyms = synonyms_list[:35] if synonyms_list else []
    
    # تحويل القائمة لنص
    syns_str = ', '.join(current_synonyms) if current_synonyms else keyword

    # --- الذكاء الاصطناعي الشامل لنية الباحث (Master Persona AI) ---
    intent_rules =[]
    
    # 1. النوايا الأساسية (الأعمدة الأربعة)
    if "معلوماتية" in search_intent:
      intent_rules.append("القارئ يريد التعلم. اشرح المصطلحات المعقدة ببساطة، تعمق في التفاصيل، واستخدم أمثلة توضيحية لتثقيفه.")
    if "ملاحية" in search_intent:
      intent_rules.append("القارئ يبحث عن وجهة محددة. كن مباشراً جداً، وجهه للمعلومة أو الرابط أو اسم المنصة الرسمية التي يبحث عنها بدون مقدمات.")
    if "استقصائية" in search_intent or "مقارنة" in search_intent:
      intent_rules.append("القارئ يقارن قبل الفعل. كن محايداً، ركز على الفروقات الجوهرية (المميزات/العيوب/السعر)، وسهل عليه اتخاذ القرار.")
    if "شرائية" in search_intent:
      intent_rules.append("القارئ جاهز للدفع. ركز على القيمة، الفوائد السريعة، الأمان، وشجعه بأسلوب واثق ومقنع لاتخاذ قرار الشراء/الاشتراك.")
        
    # 2. النوايا التفصيلية
    if "محلية" in search_intent:
      intent_rules.append("اربط المعلومات بالسياق المحلي الجغرافي، ركز على الأماكن أو الخدمات القريبة والمتاحة فعلياً.")
    if "معلومة موجزة" in search_intent:
      intent_rules.append("القارئ في عجلة من أمره. أعطه 'الخلاصة' والجواب النهائي الثابت (رقم، اسم، تاريخ) في أول جملة بدون أي حشو.")
    if "وسائط" in search_intent:
      intent_rules.append("القارئ يريد صوراً أو فيديوهات. صف له ما يجب أن يراه بصرياً، أو وجهه لكيفية الحصول على المحتوى المرئي بسهولة.")
    if "مجاني" in search_intent:
      intent_rules.append("القارئ لا يريد الدفع. ركز كلياً على الأدوات المجانية 100%، البدائل المفتوحة المصدر، وكيفية التوفير وتخطي القيود المدفوعة.")
        
    # 3. النوايا السلوكية والمتقدمة
    if "إجرائية" in search_intent or "أفعل" in search_intent:
      intent_rules.append("القارئ يريد التنفيذ الآن. اكتب بأسلوب (1، 2، 3)، استخدم أفعال أمر (اضغط، حمل، ادخل)، وقدم خطوات فورية.")
    if "مختلطة" in search_intent:
      intent_rules.append("الكلمة لها عدة معاني. قم بتغطية جميع الزوايا المحتملة للكلمة لإرضاء جميع أنواع القراء المحتملين.")
    if "حداثة" in search_intent or "تريند" in search_intent:
      intent_rules.append("القارئ يبحث عن التريند. اكتب بأسلوب صحفي سريع، ركز على التحديثات اللحظية، وما الذي تغير (اليوم/هذا العام).")
    if "مشكلات" in search_intent or "حل" in search_intent:
      intent_rules.append("القارئ غاضب ولديه عطل. تقمص دور المهندس المنقذ، اشرح سبب المشكلة باختصار، ثم اطرح الحلول الفعالة مباشرة.")
    if "ترفيهية" in search_intent:
      intent_rules.append("القارئ يريد التسلية. استخدم أسلوباً مرحاً، طريفاً، خفيف الظل، واجعل المحتوى ممتعاً ومسلياً للقراءة.")
        
    # 4. لحظات جوجل الاستراتيجية
    if "أذهب" in search_intent:
      intent_rules.append("القارئ يخطط لزيارة. ركز على العناوين، النصائح المكانية، تقييمات الزوار، والتفاصيل العملية للزيارة.")
    if "موسمية" in search_intent:
      intent_rules.append("القارئ يبحث عن مناسبة (كرمضان أو البلاك فرايداي). استخدم نبرة حماسية ترتبط بالحدث، وركز على العروض واستغلال الوقت.")
    if "ضمنية" in search_intent:
      intent_rules.append("اقرأ ما بين السطور لما يبحث عنه القارئ وقدم إجابات تلبي احتياجه الخفي الذي لم يصرح به مباشرة.")

    # دمج كل النوايا التي وجدها في شخصية واحدة
    intent_rule = "\n    ".join(intent_rules)
		
    # لو حصل أي خلل ولم يتم التقاط أي نية (تأمين إضافي)
    if not intent_rule:
        intent_rule = "قدم دليلاً شاملاً، غنياً بالمعلومات القيمة التي تجعل من مقالك المرجع الأول والنهائي للزائر."

    # تجهيز جملة التسليم للفقرة القادمة
    bridge_instruction = ""
    if next_title and section_type not in ['conclusion', 'faq', 'summary_box', 'motivation_box']:
        bridge_instruction = f"9. 🔗 انسيابية القراءة: اختم فقرتك بجملة تمهيدية سلسة جداً (جسر انتقال ذكي) (لا تكتب العنوان كما هو أبداً) بل تسلم ذهن القارئ بسلاسة للقسم القادم الذي سيكون بعنوان: '{next_title}'."

    # حقن النية والهدف والتعليمات الصارمة
    strict_instructions = f"""
    ⛔ تعليمات صارمة جداً:
    1. ممنوع كتابة أي مقدمات أو مقدمة ترحيبية (مثل: بالتأكيد، إليك الفقرة ..إلخ).
    2. ممنوع كتابة العناوين مرة أخرى.
    3. التزم بعدد الأسطر المحدد بدقة.
    4. ابدأ مباشرة بالمحتوى المطلوب.
    5. لا تستخدم "المقدمة:" أو "الخاتمة:" أو أي عناوين.
    6. اكتب بأسلوب بشري طبيعي، حديث، ومباشر 100% وموجه لنية الباحث وهدفه 100%. ⛔ يُمنع تماماً استخدام أي كلمات الكلاسيكية معقدة سواء في بداية الجمل (مثل: إنّ، لقد، حيث أن، مما لا شك فيه، أو أي كلمة أخرى) أو في وسط أو أخر الجمل . ادخل في صلب الموضوع فوراً وكأنك خبير يتحدث بثقة.
    7. ممنوع الحشو ولا التكرار.
	8. ⛔ قاعدة نحوية صارمة: إذا كانت الكلمة المفتاحية تبدو كجملة بحث ركيكة (مثل: "أمن المعلومات شرح")، يُمنع منعاً باتاً حشرها كما هي. قم بصياغتها نحوياً بشكل صحيح ومندمج في السياق (مثل: "شرح أمن المعلومات"). الأولوية المطلقة لسلامة اللغة العربية.
    {bridge_instruction}
	10. 🚀 الهدف الاستراتيجي للمقال (يجب تحقيقه في سياق كلامك): {article_goal}
    11. 🎯 أسرار احترافية لكتابة هذه الفقرة (هذه نية الباحث): {intent_rule}
	12. 🛑 تحذير خطير جداً: يُمنع منعاً باتاً كتابة أسماء النوايا (مثل كلمة: معلوماتية، إجرائية، استقصائية، النية) كعناوين أو داخل النص. طبق الأسلوب المطلوب فقط دون أن تذكر اسمه أبداً
    """

    prompts = {
        "introduction": f"""
        {strict_instructions}
        
        المطلوب: اكتب مقدمة مشوقة جداً (Hook) تخاطب القارئ مباشرة بعنوان "{section_title}" وتشد القارئ لنهاية المقال ومتوافقة مع معايير السيو:

        معلومة حصرية: المقال الذي نكتبه الآن سيناقش لاحقاً هذه العناوين:
        {all_headings}
        
        بناءً على اطلاعك على العناوين السابقة، قم بصياغة المقدمة بحيث تشوق القارئ لما سيجده في المقال (لا تسرد العناوين كفهرس ممل، ولا تكتبها كما هي أبداً).
		
        تكون المقدمة فقرتين:
        - الفقرة الأولى: ثلاث أسطر بحد أقصى
        - الفقرة الثانية: ثلاث أسطر بحد أقصى
		- المدى المسموح: فقرتين فقط ومن 2 إلى 3 أسطر (لا تزيد عن ذلك).

        المحتوى: ابدأ بمشكلة (يشد اللي متألم فعلًا) أو بحقيقة صادمة (تخض وتخلّي القارئ يكمل) أو بسؤال مباشر (يشغّل دماغه) أو بجملة قصيرة تقيلة (أسلوب صاعق) أو بمشهد أو قصة (يشد عاطفيًا) أو بكسر معتقد شائع أو... أي هدف حسب ما في رأيك ثم قدم الحل الذي في الموضوع.

        استخدم الكلمة المفتاحية الأساسية "{keyword}" وهذه المرادفات بشكل طبيعي ومتنوع: {syns_str}
		⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
		
        """,
        
        "list_bullet": f"""
        {strict_instructions}
        
        المطلوب: قائمة تنقيطية كاملة وشاملة عن "{section_title}" وتشد القارئ لنهاية المقال ومتوافقة مع معايير السيو:
        - تبدأ بمقدمة قصيرة تمهد للنقاط (200 حرف)
        - ثم النقاط التنقيطية كاملة وشاملة
        - اختم بملاحظة قصيرة (200 حرف)
        
        استخدم الكلمة المفتاحية الأساسية "{keyword}" وهذه المرادفات بشكل طبيعي ومتنوع: {syns_str}
		⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        
        """,
        
        "list_numbered": f"""
        {strict_instructions}
        
        المطلوب: قائمة مرقمة كاملة وشاملة عن "{section_title}" وتشد القارئ لنهاية المقال ومتوافقة مع معايير السيو:
        - تبدأ بمقدمة قصيرة تمهد للترقيم (200 حرف)
        - القائمة المرقمة كاملة وشاملة
        - اختم بملاحظة قصيرة (200 حرف)
        
        استخدم الكلمة المفتاحية الأساسية "{keyword}" وهذه المرادفات بشكل طبيعي ومتنوع: {syns_str}
		⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        
        """,
        
        "table": f"""
        {strict_instructions}
        
        انشئ جدول HTML (ياخذ تدرج الوان #bb3b17 و#faad2a أو ما بينهم + وخط القالب بلوجر اللي مركبه تلقائيًا) عن "{section_title}" وتشد القارئ لنهاية المقال ومتوافقة مع معايير السيو:
        - تبدأ بمقدمة قصيرة تمهد للجدول ومحتواه (200 حرف)
        - ثم الجدول كامل وشامل (يكون متجاوب مع الهواتف والكمبيوتر واستخدم overflow-x: auto;)
        - بدون CSS معقد
		- مهم جدًا استخدم text-align: center في جميع الجدول
		- مهم جدًا يجب أن يكون الجدول يأخذ خط قالب بلوجر تلقائيًا
        - استخدم الكلمة المفتاحية "{keyword}" وهذه المرادفات بشكل طبيعي: {syns_str}
        - ⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        
        ابدأ كتابة الجدول فوراً بدون أي مقدمات وبدون كتابة العنوان مرة أخرى.
        """,
        
        "faq": f"""
        {strict_instructions}

		أكتب أسئلة شائعة وأجوبة عن "{section_title}" وتشد القارئ للقراءة لنهاية الأسئلة والأجوبة ومتوافقة مع معايير السيو:
        لديك قائمة بأسئلة حقيقية يبحث عنها الناس في جوجل الأسئلة من اقتراحات جوجل التلقائية (تم البحث أيضًا عن). وقسم "الناس أيضًا يسألون" (People Also Ask). وقسم أسئلة أخرى.
        المطلوب:
        - ابدأ بمقدمة قصيرة تمهد للأسئلة والأجوبة (200 حرف)
        - كل إجابة لا تزيد عن سطرين
		- كل اجابة تبرز قيمة مضافة لا يعرفها الجميع
        - استخدم إيموجي مناسب في بداية كل جواب فقط

        ⛔ تحذير هام:
        - لا تكتب العنوان الرئيسي "{section_title}" مرة أخرى.
        - ابدأ فوراً بالسؤال الأول.
        الشروط:
        1. اجعل كل سؤال في وسم <h3>.
        2. اجعل الإجابة تحته مباشرة في وسم <p>.
        3. لا تستخدم قوائم أو ترقيم، فقط h3 ثم p.
		
        التنسيق المطلوب المرئي للزائر:
        <h3>السؤال الأول هنا</h3>
        <p>الإجابة المختصرة هنا.</p>
        
        <h3>السؤال الثاني هنا</h3>
        <p>الإجابة المختصرة هنا.</p>
        ...
		
        استخدم الكلمة المفتاحية الأساسية "{keyword}" وهذه المرادفات بشكل طبيعي ومتنوع: {syns_str}
		⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        
        """,
        
        "featured_paragraph": f"""
        {strict_instructions}
        
        اكتب فقرة مميزة عن "{section_title}" وتشد القارئ لنهاية المقال ومتوافقة مع معايير السيو:
        - بعنوان "تجربتنا" أو "خبرتنا"
        - أسلوب شخصي دافئ (First-person perspective) سواء 'نصيحة من القلب' أو 'سر المهنة' أو 'رؤية تحليلية' أو 'تطبيق عملي' أو 'واقع السوق' أو 'تنبيه للمحترفين'  أو أي حاجة حسب الموضوع وكأنك تشارك القارئ تجربة شخصية حصرية
        - المدى المسموح: من 1 إلى 3 أسطر (لا تزيد عن ذلك).
        - تبرز قيمة مضافة لا يعرفها الجميع
        
        استخدم الكلمة المفتاحية الأساسية "{keyword}" وهذه المرادفات بشكل طبيعي ومتنوع: {syns_str}
		⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        
        """,
        
        "pros_cons": f"""
        {strict_instructions}
        
        اكتب مقارنة متوازنة عن "{section_title}" وتشد القارئ لنهاية المقال ومتوافقة مع معايير السيو:
        - تبدأ بمقدمة قصيرة تمهد للمقارنة المتوازنة (200 حرف)
        - المميزات (أو ماذا تفعل) كاملة وشاملة (نقاط)
        - العيوب (أوماذا تتجنب) كاملة وشاملة (نقاط)
        - اختم بملاحظة قصيرة (200 حرف) تلخص وجهة نظرك كخبير
        
        استخدم الكلمة المفتاحية الأساسية "{keyword}" وهذه المرادفات بشكل طبيعي ومتنوع: {syns_str}
		⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        
        """,
        
        "emoji_check_list": f"""
        {strict_instructions}
        
        اكتب قائمة إيموجية (✅ و ❌) مباشرة عن "{section_title}" وتشد القارئ لنهاية المقال ومتوافقة مع معايير السيو:
        - تبدأ بمقدمة قصيرة تمهد لنقاط الإيموجي (200 حرف)
        - النقاط بالإيموجي
        - اختم بملاحظة قصيرة (200 حرف)
        
        استخدم الكلمة المفتاحية الأساسية "{keyword}" وهذه المرادفات بشكل طبيعي ومتنوع: {syns_str}
		⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        
        """,
        
        "conclusion": f"""
        {strict_instructions}
        
        اكتب خاتمة كاملة وشاملة عن "{section_title}" احترافية وتشد القارئ بإسلوب لا واعي علي تصفح الموقع لقراءة الكثير من المواضيع الأخرى ومتوافقة مع معايير السيو:
        - تلخص الموضوع كاملاً
        - هذه هي العناوين التي تم شرحها بالفعل في هذا المقال:
        {all_headings}
        - فقرة واحدة فقط في حدود من 2 إلى 3 أسطر
		- الدعوة لاتخاذ إجراء (Call to Action)
        - تشجع على التعليق والمشاركة بإسلوب لا واعي وحثه على قراءة المزيد من المواضيع ذات صلة
        
        استخدم الكلمة المفتاحية الأساسية "{keyword}" وهذه المرادفات بشكل طبيعي ومتنوع: {syns_str}
		⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        ابدأ الكتابة فوراً بدون أي مقدمات وبدون "الخاتمة:" أو عناوين.
        """,
        
        "text_paragraph": f"""
        {strict_instructions}
        
        اكتب فقرة عن "{section_title}" وتشد القارئ لنهاية المقال ومتوافقة مع معايير السيو:
        
		🔴 تعليمات الطول الذكي (Smart Length):
		- أنت الخبير، أنت من تقرر عدد الفقرات وطول أسطرها حدد الطول المناسب بناءً على أهمية ودسامة العنوان.
        - إذا كان العنوان فرعياً بسيطاً، اكتب فقرة واحدة فقط أو فقرتين تحت بعض فقط تكون سطراً واحداً فقط أو سطرين فقط.
        - إذا كان العنوان رئيسياً ودسماً، اكتب 3 فقرات تحت بعض فقط و3 أسطر كحد أقصى لكل فقرة.
        - المدى المسموح: من 1 إلى 3 فقرات ومن 1 إلى 3 أسطر (لا تزيد عن ذلك).
        - لا تحاول حشو الكلام، كن موجزاً ومفيداً.
        - مسافة بسيطة بين الفقرات (إذا كانت فقرتين أو 3 فقرات).
        
        استخدم الكلمة المفتاحية الأساسية "{keyword}" وهذه المرادفات بشكل طبيعي ومتنوع: {syns_str}
		⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        
        """,

        "code_prompt_script_box": f"""
        {strict_instructions}
		
        انشئ صندوق HTML مع زر نسخ (ياخذ تدرج الوان #bb3b17 و#faad2a أو ما بينهم + وخط القالب بلوجر اللي مركبه تلقائيًا) عن "{section_title}" متوافق مع معايير السيو:
		
        المطلوب:
		- ابدأ بمقدمة قصيرة تمهد للصندوق ومحتواه (200 حرف)
		- ثم الصندوق الذي بداخله كود برمجي أو برومبت أو سكريبت يخص هذا الموضوع كامل وشامل (يكون متجاوب مع الهواتف والكمبيوتر واستخدم overflow-x: auto;)
		- بدون CSS معقد
		- مهم جدًا يجب أن يكون الصندوق يأخذ خط قالب بلوجر تلقائيًا
		- إذا كان الصندوق يحتوي على كود برمجي واحد أو برومبت واحد أو سكريبت واحد فقط، فقم بإنشاء زر نسخ واحد له. أما إذا كان يحتوي على عدة أكواد برمجية أو برومبتات أو سكريبتات تحت بعض، فقم بإنشاء زر نسخ مستقل لكل صندوق على حدة فقط.


        - استخدم الكلمة المفتاحية "{keyword}" وهذه المرادفات بشكل طبيعي: {syns_str}
        - ⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        
        ابدأ كتابة الصندوق فوراً بدون أي مقدمات وبدون كتابة العنوان مرة أخرى.
        """,
		
        "summary_box": f"""
        
        أنت كاتب محتوى إبداعي (Copywriter) محترف جداً. مهمتك بيع هذا المقال للقارئ في ثوانٍ
        لديك قائمة بعناوين المقال، لا تقم بسردها مثل الفهرس الممل، بل حولها إلى "وعود وفوائد" للقارئ.
        العناوين التي سأزودك بها لاحقاً... كأن خبير بيتكلم احترافية وتشد القارئ لنهاية المقال ومتوافقة مع معايير السيو.

        ⛔ تعليمات صارمة (لتجنب الأسلوب الآلي):
        1. ممنوع تماماً استخدام عبارات: "في هذا المقال"، "سنتناول"، "يقدم هذا الدليل"، "ستتعلم".
        2. ابدأ بالنقاط فوراً لا تكون عناوين، بل تكون "ماذا سيستفيد القارئ؟" (مثلاً: بدل "شرح Midjourney"، اكتب "كيف تحول خيالك لصور في ثوانٍ").
        3. الأسلوب: حماسي، ودود، وكأنك تخبر صديقك عن كنز وجدته.
		4. اجعل النص يأخذ خط قالب بلوجر الافتراضي
		
        المحتوى:
		- عنوان جذاب وشيق وفضولي لـ "ملخص ما ستتعلمه" مع تضمين الكلمة المفتاحية هذه "{keyword}" بشكل احترافي
        - ملخص للمقال بالكامل
        - نقاط مركزة جداً
        - اجعل الأسلوب يبدو كأن خبيراً يتحدث لصديقه ليوفر عليه الوقت
        - داخل <div>...</div> بخلفية #F4CCCC أو #FFF2CC أو ألوان أخرى نفس الدرجة ما بينهم

        الشروط التقنية (مهمة جداً):
        1. يجب أن يكون المخرج النهائي داخل <div> ... </div>
        2. العنوان الرئيسي داخل الـ div يكون: <h2> ... </h2> مع {keyword}
        3. استخدم قوائم نقطية <ul> و <li> لتلخيص النقاط المهمة.
        4. لا تستخدم أي عناوين H2 أخرى داخل الـ div، فقط العنوان الرئيسي.
        5. استخدم وسوم <p> للفقرات.
		
        استخدم الكلمة المفتاحية الأساسية "{keyword}" وهذه المرادفات بشكل طبيعي ومتنوع: {syns_str}
		⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        
        """
    }
    
    base_prompt = prompts.get(section_type, prompts["text_paragraph"])
    
    return base_prompt

def analyze_intent_dynamically(title, keyword):
    """تحليل نية الباحث ديناميكياً إذا لم تكن موجودة في ملف الخطة"""
    try:
        client, selected_model = get_smart_client_and_model()
        prompt = f"""
        أنت خبير SEO الجديد. قم بتحديد "نية الباحث" (Search Intent) للمقال التالي:
        العنوان: "{title}"
        الكلمة المفتاحية: "{keyword}"
        
        اختر نية واحدة أو نيتين كحد أقصى من هذه القائمة فقط:[معلوماتية, ملاحية, استقصائية, شرائية, محلية, معلومة موجزة, وسائط, بحث مجاني, إجرائية, مختلطة, حداثة/تريند, حل مشكلات, ترفيهية, أريد أن أفعل, أريد أن أذهب, موسمية, مقارنة, ضمنية]
        
        رد بالنية فقط (مثال: معلوماتية, إجرائية) بدون أي مقدمات أو شروحات إضافية.
        """
        response = client.models.generate_content(model=selected_model, contents=prompt)
        return response.text.strip()
    except Exception as e:
        print(f"   ⚠️ فشل تحليل النية ديناميكياً: {e}")
        return "معلوماتية شاملة" # ملاذ أخير فقط لو سيرفر جوجل سقط تماماً

def write_full_article(article_data):
    """كتابة المقال مع دمج الهدف (Goal)"""
    title = article_data['title']
    keyword = article_data['keyword']
    meta_description = article_data.get('meta_description', '')

    # 1. سحب الهدف والنية من ملف الخطة مع طباعة اللوج
    article_goal = article_data.get('goal', f'تقديم دليل شامل ومفيد حول {keyword} يساعد القارئ على الفهم والتطبيق.')
    print(f"   🎯 تم التقاط هدف المقال: {article_goal}")
	
    search_intent = article_data.get('search_intent', "")
    if isinstance(search_intent, list):
        search_intent = " ".join(search_intent)
        
    # 2. التأكد من وجود نية صالحة، وإلا نقوم بتحليلها ديناميكياً عبر الذكاء الاصطناعي
    valid_intents =["معلوماتية", "ملاحية", "استقصائية", "شرائية", "محلية", "معلومة موجزة", "وسائط", "مجاني", "إجرائية", "أفعل", "مختلطة", "حداثة", "تريند", "مشكلات", "حل", "ترفيهية", "أذهب", "موسمية", "مقارنة", "ضمنية"]
    has_valid_intent = any(vi in search_intent for vi in valid_intents)
    
    if not search_intent or not has_valid_intent:
        print(f"   ⚠️ النية غير موجودة أو غير معروفة في الخطة. جاري تحليل النية ديناميكياً...")
        search_intent = analyze_intent_dynamically(title, keyword)
        print(f"   🧠 النية المستنتجة آلياً: {search_intent}")
    else:
        print(f"   🧠 تم التقاط نية الباحث من الخطة: {search_intent}")
	
    print(f"🏗️ Generating structure for: {title}")
    original_structure = generate_article_structure(title, keyword, search_intent)

    # --- 1. تنظيف الهيكل وتجميع الأسئلة التائهة ---
    final_body = []
    collected_questions = []
    faq_section = None
    conclusion_section = None
    
    question_starters = ('هل ', 'كيف ', 'ما ', 'لماذا ', 'متى ', 'أين ', 'كم ')
    
    for item in original_structure:
        t_lower = item['type'].lower()
        title_text = item['title'].strip()
        
        # لو خاتمة، نركنها على جنب
        if 'conclusion' in t_lower or 'خاتمة' in title_text:
            item['type'] = 'conclusion'
            item['title'] = 'خاتمة'
            conclusion_section = item
            continue
            
        # لو قسم الأسئلة الشائعة الرسمي
        if 'faq' in t_lower or 'أسئلة' in title_text:
            faq_section = item
            continue
            
        # لو عنوان عادي بس صيغته سؤال (سؤال تائه)، ناخده معانا
        if title_text.endswith('?') or title_text.startswith(question_starters):
            collected_questions.append(title_text)
        else:
            # عنوان عادي جداً، يفضل في مكانه
            final_body.append(item)

    # لو مفيش قسم أسئلة، ننشئ واحد عشان نحط فيه الأسئلة التائهة
    if not faq_section:
        faq_section = {"level": "h2", "type": "faq", "title": "أسئلة شائعة تهمك"}
    
    # نخزن الأسئلة التائهة عشان نستخدمها واحنا بنكتب قسم الأسئلة
    faq_section['extra_questions_from_structure'] = collected_questions
    
    # نعيد بناء الهيكل النهائي المرتب
    structure = final_body + [faq_section]
    if conclusion_section:
        structure.append(conclusion_section)

    print(f"🔍 Generating synonyms for keyword: {keyword}")
    synonyms = get_synonyms(keyword)
    print(f"   ✅ Synonyms: {', '.join(synonyms[:5])}{'...' if len(synonyms) > 5 else ''}")

    # 1. توليد الرابط الإنجليزي (Slug)
    raw_slug = create_permalink_gemini(keyword)
    
    # تنظيف الرابط
    final_slug = raw_slug.lower().strip()
    final_slug = re.sub(r'\s+', '-', final_slug) 
    final_slug = re.sub(r'-+', '-', final_slug)  
    final_slug = final_slug.strip('-')           
    
    # 2. بناء بداية المقال
    full_html = f"""
{final_slug}
<br>
{meta_description}
<br>
<br>
"""
    
    # متغير لتتبع البولد عالمياً (عشان ميكررش البولد في المقال كله)
    global_bold_tracker = set()

    # 1. إعداد الجلسة الأولى
    client, selected_model = get_smart_client_and_model(force_rotate=False)
    config = types.GenerateContentConfig(safety_settings=SAFETY_SETTINGS)
    chat = client.chats.create(model=selected_model, config=config)

    # --- السيستم برومبت الجديد (يتضمن الهدف) ---
    setup_prompt = f"""
	أنت كاتب وخبير في صناعة المحتوي الكتابي المتوافق مع معايير السيو الجديدة وخبير متخصص في السيو الجديد.
    🎯 هدف المقال الرئيسي: "{article_goal}"
    🧠 نية الباحث (Search Intent): "{search_intent}"
    قواعد الكتابة:
	1. تقمص شخصية الكاتب المناسبة لنية الباحث
    2. نفذ هذا الهدف في كل فقرة تكتبها
    3. اكتب أي إجابة في هذه المحادثة من البداية إلى النهاية بالعربية الفصحى البسيطة والسلسة والممتعة
	4. اكتب بصيغة المتكلم (ضمائر المتكلم)
    5. أسلوب بشري طبيعي جديد وحصري واحترافي ومميز
    6. استخدم "{keyword}" ومرادفاتها طبيعياً
    7. ابدأ الكتابة مباشرة بدون مقدمات أو عناوين إضافية
    8. لا تكرر العناوين
    9. لا تستخدم علامات ** أو علامات اقتباس مزدوجة "" في أي نص نهائياً
    
    مهم جداً: عندما أطلب منك كتابة محتوى، اكتبه مباشرة بدون أي مقدمات.
	"""

    try:
        chat.send_message(setup_prompt)
        print("   ✅ Setup complete. Waiting 25s...")
        time.sleep(25)
    except:
        pass
	
    mid_index = len(structure) // 2

    # جمع كل عناوين المقال كنص واحد لكي تقرأها الخاتمة
    all_headings_text = "\n".join([f"- {item['title']}" for item in structure if item['type'] not in ['introduction', 'conclusion']])

    current_h2_context = "" # متغير لتخزين عنوان القسم الحالي
	
    # 3. المرور على الأقسام ببطء شديد
    for i, section in enumerate(structure):
        level = section.get('level', 'h2')
        title_text = section.get('title', '')
        # تنظيف العنوان من الإيموجي
        title_text = re.sub(r'[^\w\s\u0600-\u06FF\d\-\(\)]', '', title_text).strip()
        sec_type = section.get('type', 'text_paragraph')
        if level == 'h2':
            current_h2_context = title_text # احفظ العنوان الكبير

        # استخراج العنوان القادم (لكي تسلم الفقرة الحالية له)
        next_section_title = structure[i+1]['title'] if i+1 < len(structure) else ""
		
        # إضافة العناوين HTML (إلا لو كانت خاتمة أو مقدمة بدون عنوان صريح)
        write_title = True
        if sec_type == 'conclusion': write_title = False
        # إخفاء عنوان المقدمة فقط إذا كان فارغاً أو كلمة "مقدمة" مجردة، أما لو كان عنواناً جذاباً فأظهره كـ h2
        if sec_type == 'introduction' and (not title_text or title_text.strip() == 'مقدمة'): write_title = False

        if sec_type == 'faq':
             full_html += f"<h2>{title_text}</h2>\n"
             write_title = False
             
             # نجهز البرومبت الأساسي مباشرة بدون المكتبة القديمة
             prompt = get_content_prompt(sec_type, title_text, keyword, synonyms, search_intent, article_goal, next_section_title, all_headings_text)
				 
        if write_title and title_text:
            if level == 'h2': full_html += f"<h2>{title_text}</h2>\n"
            elif level == 'h3': full_html += f"<h3>{title_text}</h3>\n"
            elif level == 'h4': full_html += f"<h4>{title_text}</h4>\n"
        
        # تجهيز البرومبت
        # --- بداية كود البحث المضاف ---
        web_context = ""
        # نبحث فقط في الفقرات التي تحتاج معلومات (ليست مقدمة أو خاتمة)
        if sec_type in ['text_paragraph', 'faq', 'list_bullet', 'list_numbered', 'table']:
            # نبحث عن العنوان + الكلمة المفتاحية
            search_query = f"{title_text} {keyword}"
            web_context = search_google_info(search_query)
            if web_context:
                print(f"   🔍 Found info: {web_context[:1000]}...") # يطبع أول 1000 حرف فقط للتأكيد
        # -----------------------------

        prompt = get_content_prompt(sec_type, title_text, keyword, synonyms, search_intent, article_goal, next_section_title, all_headings_text)

        # --- حقن المعلومات في البرومبت (بذكاء وحصرية) ---
        if web_context:
            prompt += f"""
            
            🌍 مصادر ومعلومات حديثة (للاطلاع فقط):
            {web_context}
            
            ⛔ تعليمات هامة جداً للتعامل مع هذه المعلومات:
            1. استخدم المعلومات والأرقام والحقائق الموجودة هنا لضمان دقة المحتوى وحداثته.
            2. ❌ ممنوع النسخ أو الترجمة الحرفية لهذه النصوص نهائياً.
            3. أعد صياغة المعلومات بأسلوبك الخاص (أسلوب الخبير العربي المحترف) الذي طلبته منك سابقاً.
            4. ادمج هذه المعلومات بسلاسة داخل الفقرة وكأنها من خبرتك الشخصية.
            5. الهدف هو الحصرية والتميز، لا التكرار.
            """
            print("   ✅ Web context attached to prompt.") # تأكيد
            print(f"   📜 PROMPT PREVIEW: {prompt[:300]}...") # الكلام الإنجليزي الذي جلبه من البحث
        # -------------------------------
        
        prompt += "\n\nأعطني المحتوى بصيغة HTML فقط (p, ul, li, table...) بدون ```html"
        
        # محاولات الكتابة
        success = False
        retries = 0
        max_retries = 3 
        
        while not success and retries < max_retries:
            try:
                print(f"   ✍️ Writing: {title_text} ({sec_type})...")
            
                # إعادة الجلسة عند الخطأ
                if retries > 0:
                    print("   🔄 Starting NEW session due to error...")
                    # هنا بنغير المفتاح والكلام ده...
                    
                    # نبدأ شات جديد
                    client, selected_model = get_smart_client_and_model(force_rotate=True)
                    config = types.GenerateContentConfig(safety_settings=SAFETY_SETTINGS)
                    chat = client.chats.create(model=selected_model, config=config)
                    
                    try: 
                        # 1. نبعت برومبت التهيئة الأساسي (عربي فصحى وغيره)
                        chat.send_message(setup_prompt)
                        
                        # 2. تذكير الموظف الجديد (جيميناي) بموقعه في المقال
                        print(f"   🧠 Reminding Gemini of context for: {title_text}")
                        if level == 'h3' and current_h2_context:
                            reminder = f"تذكير بالسياق: نحن نكتب الآن مقالاً بعنوان '{title}'. وصلنا تحديداً لكتابة فقرة فرعية بعنوان '{title_text}' تابعة للقسم الرئيسي '{current_h2_context}'. أكمل الكتابة بناءً على هذا السياق."
                        elif sec_type == 'conclusion':
                            reminder = f"تذكير بالسياق: نحن نكتب مقالاً بعنوان '{title}'. وصلنا الآن لكتابة 'الخاتمة' الشاملة للمقال. أكمل الكتابة."
                        elif sec_type == 'faq':
                            reminder = f"تذكير بالسياق: نحن نكتب مقالاً بعنوان '{title}'. وصلنا الآن لكتابة قسم 'الأسئلة الشائعة'. أكمل الكتابة."
                        else:
                            # للـ H2 أو أي فقرة رئيسية أخرى
                            reminder = f"تذكير بالسياق: نحن نكتب الآن مقالاً بعنوان '{title}'. وصلنا تحديداً لكتابة قسم رئيسي بعنوان '{title_text}'. أكمل الكتابة."
                            
                        chat.send_message(reminder)
                            
                    except: pass

                # الإرسال
                response = chat.send_message(prompt)
                content = response.text.replace("```html", "").replace("```", "").strip()
                content = clean_text_symbols(content)
                
                # 1. تنظيف أولي: إزالة أي بولد وضعه Gemini داخل الجداول (عشان يبقى الجدول نضيف)
                if '<table>' in content:
                    def strip_bold_tags(match):
                        return re.sub(r'</?(b|strong)>', '', match.group(0), flags=re.IGNORECASE)
                    content = re.sub(r'<table.*?>.*?</table>', strip_bold_tags, content, flags=re.DOTALL)

                # 2. الآن نطبق البولد بتاعنا (كلمات مفتاحية فقط) على النص كله
                content = make_keywords_bold(content, keyword, synonyms, global_bold_tracker)
                
                if len(content) < 50: raise Exception("Content too short")
                
                full_html += content
                
                # الفاصل (نتأكد أنه ليس الأخير وليس قبل الخاتمة مباشرة إذا كانت بدون عنوان)
                if i < len(structure) - 1:
                    full_html += "\n<br>\n"
                
                success = True
                print(f"   ✅ Done.")
                
                print("   ⏳ Sleeping 65s to avoid Quota limit...")
                time.sleep(65)

            except Exception as e:
                retries += 1
                
                # --- أضف هذا السطر لتغيير المفتاح الحالي عند الخطأ ---
                global CURRENT_KEY
                # نختار مفتاح عشوائي جديد غير الحالي
                other_keys = [k for k in GEMINI_API_KEYS if k != CURRENT_KEY]
                if other_keys:
                    CURRENT_KEY = random.choice(other_keys)
                    print(f"   🔄 Switched to a new API Key due to error.")
                # ---------------------------------------------------

                wait_time = 75 * retries 
                print(f"   ⚠️ Error ({e}). Waiting {wait_time}s...")
                time.sleep(wait_time) 
                
                if retries == max_retries:
                    full_html += f"<p>...</p>\n" # فشل صامت أفضل من رسالة خطأ

    # --- الملخص المطور (يعتمد على العناوين + تنسيق ملون) ---
    print("   📝 Generating Summary based on Headings...")
    summary_success = False
    sum_retries = 0
    
    # 1. استخراج العناوين فقط لبناء ملخص ذكي
    # نأخذ كل العناوين ما عدا قسم الأسئلة (لأنه طويل ومكرر في الملخص)
    headings_context = []
    found_faq = False
    for item in structure:
        if 'faq' in item['type'].lower() or 'أسئلة' in item['title']:
            found_faq = True # وصلنا للأسئلة، نوقف الجمع أو نضيف عنوانها فقط
            headings_context.append(f"- قسم الأسئلة الشائعة: {item['title']}")
            break # كفاية كده، مش محتاجين تفاصيل الأسئلة في الملخص
        
        headings_context.append(f"- {item['level'].upper()}: {item['title']}")
    
    headings_text = "\n".join(headings_context)
    
    while not summary_success and sum_retries < 3:
        try:
            sum_prompt = get_content_prompt("summary_box", "ملخص", keyword, synonyms, search_intent, article_goal, "", all_headings_text)
            sum_prompt += f"\n\nالعناوين:\n{headings_text}" # نرفق العناوين هنا
            
            sum_client, sum_selected_model = get_smart_client_and_model()
            sum_config = types.GenerateContentConfig(safety_settings=SAFETY_SETTINGS)
            summary_chat = sum_client.chats.create(model=sum_selected_model, config=sum_config)
            
            res = summary_chat.send_message(sum_prompt)
            sum_content = clean_text_symbols(res.text.replace("```html","").replace("```",""))
            
            # تطبيق البولد الذكي
            sum_content = make_keywords_bold(sum_content, keyword, synonyms, global_bold_tracker)
                
            # حقن الخلاصة بدقة: بعد المقدمة (التي عادة ما تكون فقرتين بعد الميتا)
            # المنطق: نبحث عن أول عنوان H2، ونضع الخلاصة قبله مباشرة.
            # (لأن المقدمة تأتي دائماً قبل أول عنوان H2)
            
            first_h2_index = full_html.find('<h2>')
            
            if first_h2_index != -1:
                # نفصل النص جزئين عند أول عنوان
                before_h2 = full_html[:first_h2_index]
                after_h2 = full_html[first_h2_index:]
                
                # إزالة أي فواصل <br> زائدة في نهاية المقدمة قبل حقن الملخص
                clean_before = re.sub(r'(<br>\s*)+$', '', before_h2.strip())
                # نركبهم تاني مع فاصل واحد فقط
                full_html = f"{clean_before}\n<br>\n{sum_content}\n<br>\n{after_h2}"
            else:
                # خطة بديلة لو مفيش عناوين خالص (نادر): نحطه بعد رابع <br> (يعني بعد الفقرات الأولى)
                # لأن النص بيبدأ بـ: سبيس -> ميتا -> سبيس -> مقدمة1 -> مقدمة2
                parts = full_html.split('<br>', 4)
                if len(parts) >= 4:
                    parts.insert(4, f'\n{sum_content}\n') # بعد رابع فاصل
                    full_html = '<br>'.join(parts)
                else:
                    # لو النص قصير جداً، نحطه في الآخر وخلاص
                    full_html += f"\n<br>\n{sum_content}"
                
            print("   ✅ Summary injected.")
            summary_success = True
            time.sleep(30)
            
        except Exception as e:
            sum_retries += 1
            print(f"   ⚠️ Summary failed (Attempt {sum_retries}/3): {e}")
            
            # تبديل المفتاح عند الفشل
            if sum_retries < 3:
                # كود تدوير المفتاح
                other_keys = [k for k in GEMINI_API_KEYS if k != CURRENT_KEY]
                if other_keys:
                    CURRENT_KEY = random.choice(other_keys)
                    print(f"   🔄 Switched Key for summary retry.")
                time.sleep(10) # راحة قصيرة

    # --- التعديل: تنسيق العناوين : إلى | ---
    full_html = format_headings_style(full_html)

    return full_html

def inject_external_links(html_content, external_dict):
    """
    محرك الربط الخارجي الذكي (نسخة التتبع العميق):
    يتجاهل العناوين ورؤوس الجداول حتى لو كانت متداخلة.
    يزرع الرابط مرة واحدة فقط للكلمة في المقال بأكمله.
    """
    print("   🌍 Injecting External Nofollow Links automatically...")
    
    parts = re.split(r'(<[^>]+>)', html_content)
    # قائمة الأوسام الممنوع وضع روابط بداخلها (تم إضافة رؤوس الجداول th و thead)
    restricted_tags = ['h1', 'h2', 'h3', 'h4', 'a', 'th', 'thead', 'button']
    
    for brand, url in external_dict.items():
        brand_injected = False
        inside_restricted_count = 0  # عداد ذكي لتتبع التداخل
        
        for i, part in enumerate(parts):
            if brand_injected: 
                break # الكلمة تم ربطها مرة، نخرج وندخل على الكلمة التي بعدها في القاموس
            
            # إذا كان الجزء عبارة عن كود HTML، نقوم بتحديث العداد
            if part.startswith('<'):
                tag_match = re.match(r'</?([a-zA-Z0-9]+)', part)
                if tag_match:
                    tag_name = tag_match.group(1).lower()
                    if tag_name in restricted_tags:
                        # إذا كان وسم إغلاق، ننقص العداد
                        if part.startswith('</'):
                            inside_restricted_count = max(0, inside_restricted_count - 1)
                        # إذا كان وسم فتح (وليس إغلاق ذاتي)، نزيد العداد
                        elif not part.endswith('/>'):
                            inside_restricted_count += 1
                continue
            
            # إذا كان نصاً عادياً، ولسنا داخل أي وسم ممنوع (العداد = 0)
            if inside_restricted_count == 0:
                pattern = r'(?<![\w\u0600-\u06FF])' + re.escape(brand) + r'(?![\w\u0600-\u06FF])'
                
                if re.search(pattern, part, flags=re.IGNORECASE):
                    # زرع الرابط الخارجي (Nofollow + Blank) مرة واحدة فقط
                    replacement = f'<a href="{url}" target="_blank" rel="nofollow">{brand}</a>'
                    parts[i] = re.sub(pattern, replacement, part, count=1, flags=re.IGNORECASE)
                    brand_injected = True
                    print(f"      ✅ Linked external brand '{brand}' successfully.")
                    
    return ''.join(parts)

def get_external_links_from_github(repo):
    """
    يقرأ الروابط الخارجية من ملف على جيت هاب.
    إذا لم يكن الملف موجوداً، يقوم بإنشائه فارغاً لتقوم أنت بتعبئته لاحقاً.
    """
    file_path = "external_links.json"
    try:
        content = repo.get_contents(file_path).decoded_content.decode('utf-8')
        links_dict = json.loads(content)
        print(f"   🌍 Loaded {len(links_dict)} external links from GitHub.")
        return links_dict
    except Exception:
        # إذا لم يجد الملف، ينشئ واحداً كنموذج
        print("   ⚠️ external_links.json not found. Creating a default one...")
        default_dict = {"Gemini": "https://gemini.google.com/", "ChatGPT": "https://chatgpt.com/"}
        try:
            repo.create_file(file_path, "Create external links file", json.dumps(default_dict, indent=2))
        except: pass
        return default_dict

def main():
    try:
        logger.info("🚀 Starting article generation process...")
        
        auth = Auth.Token(GITHUB_TOKEN)
        g = Github(auth=auth)
        repo = g.get_repo(REPO_NAME)

        plan_files = [f for f in repo.get_contents(PLANS_DIR) if f.name.endswith(".json")]
        if not plan_files:
            logger.warning("No content plans found.")
            return

        selected_file = random.choice(plan_files)
        logger.info(f"📂 Selected plan: {selected_file.name}")
        
        content_json = json.loads(selected_file.decoded_content.decode("utf-8"))
        
        if not content_json:
            logger.warning("Plan is empty.")
            return

        article = content_json[0]
        
        logger.info(f"📝 Generating article: {article['title']}")
        post_body = write_full_article(article)
        # --- تشغيل المحركات النهائية في دالة main (حيث يتوفر repo) ---
        logger.info("⚙️ Running final formatting and linking engines...")
        try:
            service = get_blogger_service()
            
            # 1. الربط الخارجي من ملف جيت هاب
            external_dict = get_external_links_from_github(repo)
            post_body = inject_external_links(post_body, external_dict)
            
            # 2. الربط الداخلي الذكي (يعتمد على repo و service)
            post_body = apply_smart_internal_linking(post_body, repo, service)
            
        except Exception as engine_err:
            logger.error(f"⚠️ Error running final engines (Skipping to publish): {engine_err}")
        
        try:
            category_name = selected_file.name.replace("content_plan_", "").replace(".json", "").replace("_", " ")
            
            post_data = {
                "kind": "blogger#post",
                "blog": {"id": BLOG_ID},
                "title": article['title'],
                "content": post_body,
                "labels": [category_name],
            }
            
            result = service.posts().insert(blogId=BLOG_ID, body=post_data, isDraft=True).execute()
            logger.info(f"✅ Published draft: {article['title']}")
            logger.info(f"🔗 Permalink and Meta info added at the top of the post content")

            if not TEST_MODE:
                new_plan = content_json[1:]
                updated_content = json.dumps(new_plan, indent=2, ensure_ascii=False)
                repo.update_file(selected_file.path, f"Published: {article['title']}", updated_content, selected_file.sha)
                logger.info("🗑️ Removed article from plan.")

                try:
                    pub_file = repo.get_contents("published_titles.txt")
                    new_pub_content = pub_file.decoded_content.decode("utf-8") + "\n" + article['title']
                    repo.update_file("published_titles.txt", "Add published title", new_pub_content, pub_file.sha)
                except:
                    repo.create_file("published_titles.txt", "Create published list", article['title'])
            else:
                logger.info("⚠️ TEST MODE ENABLED: Article was NOT removed from the plan & NOT added to published list.")

        except Exception as e:
            # عند فشل النشر، لا تنقل الملف ولا تفعل شيء
            logger.error(f"❌ Error publishing to Blogger: {e}")
            logger.info("⚠️ Keeping the plan file in place to retry later.")

    except Exception as e:
        # الخطأ العام للسكريبت
        logger.error(f"❌ Critical error in main(): {e}", exc_info=True)
        # لا نحذف الملف ولا نغير مكانه
        # raise # يمكنك إزالة raise لو مش عايز الـ Action يبان أحمر، بس الأفضل تسيبه عشان تعرف إن فيه مشكلة
        raise

if __name__ == "__main__":
    main()
