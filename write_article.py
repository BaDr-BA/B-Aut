import os
import json
import random
import time
import re
from github import Github
import google.generativeai as genai
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from googletrans import Translator
import typing_extensions as typing
from github import Github, Auth
import logging

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
TEST_MODE = True # اجعله False عندما تعتمد السكريبت نهائياً

# --- الإعدادات والمفاتيح ---
GEMINI_API_KEYS = [os.environ.get(f"GEMINI_API_KEY_{i}") for i in range(1, 7) if os.environ.get(f"GEMINI_API_KEY_{i}")]
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

# ---------------------------------------------------------
# دالة المراقبة وتحديث ملف الحالة (توضع هنا لتراها كل الدوال)
# ---------------------------------------------------------
def update_status_log(message):
    """تحديث ملف status.md في المستودع لمراقبة العمل لحظة بلحظة"""
    
    # طباعة الرسالة في الكونسول دائماً للمتابعة السريعة
    print(f"📝 LOG: {message}")

    if TEST_MODE: 
        return # في وضع الاختبار نكتفي بالطباعة فقط

    try:
        # استخدام طريقة المصادقة الجديدة لتجنب التحذيرات
        from github import Auth
        auth = Auth.Token(GITHUB_TOKEN)
        g = Github(auth=auth)
        
        repo = g.get_repo(REPO_NAME)
        
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"- `{timestamp}` : {message}"

        try:
            # محاولة جلب الملف وتحديثه
            contents = repo.get_contents("status.md")
            current_log = contents.decoded_content.decode("utf-8")
            
            # نضيف السطر الجديد في البداية عشان تشوف آخر حاجة فوق
            new_log = f"{log_entry}\n{current_log}"
            
            # تحديث الملف (نقوم بقص اللوج لو زاد عن حد معين عشان ميبقاش تقيل)
            if len(new_log) > 50000: 
                new_log = new_log[:50000] + "\n... (تم حذف السجلات القديمة)"
                
            repo.update_file(contents.path, f"Status: {message}", new_log, contents.sha)
        except:
            # إذا الملف غير موجود، ننشئه
            repo.create_file("status.md", "Init status log", f"# 📊 سجل عمليات البوت\n\n{log_entry}")
            
    except Exception as e:
        print(f"⚠️ Could not update status log: {e}")


def get_blogger_service():
    creds = Credentials(None, refresh_token=REFRESH_TOKEN, token_uri="https://oauth2.googleapis.com/token", client_id=CLIENT_ID, client_secret=CLIENT_SECRET)
    return build('blogger', 'v3', credentials=creds)

def clean_json_response(text):
    """تنظيف رد Gemini لاستخراج JSON صالح"""
    text = text.replace("```json", "").replace("```", "").strip()
    return text

def create_permalink_gemini(keyword_arabic):
    """توليد رابط ثابت باستخدام Gemini لضمان عدم توقف المكتبات الخارجية"""
    try:
        model = get_gemini_model() # نستخدم نفس الموديل المهيأ
        prompt = f"""
        Act as a URL slug generator.
        Task: Translate this Arabic text "{keyword_arabic}" to English, convert to lowercase, remove special characters, and replace spaces with hyphens (-).
        Output: Just the final slug string. No explanation.
        Example Input: الربح من الانترنت
        Example Output: profit-from-internet
        """
        response = model.generate_content(prompt)
        permalink = response.text.strip().replace("\n", "").replace(" ", "")
        
        # تنظيف إضافي لضمان عدم وجود رموز غريبة
        permalink = re.sub(r'[^a-z0-9\-]', '', permalink)
        return permalink
    except Exception as e:
        print(f"⚠️ Permalink Error: {e}")
        # خطة بديلة في حال فشل Gemini نستخدم مكتبة re فقط لعمل slug عربي
        return re.sub(r'[^0-9\u0600-\u06FF]+', '-', keyword_arabic).strip('-')


