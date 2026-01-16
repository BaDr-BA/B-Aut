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

def get_blogger_service():
    creds = Credentials(None, refresh_token=REFRESH_TOKEN, token_uri="https://oauth2.googleapis.com/token", client_id=CLIENT_ID, client_secret=CLIENT_SECRET)
    return build('blogger', 'v3', credentials=creds)

def clean_json_response(text):
    """تنظيف رد Gemini لاستخراج JSON صالح"""
    text = text.replace("```json", "").replace("```", "").strip()
    return text

def translate_to_english(text):
    """ترجمة النص إلى الإنجليزية"""
    try:
        translator = Translator()
        translated = translator.translate(text, src='ar', dest='en')
        return translated.text
    except Exception as e:
        print(f"⚠️ Translation error: {e}")
        # في حالة فشل الترجمة، نستخدم النص العربي
        return text

def create_permalink(keyword_arabic):
    """تجهيز الرابط الثابت: ترجمة للإنجليزية، حروف صغيرة واستبدال المسافات بشرط"""
    # ترجمة الكلمة المفتاحية للإنجليزية
    keyword_english = translate_to_english(keyword_arabic)
    # تحويل لحروف صغيرة واستبدال المسافات والرموز بشرطة
    permalink = re.sub(r'[^a-z0-9]+', '-', keyword_english.lower()).strip('-')
    return permalink

