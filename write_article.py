import os
import json
import random
import time
import re
import logging
from github import Github, Auth
from groq import Groq
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

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
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
CLIENT_ID = os.environ.get("BLOGGER_CLIENT_ID")
CLIENT_SECRET = os.environ.get("BLOGGER_CLIENT_SECRET")
REFRESH_TOKEN = os.environ.get("BLOGGER_REFRESH_TOKEN")
BLOG_ID = os.environ.get("BLOGGER_BLOG_ID")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPO_NAME = "BaDr-BA/B-Aut"
PLANS_DIR = "plans"

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

def ask_groq(messages, json_mode=False):
    """دالة مركزية للاتصال بـ Llama 3.3 عبر Groq"""
    if not GROQ_API_KEY:
        raise ValueError("❌ No GROQ_API_KEY found!")

    client = Groq(api_key=GROQ_API_KEY)
    model_id = "llama-3.3-70b-versatile" 

    for attempt in range(3):
        try:
            chat_completion = client.chat.completions.create(
                messages=messages,
                model=model_id,
                temperature=0.7,
                response_format={"type": "json_object"} if json_mode else None
            )
            return chat_completion.choices[0].message.content
        except Exception as e:
            if "429" in str(e): 
                print(f"⚠️ Groq Rate Limit. Waiting 20s...")
                time.sleep(20)
            else:
                print(f"⚠️ Groq Error: {e}")
                time.sleep(5)
    
    raise Exception("❌ Failed to get response from Groq.")

def format_headings_style(html_content):
    """تحويل النقطتين : إلى مسافة وعمود ¦ في العناوين H1-H4 فقط"""
    def replace_colon(match):
        return f"{match.group(1)}{match.group(2).replace(':', ' ¦')}{match.group(3)}"
    
    return re.sub(r'(<h[1-4][^>]*>)(.*?)(</h[1-4]>)', replace_colon, html_content, flags=re.DOTALL | re.IGNORECASE)

def clean_json_response(text):
    """تنظيف رد Gemini لاستخراج JSON صالح"""
    text = text.replace("```json", "").replace("```", "").strip()
    return text

def create_permalink_gemini(keyword_arabic):
    """توليد رابط ثابت بالإنجليزية باستخدام Llama"""
    try:
        messages = [
            {"role": "system", "content": "You are a translator."},
            {"role": "user", "content": f"Translate '{keyword_arabic}' to English slug (e.g. profit-from-internet). Output ONLY the slug."}
        ]
        slug = ask_groq(messages)
        slug = re.sub(r'[^a-z0-9\-]', '', slug.strip().lower())
        return slug if len(slug) > 2 else "article"
    except:
        return re.sub(r'[^0-9\u0600-\u06FF]+', '-', keyword_arabic).strip('-')

def clean_text_symbols(text):
    """
    إزالة علامات الاقتباس والنجوم المزدوجة وكود keyword_strong المزعج
    """
    # 1. تنظيف كود القالب المزعج (keyword_strong) واستبداله بـ bold عادي
    text = re.sub(r'<strong[^>]*id=["\']keyword_strong["\'][^>]*>', '<b>', text)
    
    # 2. إزالة ** المزدوجة
    text = text.replace('**', '')
    
    # 3. إزالة " من النص لكن ليس من HTML attributes
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
    
    try:
        response = ask_groq([{"role": "user", "content": prompt}], json_mode=True)
        structure = json.loads(response)
        # تصحيح لو الرد جه داخل مفتاح
        if isinstance(structure, dict):
            keys = list(structure.keys())
            if keys: structure = structure[keys[0]]
            
        return structure
    except Exception as e:
        print(f"Structure Error: {e}")
        raise Exception("❌ Failed to generate structure.")

def get_synonyms(keyword):
    """
    توليد مرادفات للكلمة المفتاحية تلقائياً باستخدام Groq
    """
    try:
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
        response = ask_groq([{"role": "user", "content": prompt}], json_mode=True)
        synonyms = json.loads(response)
        if isinstance(synonyms, dict): synonyms = list(synonyms.values())[0]
        return synonyms[:70]
    except:
        return [keyword]