def clean_text_symbols(text):
    """
    إزالة علامات الاقتباس والنجوم المزدوجة من النص المولد فقط
    مع الحفاظ على علامات الاقتباس في HTML attributes
    """
    # نستخدج regex ذكي لإزالة " و ** فقط من داخل النص وليس من HTML tags
    
    # 1. إزالة ** المزدوجة (تنسيق Bold markdown الخاطئ)
    text = text.replace('**', '')
    
    # 2. إزالة " من النص لكن ليس من HTML attributes
    # نحفظ HTML tags أولاً
    html_pattern = r'(<[^>]+>)'
    parts = re.split(html_pattern, text)
    
    cleaned_parts = []
    for i, part in enumerate(parts):
        if part.startswith('<') and part.endswith('>'):
            # هذا HTML tag - نحافظ عليه كما هو
            cleaned_parts.append(part)
        else:
            # هذا نص عادي - نزيل علامات الاقتباس منه
            # نحافظ على علامات الاقتباس التي هي جزء من كلمات عربية
            cleaned_part = part.replace('"', '').replace('"', '').replace('"', '')
            cleaned_parts.append(cleaned_part)
    
    return ''.join(cleaned_parts)

def get_gemini_model():
    """اختيار مفتاح عشوائي وموديل قوي"""
    if not GEMINI_API_KEYS:
        raise ValueError("No Gemini API keys found!")
    
    key = random.choice(GEMINI_API_KEYS)
    genai.configure(api_key=key)
    
    models_list = [
        'gemini-2.5-flash',
        'gemini-2.0-flash',
        'gemini-2.5-flash-lite',
        'gemini-2.0-flash-lite',
    ]
    selected_model = random.choice(models_list)
    print(f"🤖 Using Model: {selected_model}")
    
    return genai.GenerativeModel(selected_model, safety_settings=SAFETY_SETTINGS)

def generate_article_structure(title, keyword):
    """المرحلة 1: بناء الهيكل الهندسي للمقال"""
    model = get_gemini_model()
    
    prompt = f"""
    اريد هيكل كامل لمقال عنوانه: "{title}"
    والكلمة المفتاحية: "{keyword}"
    
    المطلوب:
    أعطني العناوين الرئيسية (H2) والعناوين الفرعية (H3) المناسبة لمقال متوافق مع معايير SEO الجديدة ونية الباحث لتصدر نتائج البحث.
    
    ⚠️ مهم جداً: تجنب تكرار نفس العنوان مرتين! كل عنوان يجب أن يكون فريداً ومختلفاً.
    
    بجانب كل عنوان، حدد:
    - level: إما "h2" أو "h3" أو "intro" (للمقدمة فقط في البداية)
    - type: نوع المحتوى من هذه القائمة حصراً: [introduction, list_bullet, list_numbered, table, faq, conclusion, text_paragraph, featured_paragraph, pros_cons, emoji_check_list]
    - title: نص العنوان (يجب أن يكون فريداً)

    يجب أن يكون الرد بصيغة JSON Array فقط، بهذا الشكل:
    [
        {{"level": "intro", "type": "introduction", "title": "مقدمة شاملة"}},
        {{"level": "h2", "type": "text_paragraph", "title": "ما هو..."}},
        {{"level": "h3", "type": "list_bullet", "title": "أهم مميزات..."}},
        {{"level": "h2", "type": "table", "title": "مقارنة بين..."}},
        ...
        {{"level": "h2", "type": "conclusion", "title": "خاتمة المقال"}}
    ]
    
    ملاحظات:
    - استخدم "intro" مرة واحدة فقط للمقدمة
    - استخدم "h2" للعناوين الرئيسية
    - استخدم "h3" للعناوين الفرعية
    - لا تكرر نفس العنوان
    """

    try:
        # التغيير: نطلب الرد كنص عادي ثم ننظفه لتجنب مشاكل الـ Schema
        response = model.generate_content(prompt)
        
        # تنظيف النص واستخراج الـ JSON
        clean_text = clean_json_response(response.text)
        structure = json.loads(clean_text)
        
        # كود التحقق من التكرار
        titles_seen = set()
        unique_structure = []
        for item in structure:
            if item['title'] not in titles_seen:
                titles_seen.add(item['title'])
                unique_structure.append(item)
            else:
                print(f"⚠️ Skipping duplicate title: {item['title']}")
        
        return unique_structure
        
    except Exception as e:

        print(f"⚠️ Failed to generate structure: {e}")
        return [
            {"level": "intro", "type": "introduction", "title": "مقدمة"},
            {"level": "h2", "type": "text_paragraph", "title": f"معلومات عن {keyword}"},
            {"level": "h2", "type": "list_bullet", "title": "أهم النقاط"},
            {"level": "h2", "type": "conclusion", "title": "خاتمة"}
        ]

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