def get_gemini_model():
    """اختيار مفتاح عشوائي وموديل قوي"""
    if not GEMINI_API_KEYS:
        raise ValueError("No Gemini API keys found!")
    
    key = random.choice(GEMINI_API_KEYS)
    genai.configure(api_key=key)
    
    # قائمة الموديلات المتاحة
    models_list = [
        'gemini-3-pro-preview',    
        'deep-research-pro-preview-12-2025',    
        'gemini-2.5-pro',    
        'gemini-3-flash-preview',    
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
    بجانب كل عنوان، حدد:
    - level: إما "h2" أو "h3" أو "intro" (للمقدمة)
    - type: نوع المحتوى من هذه القائمة حصراً: [introduction, list_bullet, list_numbered, table, faq, conclusion, text_paragraph, advice_box, pros_cons, emoji_check_list]
    - title: نص العنوان

    يجب أن يكون الرد بصيغة JSON Array فقط، بهذا الشكل:
    [
        {{"level": "intro", "type": "introduction", "title": "مقدمة شاملة"}},
        {{"level": "h2", "type": "text_paragraph", "title": "ما هو..."}},
        {{"level": "h3", "type": "list_bullet", "title": "أهم مميزات..."}},
        {{"level": "h2", "type": "table", "title": "مقارنة بين..."}},
        ...
        {{"level": "h2", "type": "conclusion", "title": "خاتمة المقال"}}
    ]
    
    ملاحظات مهمة:
    - استخدم "intro" فقط للمقدمة في بداية المقال
    - استخدم "h2" للعناوين الرئيسية
    - استخدم "h3" للعناوين الفرعية تحت h2
    - لا تضف أي نص خارج الـ JSON
    """
    
    try:
        response = model.generate_content(prompt)
        structure = json.loads(clean_json_response(response.text))
        return structure
    except Exception as e:
        print(f"⚠️ Failed to generate structure: {e}")
        # هيكل احتياطي بسيط في حال الفشل
        return [
            {"level": "intro", "type": "introduction", "title": "مقدمة"},
            {"level": "h2", "type": "text_paragraph", "title": f"معلومات عن {keyword}"},
            {"level": "h2", "type": "list_bullet", "title": "أهم النقاط"},
            {"level": "h2", "type": "conclusion", "title": "خاتمة"}
        ]

def get_content_prompt(section_type, section_title, keyword):
    """اختيار البرومبت المناسب بناءً على نوع القسم"""
    
    prompts = {
        "introduction": f"""
        اكتب لي مقدمة لمقال بعنوان ({section_title}) لنية الباحث كأن خبير بيتكلم احترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو وضمن فيها الكلمة المفتاحية المستهدفة ({keyword}) ومرادفاتها بشكل طبيعي وتكون المقدمة فقرتين الاولي ثلاث اسطر والثانية ثلاث اسطر.
        """,
        
        "list_bullet": f"""
        اكتب لي فقرة تنقيطية لعنوان ({section_title}) لنية الباحث وأيضًا كأن خبير بيتكلم باحترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو تكون اولها مقدمة 200 حرف وتحط النقاط وفي نهايتها ملاحظة 200 حرف مع الكلمة المفتاحية المستهدفة الأساسية ({keyword}) ومرادفاتها بشكل طبيعي غير متكلف.
        """,
        
        "list_numbered": f"""
        اكتب لي فقرة مرقمة لعنوان ({section_title}) لنية الباحث وأيضًا كأن خبير بيتكلم باحترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو تكون اولها مقدمة 200 حرف وتحط الترقيم وفي نهايتها ملاحظة 200 حرف مع الكلمة المفتاحية المستهدفة الأساسية ({keyword}) ومرادفاتها بشكل طبيعي غير متكلف.
        """,
        
        "table": f"""
        انشئ لي جدول بتنسيق HTML بسيط ومتجاوب (width:100%) لعنوان ({section_title}) لنية الباحث مع الكلمة المفتاحية المستهدفة الأساسية ({keyword}) ومرادفاتها بشكل طبيعي غير متكلف.
        اجعل الجدول يأخذ الوان وخط القالب بلوجر اللي مركبه تلقائيًا (بدون CSS معقد inline).
        """,
        
        "faq": f"""
        اكتب لي فقرة 'الأسئلة الشائعة' لعنوان ({section_title}) لنية الباحث تتضمن من 5 إلى 15 سؤال حسب ما يجري البحث عنها من اقتراحات جوجل التلقائية (تم البحث أيضًا عن). قسم "الناس أيضًا يسألون" (People Also Ask). قسم أسئلة أخرى مع الكلمة المفتاحية المستهدفة الأساسية ({keyword}) ومرادفاتها بشكل طبيعي غير متكلف.
        ابدأ بمقدمة بشرية بسيطة (200 حرف) تشجع القارئ على الفهم، ثم تحتها اطرح السؤال ثم رمز ◀️ أو ⬌ ثم إجابة مركزة لا تزيد عن سطرين لكل سؤال.
        """,
        
        "advice_box": f"""
        اكتب لي فقرة مميزة بعنوان "خلاصة تجربة موقع تقنجي" حول ({section_title}) لنية الباحث مع الكلمة المفتاحية المستهدفة الأساسية ({keyword}) ومرادفاتها بشكل طبيعي غير متكلف
        أريدك أن تكتبها بأسلوب شخصي دافئ (First-person perspective) و'نصيحة من القلب' أو 'سر المهنة' أو 'رؤية تحليلية' أو 'تطبيق عملي' أو 'واقع السوق' أو 'تنبيه للمحترفين' حسب الموضوع وكأنك تشارك القارئ تجربة شخصية حصرية
        الفقرة في حدود (4) أسطر، وتبرز قيمة مضافة لا يعرفها الجميع مع مراعاة معايير.
        """,
        
        "pros_cons": f"""
        اكتب لي فقرة مقارنة متوازنة بناءً على موضوع ({section_title}) لنية الباحث مع الكلمة المفتاحية المستهدفة الأساسية ({keyword}) ومرادفاتها بشكل طبيعي غير متكلف
        ابدأ بمقدمة بسيطة (200 حرف) توضح أهمية الموازنة قبل اتخاذ القرار
        ثم اذكر المميزات في نقاط والعيوب في نقاط أخرى (أو ماذا تفعل وماذا تتجنب)
        واختم بملاحظة قصيرة (200 حرف) تلخص وجهة نظرك كخبير.
        """,
        
        "emoji_check_list": f"""
        اكتب لي فقرة ايموجية (✅ و ❌) عن ({section_title}) لنية الباحث وأيضًا كأن خبير بيتكلم باحترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو تكون اولها مقدمة 200 حرف وتحط النقاط وفي نهايتها ملاحظة 200 حرف مع الكلمة المفتاحية المستهدفة الأساسية ({keyword}) ومرادفاتها بشكل طبيعي غير متكلف.
        """,
        
        "conclusion": f"""
        اكتب لي خاتمة كأن خبير بيتكلم احترافية وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو تلخص المقال كاملا الذي يتكلم عن ({section_title}) لنية الباحث مع الكلمة المفتاحية المستهدفة الأساسية ({keyword}) ومرادفاتها بشكل طبيعي غير متكلف ولا تزيد عدد كلمات الخاتمة عن ثلاث اسطر مع تشد القارئ للتعليق ومشاركة المقالة باسلوب لا وعي وانه يشوف المزيد من المقالات.
        """,
        
        "text_paragraph": f"""
        اكتب لي فقرة او فقرتين او ثلاث فقرات كتابية عادية عن ({section_title}) لنية الباحث كأن خبير بيتكلم احترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو أي فقرة (فقرة / فقرتين / ثلاث فقرات) يجب ان تكون ثلاث اسطر فقط ولا تزيد الفقرة عن الثلاث اسطر ويكون في مسافة بسيطة (لو كتبت عن فقرتين او ثلاث فقرات) بين كل فقرة والاخري مع الكلمة المفتاحية المستهدفة الأساسية ({keyword}) ومرادفاتها بشكل طبيعي غير متكلف.
        """,
        
        "summary_box": f"""
        اكتب لي عنوان جذاب وفقرة بعنوان "خلاصة سريعة" تلخص المقال لكل الموضوع اللي تكلمنا عنه لنية الباحث مع الكلمة المفتاحية المستهدفة الأساسية ({keyword}) ومرادفاتها بشكل طبيعي غير متكلف.
        ابدأ بجملة ترحيبية تشرح أن هذا هو ملخص ما سيجده القارئ، ثم ضع كل النقاط مركزة جداً تعبر عن أهم فوائد المقال.
        اجعل الأسلوب كأن خبيراً يكلم صديقه ليوفر وقته.
        نسقها داخل div بخلفية تاخذ الوان قالبي بلوجر تلقائي.
        """,
        
        "motivation_box": f"""
        اكتب فقرة قصيرة جداً (سطرين) احترافية وفضولية ومشوقة لتحفيز القارئ على إكمال القراءة.
        أسلوب بشري جذاب بعيد عن البيع. استخدم الكلمة المفتاحية ({keyword}) أو مرادفاتها بشكل طبيعي.
        """
    }
    
    return prompts.get(section_type, prompts["text_paragraph"])

def make_keywords_bold(text, keyword):
    """جعل الكلمة المفتاحية ومرادفاتها عريضة في النص"""
    # قائمة المرادفات المحتملة (يمكن توسيعها)
    synonyms = [
        keyword,
        # يمكنك إضافة مرادفات يدوياً هنا أو استخدام API للمرادفات
    ]
    
    for syn in synonyms:
        # استبدال الكلمة بنفسها لكن بوسوم bold (مع الحفاظ على الحالة)
        pattern = re.compile(re.escape(syn), re.IGNORECASE)
        text = pattern.sub(f"<b>{syn}</b>", text)
    
    return text

def write_full_article(article_data):
    """المرحلة 2 & 3: التهيئة والتنفيذ بجلسة واحدة"""
    title = article_data['title']
    keyword = article_data['keyword']
    
    print(f"🏗️ Generating structure for: {title}")
    structure = generate_article_structure(title, keyword)
    
    # بدء جلسة الشات
    model = get_gemini_model()
    chat = model.start_chat(history=[])
    
    # 1. تهيئة الأسلوب (System Instruction via Chat)
    try:
        setup_prompt = f"""
        بما انك كاتب وخبير في صناعة المحتوي الكتابي المتوافق مع معايير السيو الجديدة اريد
        ان تعطيني اي اجابة في هذه المحادثة باللهجة الفصحى (البسيطة) والكلام بطريقة
        بشرية في كل اجابة او رد منك علي في هذه المحادثة من البداية الي النهاية وان
        امكن ترد بطريقة البشر وكتابة الفقرات والاجابة علي طلباتي ايضا تجيب عليها
        بطريقة بشرية باسلوب جديد احترافي وحصري ومميز وبلهجة الفصحى البسيطة.
        
        ملاحظة هامة: استخدم الكلمة المفتاحية '{keyword}' ومرادفاتها بشكل طبيعي في المحتوى.
        """
        chat.send_message(setup_prompt)
        time.sleep(10)
    except Exception as e:
        print(f"⚠️ Setup warning: {e}")
    
    full_html = ""
    
    # حساب نقطة المنتصف لإضافة الفقرة التحفيزية
    mid_index = len(structure) // 2
    
    # 2. المرور على الأقسام وكتابتها
    for i, section in enumerate(structure):
        level = section.get('level', 'h2')
        title_text = section.get('title', '')
        sec_type = section.get('type', 'text_paragraph')
        
        # أ) كتابة العنوان في HTML
        if level == 'h2':
            full_html += f"<h2>{title_text}</h2>\n"
        elif level == 'h3':
            full_html += f"<h3>{title_text}</h3>\n"
        # المقدمة (intro) لا نكتب لها عنوان منفصل
        
        # ب) طلب المحتوى من Gemini
        prompt = get_content_prompt(sec_type, title_text, keyword)
        prompt += "\n" + "اجعل الإجابة بصيغة HTML tags فقط (p, ul, li, table...) بدون تغليفها بـ ```html"
        
        # --- نظام المحاولات الذكي لتجنب خطأ 429 ---
        success = False
        retries = 0
        max_retries = 5  # زيادة عدد المحاولات
        
        while not success and retries < max_retries:
            try:
                print(f"   - Writing section: {title_text}...")
                response = chat.send_message(prompt)
                content = response.text.replace("```html", "").replace("```", "").strip()
                
                # جعل الكلمات المفتاحية عريضة
                content = make_keywords_bold(content, keyword)
                
                # إضافة المحتوى للمقال
                full_html += content + "\n<br>\n"
                print(f"   ✅ Done.")
                success = True
                
                # --- الإضافات المحشورة (Injections) ---
                
                # 1. إذا كان القسم هو المقدمة -> نضيف تحته الخلاصة السريعة فوراً
                if sec_type == 'introduction':
                    print("   -> Injecting Summary Box...")
                    summary_prompt = get_content_prompt("summary_box", "ملخص سريع", keyword)
                    summary_prompt += "\n" + "اجعل الإجابة بصيغة HTML tags فقط (p, ul, li, div...) بدون تغليفها بـ ```html"
                    
                    sum_retries = 0
                    sum_success = False
                    while not sum_success and sum_retries < max_retries:
                        try:
                            resp_sum = chat.send_message(summary_prompt)
                            clean_sum = resp_sum.text.replace("```html", "").replace("```", "").strip()
                            clean_sum = make_keywords_bold(clean_sum, keyword)
                            full_html += clean_sum + "\n<br>\n"
                            sum_success = True
                            time.sleep(30)
                        except Exception as e:
                            if "429" in str(e) or "quota" in str(e).lower():
                                sum_retries += 1
                                wait_time = 40 + (sum_retries * 10)
                                print(f"   ⚠️ Summary quota hit! Waiting {wait_time}s... (retry {sum_retries}/{max_retries})")
                                time.sleep(wait_time)
                            else:
                                print(f"   ❌ Summary error: {e}")
                                break

                # 2. إذا وصلنا لمنتصف المقال -> نضيف الفقرة التحفيزية
                if i == mid_index:
                    print("   -> Injecting Motivation Box...")
                    mot_prompt = get_content_prompt("motivation_box", "تحفيز القراءة", keyword)
                    mot_prompt += "\n" + "اجعل الإجابة بصيغة HTML tags فقط (p, div...) بدون تغليفها بـ ```html"
                    
                    mot_retries = 0
                    mot_success = False
                    while not mot_success and mot_retries < max_retries:
                        try:
                            resp_mot = chat.send_message(mot_prompt)
                            clean_mot = resp_mot.text.replace("```html", "").replace("```", "").strip()
                            clean_mot = make_keywords_bold(clean_mot, keyword)
                            full_html += f"<div style='text-align:center; margin: 20px 0;'>{clean_mot}</div>\n<br>\n"
                            mot_success = True
                            time.sleep(30)
                        except Exception as e:
                            if "429" in str(e) or "quota" in str(e).lower():
                                mot_retries += 1
                                wait_time = 40 + (mot_retries * 10)
                                print(f"   ⚠️ Motivation quota hit! Waiting {wait_time}s... (retry {mot_retries}/{max_retries})")
                                time.sleep(wait_time)
                            else:
                                print(f"   ❌ Motivation error: {e}")
                                break
                
                # الانتظار بين الفقرات
                time.sleep(30)
            
            except Exception as e:
                if "429" in str(e) or "quota" in str(e).lower():
                    retries += 1
                    # زيادة وقت الانتظار تدريجياً مع كل محاولة
                    wait_time = 40 + (retries * 15)
                    print(f"   ⚠️ Quota hit! Waiting {wait_time}s before retry {retries}/{max_retries}...")
                    time.sleep(wait_time)
                    
                    # بعد 3 محاولات فاشلة، نغير الموديل
                    if retries == 3:
                        print("   🔄 Switching to new model...")
                        model = get_gemini_model()
                        chat = model.start_chat(history=[])
                        # إعادة التهيئة
                        try:
                            chat.send_message(setup_prompt)
                            time.sleep(10)
                        except:
                            pass
                else:
                    print(f"   ❌ Error: {e}")
                    # في حالة خطأ آخر غير الكوتا، نضيف ملاحظة ونكمل
                    full_html += f"<p><i>⚠️ [خطأ في توليد هذا القسم]</i></p>\n"
                    break

    return full_html

def main():
    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(REPO_NAME)
    
    # اختيار ملف خطة
    plan_files = [f for f in repo.get_contents(PLANS_DIR) if f.name.endswith(".json")]
    if not plan_files:
        print("No content plans found.")
        return

    selected_file = random.choice(plan_files)
    print(f"📂 Selected plan: {selected_file.name}")
    
    content_json = json.loads(selected_file.decoded_content.decode("utf-8"))
    
    if not content_json:
        print("Plan is empty.")
        return

    article = content_json[0]
    
    # توليد المحتوى
    post_body = write_full_article(article)
    
    # تجهيز الرابط الثابت
    permalink_slug = create_permalink(article['keyword'])
    print(f"🔗 Generated permalink: {permalink_slug}")
    
    # تجهيز الوصف
    meta_description = article.get('meta_description', '')

    # النشر على بلوجر
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
        
        # إضافة الرابط الثابت المخصص
        if permalink_slug:
            post_data["url"] = f"https://www.yoursite.com/{permalink_slug}.html"
        
        # نشر المقالة كمسودة (isDraft=True)
        result = service.posts().insert(blogId=BLOG_ID, body=post_data, isDraft=True).execute()
        print(f"✅ Published draft: {article['title']}")
        
        # محاولة تحديث الوصف والرابط الثابت بعد النشر
        post_id = result['id']
        
        # تحديث المسودة بالوصف والرابط الثابت
        try:
            patch_data = {}
            
            # إضافة الرابط الثابت
            if permalink_slug:
                # في Blogger، الرابط الثابت المخصص يتم تعيينه عبر حقل 'url'
                # لكن يجب أن يكون بصيغة معينة
                patch_data["url"] = permalink_slug
            
            # إضافة وصف البحث - Blogger يستخدم customMetaData
            if meta_description:
                patch_data["customMetaData"] = meta_description
            
            if patch_data:
                service.posts().patch(
                    blogId=BLOG_ID,
                    postId=post_id,
                    body=patch_data
                ).execute()
                print(f"✅ Updated permalink and meta description")
        except Exception as e:
            print(f"⚠️ Could not update permalink/description: {e}")
            print(f"📝 Meta Description: {meta_description}")
            print(f"🔗 Permalink: {permalink_slug}")

        # --- التحكم في الحذف (شرط التجربة) ---
        if not TEST_MODE:
            # 1. تحديث ملف الخطة (حذف المقال)
            new_plan = content_json[1:]
            updated_content = json.dumps(new_plan, indent=2, ensure_ascii=False)
            repo.update_file(selected_file.path, f"Published: {article['title']}", updated_content, selected_file.sha)
            print("🗑️ Removed article from plan.")

            # 2. تحديث سجل العناوين المنشورة (published_titles.txt)
            try:
                pub_file = repo.get_contents("published_titles.txt")
                new_pub_content = pub_file.decoded_content.decode("utf-8") + "\n" + article['title']
                repo.update_file("published_titles.txt", "Add published title", new_pub_content, pub_file.sha)
            except:
                # إذا الملف غير موجود ننشئه
                repo.create_file("published_titles.txt", "Create published list", article['title'])
        else:
            print("⚠️ TEST MODE ENABLED: Article was NOT removed from the plan & NOT added to published list.")

    except Exception as e:
        print(f"❌ Error publishing to Blogger: {e}")

if __name__ == "__main__":
    main()
