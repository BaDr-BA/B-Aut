import os
import json
import random
import time
import re
import logging
from github import Github, Auth
import google.generativeai as genai
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from googletrans import Translator
import typing_extensions as typing
from googlesearch import search
from datetime import datetime
import people_also_ask

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

# --- الإعدادات والمفاتيح ---
GEMINI_API_KEYS = [os.environ.get(f"GEMINI_API_KEY_{i}") for i in range(1, 7) if os.environ.get(f"GEMINI_API_KEY_{i}")]
CURRENT_KEY = None # نخزن فيه المفتاح المختار لهذه الجلسة
CLIENT_ID = os.environ.get("BLOGGER_CLIENT_ID")
CLIENT_SECRET = os.environ.get("BLOGGER_CLIENT_SECRET")
REFRESH_TOKEN = os.environ.get("BLOGGER_REFRESH_TOKEN")
BLOG_ID = os.environ.get("BLOGGER_BLOG_ID")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPO_NAME = "BaDr-BA/B-Aut"
PLANS_DIR = "plans"

# إعدادات الأمان لـ Gemini (لتقليل الحجب)
SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

def get_blogger_service():
    creds = Credentials(None, refresh_token=REFRESH_TOKEN, token_uri="https://oauth2.googleapis.com/token", client_id=CLIENT_ID, client_secret=CLIENT_SECRET)
    return build('blogger', 'v3', credentials=creds)

def clean_json_response(text):
    """تنظيف رد Gemini لاستخراج JSON صالح"""
    text = text.replace("```json", "").replace("```", "").strip()
    return text

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

def get_real_google_questions(keyword, existing_titles=[]):
    """جلب أسئلة حقيقية مع استبعاد العناوين المكررة في المقال"""
    try:
        print(f"   ❓ Fetching real PAA questions for: {keyword}...")
        
        # نجلب أسئلة من المكتبة
        raw_questions = []
        try:
            # نجلب حتى 25 سؤال
            for q in people_also_ask.get_related_questions(keyword, 25):
                raw_questions.append(q)
        except: pass

        # مرحلة الفلترة (عشان ميكررش عناوين موجودة في المقال)
        final_questions = []
        for q in raw_questions:
            is_duplicate = False
            for title in existing_titles:
                # لو السؤال شبه عنوان موجود بنسبة كبيرة
                if q.strip() in title.strip() or title.strip() in q.strip(): 
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                final_questions.append(q)
        
        # نختار عدد عشوائي من الأسئلة النظيفة
        if final_questions:
            # نختار من 5 لـ 25 (أو العدد المتاح لو أقل)
            count = random.randint(5, min(len(final_questions), 25))
            selected_qs = random.sample(final_questions, count)
            return "\n".join([f"- {q}" for q in selected_qs])
            
    except Exception as e:
        print(f"   ⚠️ PAA Error: {e}")
    return ""
	
def create_permalink_gemini(keyword_arabic):
    """توليد رابط ثابت بالإنجليزية حصراً"""
    try:
        model = get_gemini_model()
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
        response = model.generate_content(prompt)
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
    إزالة علامات الاقتباس والنجوم المزدوجة وكود keyword_strong المزعج
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
    for i, part in enumerate(parts):
        if part.startswith('<') and part.endswith('>'):
            cleaned_parts.append(part)
        else:
            cleaned_part = part.replace('"', '').replace('"', '').replace('"', '')
            cleaned_parts.append(cleaned_part)
	
    return ''.join(cleaned_parts)

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

def get_gemini_model():
    """اختيار المفتاح المحدد أو عشوائي في حالة عدم التحديد"""
    global CURRENT_KEY
    
    if not GEMINI_API_KEYS:
        raise ValueError("No Gemini API keys found!")
    
    # إذا لم يتم تحديد مفتاح بعد، اختر واحداً عشوائياً
    if CURRENT_KEY is None:
        CURRENT_KEY = random.choice(GEMINI_API_KEYS)
    
    # طباعة جزء من المفتاح للتأكد (أول 5 حروف)
    key_hint = CURRENT_KEY[:5] + "..."
    # print(f"🤖 Using API Key starting with: {key_hint}") # (اختياري للتجربة)
    
    genai.configure(api_key=CURRENT_KEY)
    
    models_list = [
        'gemma-3-27b-it',
        'gemma-3-12b-it',
    ]
    selected_model = random.choice(models_list)
    
    return genai.GenerativeModel(selected_model, safety_settings=SAFETY_SETTINGS)