def make_keywords_bold(text, keyword, synonyms_list, global_tracker=None):
    """
    تغميق الكلمات المفتاحية بذكاء لتقليل الحشو (SEO 2026).
    القاعدة: الكلمة الرئيسية مرة واحدة في المقال، والمرادفات بحد أقصى مرة واحدة لكل نوع.
    """
    if synonyms_list is None: synonyms_list = []
    if global_tracker is None: global_tracker = set() # للأمان لو لم يمرر
    
    # تجهيز القائمة: الكلمة الأساسية + المرادفات
    all_terms = [keyword] + synonyms_list
    # ترتيب من الأطول للأقصر
    all_terms = sorted(list(set([t.strip() for t in all_terms if t.strip()])), key=len, reverse=True)
    
    tokens = re.split(r'(<[^>]+>)', text)
    processed_tokens = []
    is_inside_bold = False
    
    # تتبع البولد داخل "هذا النص المرسل فقط" (Local Tracker) لمنع تلوين الفقرة كلها
    local_bold_count = 0 
    
    for token in tokens:
        if not token: continue
        
        # لو تاج HTML
        if token.startswith('<'):
            processed_tokens.append(token)
            if '<b>' in token.lower() or '<strong>' in token.lower(): is_inside_bold = True
            elif '</b>' in token.lower() or '</strong>' in token.lower(): is_inside_bold = False
        else:
            # لو نص عادي
            if is_inside_bold:
                processed_tokens.append(token)
            else:
                # لو وصلنا للحد الأقصى في هذا البلوك (مثلاً 2 بولد في الفقرة الواحدة كفاية جداً)
                if local_bold_count >= 2:
                    processed_tokens.append(token)
                    continue

                temp_text = token
                # نلف على الكلمات
                for term in all_terms:
                    if local_bold_count >= 2: break # كفاية في الفقرة دي
                    
                    # الشرط القاتل: لو الكلمة دي اتعملت بولد قبل كده في المقال كله، انساها
                    if term in global_tracker: continue
                    if len(term) < 2: continue
                    
                    # بحث واستبدال آمن (Word Boundary)
                    pattern = r'(?<![\w\u0600-\u06FF])' + re.escape(term) + r'(?![\w\u0600-\u06FF])'
                    
                    if re.search(pattern, temp_text, flags=re.IGNORECASE):
                        # استبدال أول ظهور فقط في هذا التوكن
                        temp_text = re.sub(pattern, f'<b>{term}</b>', temp_text, count=1, flags=re.IGNORECASE)
                        global_tracker.add(term) # سجل إننا حرقنا الكلمة دي خلاص
                        local_bold_count += 1
                
                processed_tokens.append(temp_text)

    return ''.join(processed_tokens)