def make_keywords_bold(text, keyword, synonyms_list=None):
    """
    جعل الكلمة المفتاحية ومرادفاتها عريضة في النص
    مع تجنب التكرار والتأكد من عدم كسر HTML
    """
    if synonyms_list is None:
        synonyms_list = get_synonyms(keyword)
    
    # ترتيب المرادفات من الأطول للأقصر (عشان نتجنب استبدال جزء من كلمة)
    synonyms_sorted = sorted(synonyms_list, key=len, reverse=True)
    
    for syn in synonyms_sorted:
        if not syn.strip() or len(syn.strip()) < 2:
            continue
        
        # تجنب الكلمات التي بالفعل داخل <b> tags
        # نبحث عن الكلمة كاملة (word boundary)
        pattern = r'(?<!<b>)(?<!<b>.)(\b' + re.escape(syn) + r'\b)(?!</b>)(?!.</b>)'
        
        # استبدال الكلمة بنفسها لكن Bold
        def replace_with_bold(match):
            return f'<b>{match.group(1)}</b>'
        
        text = re.sub(pattern, replace_with_bold, text, flags=re.IGNORECASE)
    
    # إزالة أي bold مزدوج قد يحدث
    text = re.sub(r'<b>\s*<b>(.*?)</b>\s*</b>', r'<b>\1</b>', text)
    
    return text