def generate_article_structure(title, keyword):
    """توليد هيكل المقال بناءً على تحليل المنافسين (المحاكى)"""
    
    prompt = f"""
    أنت خبير SEO محترف ومحلل محتوى.
    مهمتك: هي إجراء تحليل عميق لأفضل 10 مقالات تتصدر نتائج بحث جوجل للعنوان "{title}" والكلمة المفتاحية "{keyword}".
	الهدف هو كشف كل الزوايا والنقاط التي لم تغطها هذه المقالات أو تناولتها بشكل سطحي.
    
    المطلوب:
	ليس كتابة تقرير، بل استنتاج "هيكل المقال المثالي" مباشرة بناءً على الفجوات التي وجدتها عند المنافسين.
    قدم ترتيبًا منطقيًا للعناوين الرئيسية (H2) والعناوين الفرعية (H3) يضمن تغطية شاملة ومتسلسلة لجميع الجوانب، القديمة والجديدة. والمناسبة لمقال متوافق مع معايير SEO الجديدة ونية الباحث لتصدر نتائج البحث.
    
    ⚠️ مهم جداً: تجنب تكرار نفس العنوان مرتين! كل عنوان يجب أن يكون فريداً ومختلفاً.

    قواعد الهيكل:
    1. يجب أن يغطي نقاط الضعف عند المنافسين.
    2. تسلسل منطقي.
    3. العناوين يجب أن تكون جذابة وليست تقليدية.
    4. تجنب تكرار العناوين.
	
    بجانب كل عنوان، حدد:
    - level: إما "h2" أو "h3" أو "intro" (للمقدمة فقط في البداية)
    - type: نوع المحتوى من هذه القائمة حصراً: [introduction, list_bullet, list_numbered, table, faq, conclusion, text_paragraph, featured_paragraph, pros_cons, emoji_check_list]
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
            model = get_gemini_model() # تغيير الموديل مع كل محاولة
            response = model.generate_content(prompt)
            
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
                time.sleep(20)

    # إذا فشلت كل المحاولات، نرفع خطأ ليتم إيقاف العملية والحفاظ على الخطة
    raise Exception("❌ Failed to generate article structure after retries. Aborting to save plan.")

def get_synonyms(keyword):
    """
    توليد مرادفات للكلمة المفتاحية تلقائياً باستخدام Gemini
    """
    try:
        model = get_gemini_model()
        prompt = f"""
        أنت خبير SEO الجديد متخصص في البحث عن الكلمات المفتاحية.
        
        المطلوب: أعطني من 7 إلى 70 كلمة مفتاحية مرادفة أو ذات صلة قوية بالكلمة الأساسية: "{keyword}"
        
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
        response = model.generate_content(prompt)
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
        
        # إزالة التكرار والحد الأقصى 70 كلمة
        synonyms = list(dict.fromkeys(synonyms))[:70]
        
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