def get_content_prompt(section_type, section_title, keyword, synonyms_list=None):
    """اختيار البرومبت المناسب مع مرادفات عشوائية"""
    
    # اختيار 2 مرادفات عشوائية لضمان التنوع في كل فقرة
    current_synonyms = []
    if synonyms_list:
        # نختار عدد عشوائي بحد أقصى 2، أو كل القائمة لو أقل من 2
        current_synonyms = random.sample(synonyms_list, min(len(synonyms_list), 2))
    
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

        المحتوى: ابدأ بمشكلة (يشد اللي متألم فعلًا) أو  بحقيقة صادمة (تخض وتخلّي القارئ يكمل) أو بسؤال مباشر (يشغّل دماغه) أو بجملة قصيرة تقيلة (أسلوب صاعق) أو بمشهد أو قصة (يشد عاطفيًا) أو بكسر معتقد شائع أو... أي هدف حسب ما في رأيك ثم قدم الحل الذي في الموضوع.

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
        
        اكتب أسئلة شائعة وأجوبة عن "{section_title}" موجهة لنية الباحث + كأن خبير بيجاوب باحترافية وتشد القارئ للقراءة لنهاية الأسئلة والأجوبة وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو:
        المطلوب:
        - ابدأ بمقدمة قصيرة تمهد للأسئلة والأجوبة (200 حرف)
        - ثم من 5 إلى 25 سؤال وجواب وتكون الأسئلة من اقتراحات جوجل التلقائية (تم البحث أيضًا عن). وقسم "الناس أيضًا يسألون" (People Also Ask). وقسم أسئلة أخرى
        - كل إجابة لا تزيد عن سطرين
        - استخدم رموز ◀️ أو ⬌ بين السؤال والجواب
        
        استخدم الكلمة المفتاحية الأساسية "{keyword}" وهذه المرادفات بشكل طبيعي ومتنوع: {syns_str}
		⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        
        """,
        
        "featured_paragraph": f"""
        {strict_instructions}
        
        اكتب فقرة مميزة عن "{section_title}" موجهة لنية الباحث + كأن خبير بيتكلم احترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو:
        - بعنوان "خلاصة تجربة أو خبرة موقع تقنجي"
        - أسلوب شخصي دافئ (First-person perspective) سواء 'نصيحة من القلب' أو 'سر المهنة' أو 'رؤية تحليلية' أو 'تطبيق عملي' أو 'واقع السوق' أو 'تنبيه للمحترفين'  أو أي حاجة حسب الموضوع وكأنك تشارك القارئ تجربة شخصية حصرية
        - في حدود من 2 إلي 4 أسطر
        - تبرز قيمة مضافة لا يعرفها الجميع
        
        استخدم الكلمة المفتاحية الأساسية "{keyword}" وهذه المرادفات بشكل طبيعي ومتنوع: {syns_str}
		⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        
        """,
        
        "pros_cons": f"""
        {strict_instructions}
        
        اكتب مقارنة متوازنة عن "{section_title}" موجهة لنية الباحث + كأن خبير بيتكلم احترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو:
        - تبدأ بمقدمة قصيرة تمهد للمقارنة المتوازنة (200 حرف)
        - المميزات (أو ماذا تفعل) (نقاط)
        - العيوب (أوماذا تتجنب) (نقاط)
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
        - في حدود من 2 إلى 4 أسطر
		- الدعوة لاتخاذ إجراء (Call to Action)
        - تشجع على التعليق والمشاركة بإسلوب لا واعي وحثه على قراءة المزيد من المواضيع ذات صلة
        
        استخدم الكلمة المفتاحية الأساسية "{keyword}" وهذه المرادفات بشكل طبيعي ومتنوع: {syns_str}
		⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        ابدأ الكتابة فوراً بدون أي مقدمات وبدون "الخاتمة:" أو عناوين.
        """,
        
        "text_paragraph": f"""
        {strict_instructions}
        
        اكتب فقرة أو فقرات عن "{section_title}" موجهة لنية الباحث + كأن خبير بيتكلم احترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو:
        - في حدود 1-3 فقرات
        - كل فقرة 3 أسطر بحد أقصى
        - مسافة بسيطة بين الفقرات
        
        استخدم الكلمة المفتاحية الأساسية "{keyword}" وهذه المرادفات بشكل طبيعي ومتنوع: {syns_str}
		⚠️ مهم: وزّع هذه الكلمات في المحتوى بشكل طبيعي وغير متكلف لتحسين SEO الجديد.
        
        """,
        
        "summary_box": f"""
        {strict_instructions}
        
        اكتب ملخص سريع مباشر للمقال التالي (سأزودك به) موجهة لنية الباحث + كأن خبير بيتكلم احترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو:
        - عنوان جذاب وشيق وفضولي لـ "خلاصة سريعة" مع اضافة الكلمة المفتاحية هذه "{keyword}" وضعه داخل وسم <h2> حصراً
        - ابدأ بجملة ترحيبية تشرح أن هذا هو ملخص ما سيجده الباحث أو القارئ
        - ملخص للمقال بالكامل
        - نقاط مركزة جداً
        - اجعل الأسلوب يبدو كأن خبيراً يتحدث لصديقه ليوفر عليه الوقت
        - داخل div بخلفية #bb3b17 أو #faad2a أو ما بينهم
        
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

    # --- التعديل: إعادة ترتيب الهيكل (محتوى -> أسئلة -> خاتمة) ---
    body_sec = []
    faq_sec = []
    conc_sec = []
    
    for item in original_structure:
        t = item['type'].lower()
        ti = item['title'].lower()
        if 'faq' in t or 'أسئلة' in ti: faq_sec.append(item)
        elif 'conclusion' in t or 'خاتمة' in ti:
            item['type'] = 'conclusion'; item['title'] = 'خاتمة'; conc_sec.append(item)
        else: body_sec.append(item)
        
    structure = body_sec + faq_sec + conc_sec

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

    # --- السيستم برومبت الجديد (يتضمن الهدف) ---
    system_prompt = f"""
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

    messages_history = [{"role": "system", "content": system_prompt}]
	
    mid_index = len(structure) // 2
    
    # 3. المرور على الأقسام ببطء شديد
    for i, section in enumerate(structure):
        level = section.get('level', 'h2')
        title_text = section.get('title', '')
        sec_type = section.get('type', 'text_paragraph')
        
        # إضافة العناوين HTML (إلا لو كانت خاتمة أو مقدمة بدون عنوان صريح)
        write_title = True
        if sec_type == 'conclusion': write_title = False
        if sec_type == 'introduction' and ('مقدمة' in title_text or not title_text): write_title = False

        # الأسئلة الشائعة عنوانها h2 والباقي h3 داخل المحتوى
        if sec_type == 'faq':
             full_html += f"<h2>{title_text}</h2>\n"
             write_title = False # عشان منكررش العنوان
		
        if write_title and title_text:
            if level == 'h2': full_html += f"<h2>{title_text}</h2>\n"
            elif level == 'h3': full_html += f"<h3>{title_text}</h3>\n"
        
        # تجهيز البرومبت
        prompt = get_content_prompt(sec_type, title_text, keyword, synonyms)
        prompt += "\n\nأعطني المحتوى بصيغة HTML فقط (p, ul, li, table...) بدون ```html"
        
        # إضافة الطلب للسجل
        messages_history.append({"role": "user", "content": prompt})
        
        try:
            print(f"   ✍️ Writing: {title_text} ({sec_type})...")
            
            # الكتابة
            content = ask_groq(messages_history)
            
            # حفظ الرد في السجل
            messages_history.append({"role": "assistant", "content": content})

            # تنظيف
            content = content.replace("```html", "").replace("```", "").strip()
            content = clean_text_symbols(content)
                
            # استخدام دالة البولد الجديدة مع التراكر
            content = make_keywords_bold(content, keyword, synonyms, global_bold_tracker)
                
            if len(content) < 50: raise Exception("Content too short")
                
            full_html += content
                
            # الفاصل (نتأكد أنه ليس الأخير وليس قبل الخاتمة مباشرة إذا كانت بدون عنوان)
            if i < len(structure) - 1:
                full_html += "\n<br>\n"
                
            success = True
            print(f"   ✅ Done.")
                
            print("   ⏳ Sleeping 5s to avoid Quota limit...")
            time.sleep(5) 
                

            # كود التحفيز (Motivation) يبقى هنا
            if i == mid_index and sec_type != 'introduction': # تأكيد عدم وضعه في المقدمة
                print("   -> Injecting Motivation...")
                try:
                    mot_prompt = get_content_prompt("motivation_box", "تحفيز", keyword, synonyms)
                    mot_res = ask_groq([{"role": "user", "content": mot_prompt}])
                    mot_content = clean_text_symbols(mot_res.replace('```html','').replace('```',''))
                    # لا نعمل بولد للتحفيز عادة، أو نتركه كما هو
                    full_html += f"<div style='text-align:center;'>{mot_content}</div>\n<br>\n"
                    print("   ⏳ Sleeping 2s after Motivation...")
                    time.sleep(2)
                except: pass

        except Exception as e:
            print(f"   ⚠️ Error: {e}")
            full_html += f"<p style='color:red; text-align:center;'><i>⚠️ تعذر توليد ({sec_type})</i></p>\n"

    # --- الملخص ---
    print("   📝 Generating Summary...")
    try:
        # تجهيز البرومبت مع سياق من المقال (أول 15000 حرف)
        sum_prompt = get_content_prompt("summary_box", "ملخص", keyword, synonyms)
        sum_prompt += f"\n\nلخص النص التالي:\n{full_html[:15000]}..."
        sum_res = ask_groq([{"role": "user", "content": sum_prompt}])
            
        sum_content = clean_text_symbols(clean_json_response(sum_res))
        sum_content = make_keywords_bold(sum_content, keyword, synonyms, global_bold_tracker)
            
        # حقن الملخص في المكان المناسب
        if '<h2>' in full_html:
            full_html = full_html.replace('<h2>', f'{sum_content}\n<br>\n<h2>', 1)
        else:
            # لو مفيش عناوين، نحشره بعد المقدمة يدوياً
            parts = full_html.split('<br>', 4)
            if len(parts) >= 4:
                parts.insert(3, f'\n{sum_content}\n')
                full_html = '<br>'.join(parts)
            else:
                full_html += sum_content
            
        print("   ✅ Summary injected.")
		
    except Exception as e:
        print(f"   ⚠️ Summary failed: {e}")

    return format_headings_style(full_html)

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