def get_content_prompt(section_type, section_title, keyword, synonyms_list=None):
    """اختيار البرومبت المناسب بناءً على نوع القسم"""
    
    prompts = {
        "introduction": f"""
        اكتب المطلوب مباشرة بدون أي مقدمات.
        
        المطلوب: اكتب مقدمة بعنوان "{section_title}" لنية الباحث كأن خبير بيتكلم احترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو.
        
        تكون المقدمة فقرتين:
        - الفقرة الأولى: ثلاث أسطر
        - الفقرة الثانية: ثلاث أسطر
        
        استخدم الكلمة المفتاحية الأساسية "{keyword}" وهذه المرادفات بشكل طبيعي ومتنوع: {', '.join(synonyms_list[:2]) if synonyms_list else keyword}
		⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        
        ابدأ الكتابة فوراً بدون أي مقدمات وبدون كتابة "المقدمة:" أو أي عنوان.
        """,
        
        "list_bullet": f"""
        اكتب المطلوب مباشرة بدون أي مقدمات.
        
        المطلوب: فقرة تنقيطية عن "{section_title}" موجهة لنية الباحث + كأن خبير بيتكلم احترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو:
        - تبدأ بمقدمة قصيرة (200 حرف)
        - ثم النقاط التنقيطية
        - اختم بملاحظة قصيرة (200 حرف)
        
        استخدم الكلمة المفتاحية الأساسية "{keyword}" وهذه المرادفات بشكل طبيعي ومتنوع: {', '.join(synonyms_list[:2]) if synonyms_list else keyword}
		⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        ابدأ الكتابة فوراً بدون أي مقدمات وبدون كتابة العنوان مرة أخرى.
        """,
        
        "list_numbered": f"""
        اكتب المطلوب مباشرة بدون أي مقدمات.
        
        المطلوب: قائمة مرقمة عن "{section_title}" موجهة لنية الباحث + كأن خبير بيتكلم احترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو:
        - تبدأ بمقدمة قصيرة (200 حرف)
        - القائمة المرقمة
        - اختم بملاحظة قصيرة (200 حرف)
        
        استخدم الكلمة المفتاحية الأساسية "{keyword}" وهذه المرادفات بشكل طبيعي ومتنوع: {', '.join(synonyms_list[:2]) if synonyms_list else keyword}
		⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        ابدأ الكتابة فوراً بدون أي مقدمات وبدون كتابة العنوان مرة أخرى.
        """,
        
        "table": f"""
        اكتب المطلوب مباشرة بدون أي مقدمات.
        
        انشئ جدول HTML (ياخذ الوان وخط القالب بلوجر اللي مركبه تلقائيًا) عن "{section_title}" موجهة لنية الباحث + كأن خبير بيتكلم احترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو:
        - تبدأ بمقدمة قصيرة (200 حرف)
        - ثم الجدول (متجاوب width:100%)
        - اختم بملاحظة قصيرة (200 حرف)
        - بدون CSS معقد
        - استخدم الكلمة المفتاحية "{keyword}" وهذه المرادفات بشكل طبيعي: {', '.join(synonyms_list[:4]) if synonyms_list else keyword}
        - ⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        
        ابدأ كتابة الجدول فوراً بدون أي مقدمات وبدون كتابة العنوان مرة أخرى.
        """,
        
        "faq": f"""
        اكتب المطلوب مباشرة بدون أي مقدمات.
        
        اكتب أسئلة شائعة وأجوبة عن "{section_title}" موجهة لنية الباحث + كأن خبير بيجاوب باحترافية وتشد القارئ للقراءة لنهاية الأسئلة والأجوبة وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو:
        المطلوب:
        - ابدأ بمقدمة قصيرة (200 حرف)
        - ثم من 5 إلى 25 سؤال وجواب وتكون الأسئلة من اقتراحات جوجل التلقائية (تم البحث أيضًا عن). وقسم "الناس أيضًا يسألون" (People Also Ask). وقسم أسئلة أخرى
        - كل إجابة لا تزيد عن سطرين
        - استخدم رموز ◀️ أو ⬌ بين السؤال والجواب
        
        استخدم الكلمة المفتاحية الأساسية "{keyword}" وهذه المرادفات بشكل طبيعي ومتنوع: {', '.join(synonyms_list[:4]) if synonyms_list else keyword}
		⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        ابدأ الكتابة فوراً بدون أي مقدمات وبدون كتابة العنوان مرة أخرى.
        """,
        
        "featured_paragraph": f"""
        اكتب المطلوب مباشرة بدون أي مقدمات.
        
        اكتب فقرة مميزة عن "{section_title}" موجهة لنية الباحث + كأن خبير بيتكلم احترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو:
        - بعنوان "خلاصة تجربة موقع تقنجي"
        - أسلوب شخصي دافئ (First-person perspective) سواء 'نصيحة من القلب' أو 'سر المهنة' أو 'رؤية تحليلية' أو 'تطبيق عملي' أو 'واقع السوق' أو 'تنبيه للمحترفين'  أو أي حاجة حسب الموضوع وكأنك تشارك القارئ تجربة شخصية حصرية
        - في حدود من 2 إلي 4 أسطر
        - تبرز قيمة مضافة لا يعرفها الجميع
        
        استخدم الكلمة المفتاحية الأساسية "{keyword}" وهذه المرادفات بشكل طبيعي ومتنوع: {', '.join(synonyms_list[:2]) if synonyms_list else keyword}
		⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        ابدأ الكتابة فوراً بدون أي مقدمات وبدون كتابة العنوان مرة أخرى.
        """,
        
        "pros_cons": f"""
        اكتب المطلوب مباشرة بدون أي مقدمات.
        
        اكتب مقارنة متوازنة عن "{section_title}" موجهة لنية الباحث + كأن خبير بيتكلم احترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو:
        - تبدأ بمقدمة قصيرة (200 حرف)
        - المميزات (أو ماذا تفعل) (نقاط)
        - العيوب (أوماذا تتجنب) (نقاط)
        - اختم بملاحظة قصيرة (200 حرف) تلخص وجهة نظرك كخبير
        
        استخدم الكلمة المفتاحية الأساسية "{keyword}" وهذه المرادفات بشكل طبيعي ومتنوع: {', '.join(synonyms_list[:4]) if synonyms_list else keyword}
		⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        ابدأ الكتابة فوراً بدون أي مقدمات وبدون كتابة العنوان مرة أخرى.
        """,
        
        "emoji_check_list": f"""
        اكتب المطلوب مباشرة بدون أي مقدمات.
        
        اكتب قائمة إيموجية (✅ و ❌) مباشرة عن "{section_title}" موجهة لنية الباحث + كأن خبير بيتكلم احترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو:
        - تبدأ بمقدمة قصيرة (200 حرف)
        - النقاط بالإيموجي
        - اختم بملاحظة قصيرة (200 حرف)
        
        استخدم الكلمة المفتاحية الأساسية "{keyword}" وهذه المرادفات بشكل طبيعي ومتنوع: {', '.join(synonyms_list[:2]) if synonyms_list else keyword}
		⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        ابدأ الكتابة فوراً بدون أي مقدمات وبدون كتابة العنوان مرة أخرى.
        """,
        
        "conclusion": f"""
        اكتب المطلوب مباشرة بدون أي مقدمات.
        
        اكتب خاتمة شاملة وموجهة لنية الباحث + كأن خبير بيختم عن "{section_title}" احترافية وتشد القارئ بإسلوب لا واعي علي تصفح الموقع لقراءة الكثير من المواضيع الأخرى وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو:
        - تلخص المقال كاملاً
        - في حدود من 2 إلى 4 أسطر
        - تشجع أيضاً على التعليق والمشاركة بإسلوب لا واعي
        
        استخدم الكلمة المفتاحية الأساسية "{keyword}" وهذه المرادفات بشكل طبيعي ومتنوع: {', '.join(synonyms_list[:2]) if synonyms_list else keyword}
		⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        ابدأ الكتابة فوراً بدون أي مقدمات وبدون "الخاتمة:" أو عناوين.
        """,
        
        "text_paragraph": f"""
        اكتب المطلوب مباشرة بدون أي مقدمات.
        
        اكتب فقرة أو فقرات عن "{section_title}" موجهة لنية الباحث + كأن خبير بيتكلم احترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو:
        - في حدود 1-3 فقرات
        - كل فقرة 3 أسطر بحد أقصى
        - مسافة بسيطة بين الفقرات
        
        استخدم الكلمة المفتاحية الأساسية "{keyword}" وهذه المرادفات بشكل طبيعي ومتنوع: {', '.join(synonyms_list[:2]) if synonyms_list else keyword}
		⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        ابدأ الكتابة فوراً بدون أي مقدمات وبدون كتابة العنوان مرة أخرى.
        """,
        
        "summary_box": f"""
        اكتب المطلوب مباشرة بدون أي مقدمات.
        
        اكتب ملخص سريع مباشر موجهة لنية الباحث + كأن خبير بيتكلم احترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو:
        - عنوان جذاب لـ "خلاصة سريعة"
        - ابدأ بجملة ترحيبية تشرح أن هذا هو ملخص ما سيجده الباحث أو القارئ
        - ملخص للمقال بالكامل
        - نقاط مركزة جداً
        - اجعل الأسلوب يبدو كأن خبيراً يتحدث لصديقه ليوفر عليه الوقت
        - داخل div بخلفية مناسبة
        
        استخدم الكلمة المفتاحية الأساسية "{keyword}" وهذه المرادفات بشكل طبيعي ومتنوع: {', '.join(synonyms_list[:3]) if synonyms_list else keyword}
		⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        ابدأ الكتابة فوراً بدون أي مقدمات وبدون كتابة العنوان مرة أخرى.
        """,
        
        "motivation_box": f"""
        اكتب المطلوب مباشرة بدون أي مقدمات.
        
        اكتب فقرة تحفيزية قصيرة لا تتجاوز سطرين احترافية وفضولية ومشوقة.
        - أسلوب بشري جذاب بعيداً عن الصيغ البيعية المكررة
        - تشجع على إكمال القراءة
        
        استخدم الكلمة المفتاحية الأساسية "{keyword}" وهذه المرادفات بشكل طبيعي ومتنوع: {', '.join(synonyms_list[:1]) if synonyms_list else keyword}
		⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        ابدأ فوراً في الكتابة بدون أي مقدمات.
        """
    }
    
    base_prompt = prompts.get(section_type, prompts["text_paragraph"])
    
    # إضافة تعليمات نهائية موحدة
    base_prompt += """
    
    ⚠️ تعليمات مهمة:
    1. لا تكتب عناوين إضافية أو مقدمات قبل المحتوى
    2. ابدأ مباشرة بالمحتوى المطلوب
    3. لا تستخدم "المقدمة:" أو "الخاتمة:" أو أي عناوين
    4. اكتب بأسلوب بشري طبيعي ومباشر وموجه لنية الباحث
    """
    
    return base_prompt