def get_content_prompt(section_type, section_title, keyword, synonyms_list=None):
    """اختيار البرومبت المناسب مع مرادفات عشوائية"""
    
    # نرسل كل المرادفات المتاحة (أول 35 مثلاً لتجنب الطول الزائد في البرومبت)
    # ليختار الذكاء الاصطناعي الأنسب منها للسياق
    current_synonyms = synonyms_list[:35] if synonyms_list else []
    
    # تحويل القائمة لنص
    syns_str = ', '.join(current_synonyms) if current_synonyms else keyword

    # إضافة تعليمات نهائية موحدة
    strict_instructions = """
    ⛔ تعليمات صارمة جداً:
    1. ممنوع كتابة أي مقدمات أو مقدمة ترحيبية (مثل: بالتأكيد، إليك الفقرة...، ...إلخ).
    2. ممنوع كتابة العناوين مرة أخرى.
    3. التزم بعدد الأسطر المحدد بدقة.
    4. ابدأ مباشرة بالمحتوى المطلوب.
    5. لا تستخدم "المقدمة:" أو "الخاتمة:" أو أي عناوين.
    6. اكتب بأسلوب بشري طبيعي ومباشر 100% وموجه لنية الباحث وهدفه 100%.
    """

    prompts = {
        "introduction": f"""
        {strict_instructions}
        
        المطلوب: اكتب مقدمة مشوقة جداً (Hook) تخاطب القارئ مباشرة بعنوان "{section_title}" لنية الباحث كأن خبير بيتكلم احترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو.
        
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
        
        المطلوب: قائمة تنقيطية كاملة وشاملة عن "{section_title}" موجهة لنية الباحث + كأن خبير بيتكلم احترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو:
        - تبدأ بمقدمة قصيرة تمهد للنقاط (200 حرف)
        - ثم النقاط التنقيطية كاملة وشاملة
        - اختم بملاحظة قصيرة (200 حرف)
        
        استخدم الكلمة المفتاحية الأساسية "{keyword}" وهذه المرادفات بشكل طبيعي ومتنوع: {syns_str}
		⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        
        """,
        
        "list_numbered": f"""
        {strict_instructions}
        
        المطلوب: قائمة مرقمة كاملة وشاملة عن "{section_title}" موجهة لنية الباحث + كأن خبير بيتكلم احترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو:
        - تبدأ بمقدمة قصيرة تمهد للترقيم (200 حرف)
        - القائمة المرقمة كاملة وشاملة
        - اختم بملاحظة قصيرة (200 حرف)
        
        استخدم الكلمة المفتاحية الأساسية "{keyword}" وهذه المرادفات بشكل طبيعي ومتنوع: {syns_str}
		⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        
        """,
        
        "table": f"""
        {strict_instructions}
        
        انشئ جدول HTML (ياخذ الوان #bb3b17 و#faad2a أو ما بينهم + وخط القالب بلوجر اللي مركبه تلقائيًا) عن "{section_title}" موجهة لنية الباحث + كأن خبير بيتكلم احترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو:
        - تبدأ بمقدمة قصيرة تمهد للجدول ومحتواه (200 حرف)
        - ثم الجدول كامل وشامل (يكون متجاوب مع الهواتف والكمبيوتر)
        - بدون CSS معقد
        - استخدم الكلمة المفتاحية "{keyword}" وهذه المرادفات بشكل طبيعي: {syns_str}
        - ⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        
        ابدأ كتابة الجدول فوراً بدون أي مقدمات وبدون كتابة العنوان مرة أخرى.
        """,
        
        "faq": f"""
        {strict_instructions}

		أكتب أسئلة شائعة وأجوبة عن "{section_title}" موجهة لنية الباحث + كأن خبير بيجاوب باحترافية وتشد القارئ للقراءة لنهاية الأسئلة والأجوبة وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو:
        لديك قائمة بأسئلة حقيقية يبحث عنها الناس في جوجل الأسئلة من اقتراحات جوجل التلقائية (تم البحث أيضًا عن). وقسم "الناس أيضًا يسألون" (People Also Ask). وقسم أسئلة أخرى.
        المطلوب:
        - ابدأ بمقدمة قصيرة تمهد للأسئلة والأجوبة (200 حرف)
        - كل إجابة لا تزيد عن سطرين
		- كل اجابة تبرز قيمة مضافة لا يعرفها الجميع
        - استخدم رمز ◀️ أو ↩ في بداية الجواب

        ⛔ تحذير هام:
        - لا تكتب العنوان الرئيسي "{section_title}" مرة أخرى.
        - ابدأ فوراً بالسؤال الأول.
        الشروط:
        1. اجعل كل سؤال في وسم <h3>.
        2. اجعل الإجابة تحته مباشرة في وسم <p>.
        3. لا تستخدم قوائم أو ترقيم، فقط h3 ثم p.
        التنسيق المطلوب:
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
        
        اكتب فقرة مميزة عن "{section_title}" موجهة لنية الباحث + كأن خبير بيتكلم احترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو:
        - بعنوان "خلاصة تجربة أو خبرة موقع تقنجي"
        - أسلوب شخصي دافئ (First-person perspective) سواء 'نصيحة من القلب' أو 'سر المهنة' أو 'رؤية تحليلية' أو 'تطبيق عملي' أو 'واقع السوق' أو 'تنبيه للمحترفين'  أو أي حاجة حسب الموضوع وكأنك تشارك القارئ تجربة شخصية حصرية
        - المدى المسموح: من 1 إلى 3 أسطر (لا تزيد عن ذلك).
        - تبرز قيمة مضافة لا يعرفها الجميع
        
        استخدم الكلمة المفتاحية الأساسية "{keyword}" وهذه المرادفات بشكل طبيعي ومتنوع: {syns_str}
		⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        
        """,
        
        "pros_cons": f"""
        {strict_instructions}
        
        اكتب مقارنة متوازنة عن "{section_title}" موجهة لنية الباحث + كأن خبير بيتكلم احترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو:
        - تبدأ بمقدمة قصيرة تمهد للمقارنة المتوازنة (200 حرف)
        - المميزات (أو ماذا تفعل) كاملة وشاملة (نقاط)
        - العيوب (أوماذا تتجنب) كاملة وشاملة (نقاط)
        - اختم بملاحظة قصيرة (200 حرف) تلخص وجهة نظرك كخبير
        
        استخدم الكلمة المفتاحية الأساسية "{keyword}" وهذه المرادفات بشكل طبيعي ومتنوع: {syns_str}
		⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        
        """,
        
        "emoji_check_list": f"""
        {strict_instructions}
        
        اكتب قائمة إيموجية (✅ و ❌) مباشرة عن "{section_title}" موجهة لنية الباحث + كأن خبير بيتكلم احترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو:
        - تبدأ بمقدمة قصيرة تمهد لنقاط الإيموجي (200 حرف)
        - النقاط بالإيموجي
        - اختم بملاحظة قصيرة (200 حرف)
        
        استخدم الكلمة المفتاحية الأساسية "{keyword}" وهذه المرادفات بشكل طبيعي ومتنوع: {syns_str}
		⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        
        """,
        
        "conclusion": f"""
        {strict_instructions}
        
        اكتب خاتمة كاملة وشاملة وموجهة لنية الباحث + كأن خبير بيختم عن "{section_title}" احترافية وتشد القارئ بإسلوب لا واعي علي تصفح الموقع لقراءة الكثير من المواضيع الأخرى وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو:
        - تلخص الموضوع كاملاً
        - فقرة واحدة فقط في حدود من 2 إلى 4 أسطر
		- الدعوة لاتخاذ إجراء (Call to Action)
        - تشجع على التعليق والمشاركة بإسلوب لا واعي وحثه على قراءة المزيد من المواضيع ذات صلة
        
        استخدم الكلمة المفتاحية الأساسية "{keyword}" وهذه المرادفات بشكل طبيعي ومتنوع: {syns_str}
		⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        ابدأ الكتابة فوراً بدون أي مقدمات وبدون "الخاتمة:" أو عناوين.
        """,
        
        "text_paragraph": f"""
        {strict_instructions}
        
        اكتب فقرة عن "{section_title}" موجهة لنية الباحث + كأن خبير بيتكلم احترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو:
        
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
        
        "summary_box": f"""
        
        أنت كاتب محتوى إبداعي (Copywriter) محترف جداً. مهمتك بيع هذا المقال للقارئ في ثوانٍ
        لديك قائمة بعناوين المقال، لا تقم بسردها مثل الفهرس الممل، بل حولها إلى "وعود وفوائد" للقارئ.
        العناوين التي سأزودك بها لاحقاً...
		موجهة لنية الباحث + كأن خبير بيتكلم احترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو.

        ⛔ تعليمات صارمة (لتجنب الأسلوب الآلي):
        1. ممنوع تماماً استخدام عبارات: "في هذا المقال"، "سنتناول"، "يقدم هذا الدليل"، "ستتعلم".
        2. ابدأ بسؤال صادم أو جملة تخاطب ألم القارئ أو فضوله مباشرة.
        3. النقاط لا تكون عناوين، بل تكون "ماذا سيستفيد القارئ؟" (مثلاً: بدل "شرح Midjourney"، اكتب "كيف تحول خيالك لصور في ثوانٍ").
        4. الأسلوب: حماسي، ودود، وكأنك تخبر صديقك عن كنز وجدته.
		
        المحتوى:
		- عنوان جذاب وشيق وفضولي لـ "خلاصة سريعة" مع تضمين الكلمة المفتاحية هذه "{keyword}" بشكل احترافي
        - ابدأ بجملة تشرح أن هذا هو ملخص ما سيجده الباحث أو القارئ
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
        
        """,
        
        "motivation_box": f"""
        {strict_instructions}
        
        اكتب فقرة تحفيزية قصيرة لا تتجاوز سطرين احترافية وفضولية ومشوقة.
        - أسلوب بشري جذاب بعيداً عن الصيغ البيعية المكررة
        - تشجع على إكمال القراءة
        
        استخدم الكلمة المفتاحية الأساسية "{keyword}" وهذه المرادفات بشكل طبيعي ومتنوع: {syns_str}
		⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        ابدأ فوراً في الكتابة بدون أي مقدمات.
        """
    }
    
    base_prompt = prompts.get(section_type, prompts["text_paragraph"])
    
    return base_prompt

def write_full_article(article_data):
    """كتابة المقال مع دمج الهدف (Goal)"""
    title = article_data['title']
    keyword = article_data['keyword']
    meta_description = article_data.get('meta_description', '')

    # 1. سحب الهدف من ملف الخطة
    article_goal = article_data.get('goal', f'تقديم دليل شامل ومفيد حول {keyword} يساعد القارئ على الفهم والتطبيق.')
	
    print(f"🏗️ Generating structure for: {title}")
    original_structure = generate_article_structure(title, keyword)

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
    model = get_gemini_model()
    chat = model.start_chat(history=[])

    # --- السيستم برومبت الجديد (يتضمن الهدف) ---
    setup_prompt = f"""
	أنت كاتب وخبير في صناعة المحتوي الكتابي المتوافق مع معايير السيو الجديدة وخبير متخصص في السيو الجديد.
    🎯 هدف المقال الرئيسي: "{article_goal}"
    قواعد الكتابة:
    1. نفذ هذا الهدف في كل فقرة تكتبها.
    2. اكتب أي إجابة في هذه المحادثة من البداية إلى النهاية بالعربية الفصحى البسيطة والسلسة والممتعة
    3. أسلوب بشري طبيعي جديد وحصري واحترافي ومميز
    4. استخدم "{keyword}" ومرادفاتها طبيعياً
    5. ابدأ الكتابة مباشرة بدون مقدمات أو عناوين إضافية
    6. لا تكرر العناوين
    7. لا تستخدم علامات ** أو علامات اقتباس مزدوجة "" في أي نص نهائياً
    
    مهم جداً: عندما أطلب منك كتابة محتوى، اكتبه مباشرة بدون أي مقدمات.
	"""

    try:
        chat.send_message(setup_prompt)
        print("   ✅ Setup complete. Waiting 25s...")
        time.sleep(25)
    except:
        pass
	
    mid_index = len(structure) // 2

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
        
        # إضافة العناوين HTML (إلا لو كانت خاتمة أو مقدمة بدون عنوان صريح)
        write_title = True
        if sec_type == 'conclusion': write_title = False
        if sec_type == 'introduction' and ('مقدمة' in title_text or not title_text): write_title = False

        # الأسئلة الشائعة عنوانها h2 والباقي h3 داخل المحتوى
        if sec_type == 'faq':
             full_html += f"<h2>{title_text}</h2>\n"
             write_title = False
             
             # نجمع كل العناوين الموجودة عشان منكررهاش
             all_titles_in_article = [x['title'] for x in structure]
             
             # استدعاء الدالة مع تمرير العناوين
             real_questions = get_real_google_questions(keyword, existing_titles=all_titles_in_article)
             
             # نجهز البرومبت الأساسي من القاموس (القديم القوي)
             base_prompt = get_content_prompt(sec_type, title_text, keyword, synonyms)
             
             if real_questions:
                 # لو لقينا أسئلة حقيقية، نعدل البرومبت ليستخدمها
                 prompt = f"""
                 {base_prompt}
                 
                 🔥 إضافة هامة جداً:
                 لقد جلبت لك أسئلة حقيقية يسألها الناس الآن في جوجل:
                 {real_questions}
                 
                 المطلوب: ادمج هذه الأسئلة الحقيقية ضمن إجاباتك أو استبدل الأسئلة الافتراضية بها لتكون الفائدة قصوى.
                 """
                 print(f"   ✅ Using {len(real_questions.splitlines())} REAL questions.")
             else:
                 # لو مفيش أسئلة حقيقية، نستخدم البرومبت القديم زي ما هو
                 prompt = base_prompt
                 print("   ⚠️ No real questions found. Using default prompt.")
				 
        if write_title and title_text:
            if level == 'h2': full_html += f"<h2>{title_text}</h2>\n"
            elif level == 'h3': full_html += f"<h3>{title_text}</h3>\n"
        
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

        prompt = get_content_prompt(sec_type, title_text, keyword, synonyms)

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
                    model = get_gemini_model()
                    chat = model.start_chat(history=[]) 
                    
                    try: 
                        # 1. نبعت برومبت التهيئة الأساسي (عربي فصحى وغيره)
                        chat.send_message(setup_prompt)
                        
                        # 2. (الجزء الجديد) لو إحنا في قسم فرعي H3، نفكره إحنا تبع مين
                        if level == 'h3' and current_h2_context:
                            print(f"   🧠 Reminding Gemini of context: {current_h2_context}")
                            reminder = f"نحن الآن نكتب فقرة فرعية بعنوان '{title_text}' تابعة للقسم الرئيسي '{current_h2_context}'. أكمل الكتابة بناءً على هذا السياق."
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
                

                # كود التحفيز (Motivation) يبقى هنا
                if i == mid_index and sec_type != 'introduction': # تأكيد عدم وضعه في المقدمة
                    print("   -> Injecting Motivation...")
                    try:
                        mot_prompt = get_content_prompt("motivation_box", "تحفيز", keyword, synonyms)
                        res = chat.send_message(mot_prompt)
                        mot_content = clean_text_symbols(res.text.replace('```html','').replace('```',''))
                        # لا نعمل بولد للتحفيز عادة، أو نتركه كما هو
                        full_html += f"<div style='text-align:center;'>{mot_content}</div>\n<br>\n"
                        print("   ⏳ Sleeping 85s after Motivation...")
                        time.sleep(85)
                    except: pass

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
            sum_prompt = get_content_prompt("summary_box", "ملخص", keyword, synonyms)
            sum_prompt += f"\n\nالعناوين:\n{headings_text}" # نرفق العناوين هنا
            
            summary_model = get_gemini_model()
            summary_chat = summary_model.start_chat(history=[])
            
            res = summary_chat.send_message(sum_prompt)
            sum_content = clean_text_symbols(res.text.replace("```html","").replace("```",""))
            
            # تطبيق البولد الذكي
            sum_content = make_keywords_bold(sum_content, keyword, synonyms, global_bold_tracker)
                
            # 3. الحقن (مكان الكود القديم الذي سألت عنه في نقطة 3)
            if '<h2>' in full_html:
                full_html = full_html.replace('<h2>', f'{sum_content}\n<br>\n<h2>', 1)
            else:
                full_html = f"{sum_content}\n<br>\n{full_html}"
                
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

def main():
    try:
        logger.info("🚀 Starting article generation process...")
        
        auth = Auth.Token(GITHUB_TOKEN)
        g = Github(auth=auth)
        repo = g.get_repo(REPO_NAME)

        # --- بداية كود تدوير المفاتيح الذكي ---
        global CURRENT_KEY
        try:
            # 1. محاولة قراءة رقم آخر مفتاح تم استخدامه
            last_key_index = -1
            try:
                key_file = repo.get_contents("last_key_index.txt")
                last_key_index = int(key_file.decoded_content.decode("utf-8").strip())
                logger.info(f"🔄 Last used key index was: {last_key_index}")
            except:
                logger.info("ℹ️ No usage history found. Starting fresh.")

            # 2. تحديد المؤشرات المتاحة (0, 1, 2...)
            all_indices = list(range(len(GEMINI_API_KEYS)))
            
            # 3. استبعاد المفتاح الأخير (إلا لو كان هو الوحيد)
            valid_indices = [i for i in all_indices if i != last_key_index]
            if not valid_indices: valid_indices = all_indices # لو مفيش غير مفتاح واحد استخدمه وخلاص

            # 4. اختيار مفتاح جديد عشوائي من القائمة المصفاة
            new_index = random.choice(valid_indices)
            CURRENT_KEY = GEMINI_API_KEYS[new_index]
            logger.info(f"✅ Selected new key index: {new_index}")

            # 5. تحديث الملف في المستودع بالرقم الجديد
            if not TEST_MODE:
                try:
                    if last_key_index == -1:
                        repo.create_file("last_key_index.txt", "Init key history", str(new_index))
                    else:
                        repo.update_file(key_file.path, "Update key rotation", str(new_index), key_file.sha)
                except Exception as update_err:
                    logger.warning(f"⚠️ Could not update key history: {update_err}")

        except Exception as e:
            logger.error(f"⚠️ Key rotation logic failed: {e}")
            CURRENT_KEY = random.choice(GEMINI_API_KEYS) # خطة بديلة
        # --- نهاية كود تدوير المفاتيح ---

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
        
        try:
            service = get_blogger_service()
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