def write_full_article(article_data):
    """المرحلة 2 & 3: التهيئة والتنفيذ بجلسة واحدة"""
    title = article_data['title']
    keyword = article_data['keyword']
    meta_description = article_data.get('meta_description', '')
    
    print(f"🏗️ Generating structure for: {title}")
    structure = generate_article_structure(title, keyword)

    # توليد المرادفات مرة واحدة في البداية
    print(f"🔍 Generating synonyms for keyword: {keyword}")
    synonyms = get_synonyms(keyword)
    print(f"   ✅ Synonyms: {', '.join(synonyms[:5])}{'...' if len(synonyms) > 5 else ''}")

    # إنشاء الرابط الثابت
    permalink = create_permalink_gemini(keyword)
    
    # بداية المقال بمعلومات Meta
    full_html = f"""
    <!-- ===== معلومات SEO للنسخ واللصق =====
    الرابط الثابت المخصص: {permalink}
    وصف البحث (Meta Description): {meta_description}
    الكلمة المفتاحية: {keyword}
    المرادفات: {', '.join(synonyms[:10])}
    ========================================= -->

    """
    
    # بدء جلسة الشات
    model = get_gemini_model()
    chat = model.start_chat(history=[])
    
    # تهيئة الأسلوب
    try:
        setup_prompt = f"""
        أنت كاتب وخبير في صناعة المحتوي الكتابي المتوافق مع معايير السيو الجديدة وخبير متخصص في السيو الجديد.
        
        قواعد الكتابة:
        1. اكتب أي إجابة في هذه المحادثة من البداية إلى النهاية بالعربية الفصحى البسيطة
        2. أسلوب بشري طبيعي جديد وحصري واحترافي ومميز
        3. استخدم "{keyword}" ومرادفاتها طبيعياً
        4. ابدأ الكتابة مباشرة بدون مقدمات أو عناوين إضافية
        5. لا تكرر العناوين
        6. لا تستخدم علامات ** أو علامات اقتباس مزدوجة "" في أي نص
        
        مهم جداً: عندما أطلب منك كتابة محتوى، اكتبه مباشرة بدون أي مقدمات.
        """
        chat.send_message(setup_prompt)
        time.sleep(15)
    except Exception as e:
        print(f"⚠️ Setup warning: {e}")
    
    mid_index = len(structure) // 2
    
    # المرور على الأقسام
    for i, section in enumerate(structure):
        level = section.get('level', 'h2')
        title_text = section.get('title', '')
        sec_type = section.get('type', 'text_paragraph')
        
        # كتابة العنوان
        if level == 'h2':
            full_html += f"<h2>{title_text}</h2>\n"
        elif level == 'h3':
            full_html += f"<h3>{title_text}</h3>\n"
        
        # طلب المحتوى
        prompt = get_content_prompt(sec_type, title_text, keyword, synonyms)
        prompt += "\n\nأعطني المحتوى بصيغة HTML فقط (p, ul, li, table...) بدون ```html"
        
        success = False
        retries = 0
        max_retries = 5
        
        while not success and retries < max_retries:
            try:
                print(f"   - Writing section: {title_text}...")
                response = chat.send_message(prompt)
                content = response.text.replace("```html", "").replace("```", "").strip()
                
                # تنظيف النص من الرموز غير المرغوبة
                content = clean_text_symbols(content)
                
                # جعل الكلمات المفتاحية ومرادفاتها عريضة
                content = make_keywords_bold(content, keyword, synonyms)
                
                # التحقق من أن المحتوى ليس فارغاً
                if len(content.strip()) < 50:
                    print(f"   ⚠️ Content too short, retrying...")
                    retries += 1
                    time.sleep(20)
                    continue
                
                full_html += content + "\n<br>\n"
                print(f"   ✅ Done.")
                success = True
                
                # الإضافات المحشورة
                if sec_type == 'introduction':
                    print("   -> Injecting Summary Box...")
                    summary_prompt = get_content_prompt("summary_box", "ملخص سريع", keyword, synonyms)
                    summary_prompt += "\n\nأعطني المحتوى بصيغة HTML فقط بدون ```html"
                    
                    sum_retries = 0
                    sum_success = False
                    while not sum_success and sum_retries < max_retries:
                        try:
                            resp_sum = chat.send_message(summary_prompt)
                            clean_sum = resp_sum.text.replace("```html", "").replace("```", "").strip()
                            clean_sum = clean_text_symbols(clean_sum)
                            clean_sum = make_keywords_bold(clean_sum, keyword, synonyms)
                            full_html += clean_sum + "\n<br>\n"
                            sum_success = True
                            time.sleep(30)
                        except Exception as e:
                            if "429" in str(e) or "quota" in str(e).lower():
                                sum_retries += 1
                                wait_time = 40 + (sum_retries * 10)
                                print(f"   ⚠️ Summary quota hit! Waiting {wait_time}s... ({sum_retries}/{max_retries})")
                                time.sleep(wait_time)
                            else:
                                print(f"   ❌ Summary error: {e}")
                                break

                if i == mid_index:
                    print("   -> Injecting Motivation Box...")
                    mot_prompt = get_content_prompt("motivation_box", "تحفيز القراءة", keyword, synonyms)
                    mot_prompt += "\n\nأعطني المحتوى بصيغة HTML فقط بدون ```html"
                    
                    mot_retries = 0
                    mot_success = False
                    while not mot_success and mot_retries < max_retries:
                        try:
                            resp_mot = chat.send_message(mot_prompt)
                            clean_mot = resp_mot.text.replace("```html", "").replace("```", "").strip()
                            clean_mot = clean_text_symbols(clean_mot)
                            clean_mot = make_keywords_bold(clean_mot, keyword, synonyms)
                            full_html += f"<div style='text-align:center; margin: 20px 0;'>{clean_mot}</div>\n<br>\n"
                            mot_success = True
                            time.sleep(30)
                        except Exception as e:
                            if "429" in str(e) or "quota" in str(e).lower():
                                mot_retries += 1
                                wait_time = 40 + (mot_retries * 10)
                                print(f"   ⚠️ Motivation quota hit! Waiting {wait_time}s... ({mot_retries}/{max_retries})")
                                time.sleep(wait_time)
                            else:
                                print(f"   ❌ Motivation error: {e}")
                                break
                
                # انتظار متغير بناءً على عدد المحاولات
                wait_time = 40 + (retries * 10)  # يبدأ من 40 ويزيد تدريجياً
                time.sleep(wait_time)
            
            except Exception as e:
                if "429" in str(e) or "quota" in str(e).lower():
                    retries += 1
                    wait_time = 40 + (retries * 15)
                    print(f"   ⚠️ Quota hit! Waiting {wait_time}s before retry {retries}/{max_retries}...")
                    time.sleep(wait_time)
                    
                    if retries == 3:
                        print("   🔄 Switching to new model...")
                        model = get_gemini_model()
                        chat = model.start_chat(history=[])
                        try:
                            chat.send_message(setup_prompt)
                            time.sleep(10)
                        except:
                            pass
                else:
                    print(f"   ❌ Error: {e}")
                    full_html += f"<p><i>⚠️ [خطأ في توليد هذا القسم: {title_text}]</i></p>\n"
                    break

    return full_html

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
            logger.error(f"❌ Error publishing to Blogger: {e}")
            
            # نقل الملف الفاشل
            if not TEST_MODE:
                try:
                    failed_content = selected_file.decoded_content.decode("utf-8")
                    failed_path = f"failed_plans/{selected_file.name}"
                    repo.create_file(failed_path, f"Move failed plan: {selected_file.name}", failed_content)
                    repo.delete_file(selected_file.path, f"Remove failed plan: {selected_file.name}", selected_file.sha)
                    logger.warning(f"⚠️ Moved {selected_file.name} to 'failed_plans' directory for inspection.")
                except Exception as move_error:
                    logger.error(f"⚠️ Could not move failed file: {move_error}")

    except Exception as e:
        logger.error(f"❌ Critical error in main(): {e}", exc_info=True)
        raise  # مهم! عشان GitHub Actions يعرف إن فيه خطأ

if __name__ == "__main__":
    main()
