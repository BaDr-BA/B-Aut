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
    # محاولة إصلاح الأخطاء الشائعة في JSON إذا وجدت
    return text

def create_permalink(keyword_english):
    """تجهيز الرابط الثابت: حروف صغيرة واستبدال المسافات بشرط"""
    return re.sub(r'[^a-z0-9]+', '-', keyword_english.lower()).strip('-')

def get_gemini_model():
    """اختيار مفتاح عشوائي وموديل قوي"""
    key = random.choice(GEMINI_API_KEYS)
    genai.configure(api_key=key)
    # نستخدم Pro لأنه الأذكى في فهم الهيكل والتعليمات المعقدة
    # قائمة الموديلات التي تريدها (رتبها كما تحب)
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
    أعطني العناوين الفرعية (H2) والعناوين الأصغر (H3) المناسبة لمقال متوافق مع معايير SEO الجديدة ونية الباحث لتصدر نتائج البحث.
    بجانب كل عنوان، حدد "نوع المحتوى" الأنسب له من هذه القائمة حصراً:
    [introduction, list_bullet, list_numbered, table, faq, conclusion, text_paragraph, advice_box, pros_cons, emoji_check_list]

    يجب أن يكون الرد بصيغة JSON Array فقط، بهذا الشكل:
    [
        {{"type": "introduction", "title": "مقدمة"}},
        {{"type": "text_paragraph", "title": "ما هو..."}},
        {{"type": "list_bullet", "title": "أهم مميزات..."}},
        {{"type": "table", "title": "مقارنة بين..."}},
        ...
        {{"type": "conclusion", "title": "خاتمة"}}
    ]
    لا تضف أي نص خارج الـ JSON.
    """
    
    try:
        response = model.generate_content(prompt)
        structure = json.loads(clean_json_response(response.text))
        return structure
    except Exception as e:
        print(f"⚠️ Failed to generate structure: {e}")
        # هيكل احتياطي بسيط في حال الفشل
        return [
            {"type": "introduction", "title": "مقدمة"},
            {"type": "text_paragraph", "title": f"معلومات عن {keyword}"},
            {"type": "list_bullet", "title": "أهم النقاط"},
            {"type": "conclusion", "title": "خاتمة"}
        ]

def get_content_prompt(section_type, section_title, keyword):
    """اختيار البرومبت المناسب بناءً على نوع القسم"""
    
    prompts = {
        "introduction": f"""
        اكتب لي مقدمة لمقال بعنوان ({section_title}) لنية الباحث كأن خبير بيتكلم احترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو وضمن فيها الكلمة المفتاحية المستهدفة ({keyword}) وتكون المقدمة فقرتين الاولي ثلاث اسطر والثانية ثلاث اسطر.
        """,
        
        "list_bullet": f"""
        اكتب لي فقرة تنقيطية لعنوان ({section_title}) لنية الباحث وأيضًا كأن خبير بيتكلم باحترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو تكون اولها مقدمة 200 حرف وتحط النقاط وفي نهايتها ملاحظة 200 حرف مع مرادفات اخرى للكلمة المفتاحية المستهدفة الأساسية ({keyword}) بشكل طبيعي غير متكلف.
        """,
        
        "list_numbered": f"""
        اكتب لي فقرة مرقمة لعنوان ({section_title}) لنية الباحث وأيضًا كأن خبير بيتكلم باحترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو تكون اولها مقدمة 200 حرف وتحط الترقيم وفي نهايتها ملاحظة 200 حرف مع مرادفات اخرى للكلمة المفتاحية المستهدفة الأساسية ({keyword}) بشكل طبيعي غير متكلف.
        """,
        
        "table": f"""
        انشئ لي جدول بتنسيق HTML بسيط ومتجاوب (width:100%) لعنوان ({section_title}) لنية الباحث مع مرادفات اخرى للكلمة المفتاحية المستهدفة الأساسية ({keyword}) بشكل طبيعي غير متكلف.
        اجعل الجدول يأخذ الوان وخط القالب بلوجر اللي مركبه تلقائيًا (بدون CSS معقد inline).
        """,
        
        "faq": f"""
        اكتب لي فقرة 'الأسئلة الشائعة' لعنوان ({section_title}) لنية الباحث تتضمن من 3 إلى 20 سؤال حسب ما يجري البحث عنها من اقتراحات جوجل التلقائية (تم البحث أيضًا عن). قسم "الناس أيضًا يسألون" (People Also Ask). قسم أسئلة أخرى مع مرادفات اخرى للكلمة المفتاحية المستهدفة الأساسية ({keyword}) بشكل طبيعي غير متكلف.
        ابدأ بمقدمة بشرية بسيطة (200 حرف) تشجع القارئ على الفهم، ثم تحتها اطرح السؤال ثم رمز ◀️ أو ⬌ ثم إجابة مركزة لا تزيد عن سطرين لكل سؤال.
        """,
        
        "advice_box": f"""
        اكتب لي فقرة مميزة بعنوان "خلاصة تجربة موقع تقنجي" حول ({section_title}) لنية الباحث مع مرادفات اخرى للكلمة المفتاحية المستهدفة الأساسية ({keyword}) بشكل طبيعي غير متكلف
        أريدك أن تكتبها بأسلوب شخصي دافئ (First-person perspective)  و'نصيحة من القلب' أو 'سر المهنة' أو 'رؤية تحليلية' أو 'تطبيق عملي' أو 'واقع السوق' أو 'تنبيه للمحترفين' حسب الموضوع وكأنك تشارك القارئ تجربة شخصية حصرية
        الفقرة في حدود (4) أسطر، وتبرز قيمة مضافة لا يعرفها الجميع مع مراعاة معايير.
        """,
        
        "pros_cons": f"""
        اكتب لي فقرة مقارنة متوازنة بناءً على موضوع ({section_title}) لنية الباحث مع مرادفات اخرى للكلمة المفتاحية المستهدفة الأساسية ({keyword}) بشكل طبيعي غير متكلف
        ابدأ بمقدمة بسيطة (200 حرف) توضح أهمية الموازنة قبل اتخاذ القرار
        ثم اذكر المميزات في نقاط والعيوب في نقاط أخرى (أو ماذا تفعل وماذا تتجنب)
        واختم بملاحظة قصيرة (200 حرف) تلخص وجهة نظرك كخبير.
        """,
        
        "emoji_check_list": f"""
        اكتب لي فقرة ايموجية (✅ و ❌) عن ({section_title}) لنية الباحث لنية الباحث وأيضًا كأن خبير بيتكلم باحترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو تكون اولها مقدمة 200 حرف وتحط النقاط وفي نهايتها ملاحظة 200 حرف مع مرادفات اخرى للكلمة المفتاحية المستهدفة الأساسية ({keyword}) بشكل طبيعي غير متكلف.
        """,
        
        "conclusion": f"""
        اكتب لي خاتمة كأن خبير بيتكلم احترافية وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو تلخص المقال كاملا الذي يتكلم عن ({section_title}) لنية الباحث مع مرادفات اخرى للكلمة المفتاحية المستهدفة الأساسية ({keyword}) بشكل طبيعي غير متكلف ولا تزيد عدد كلمات الخاتمة عن ثلاث اسطر مع تشد القارئ للتعليق ومشاركة المقالة باسلوب لا وعي وانه يشوف المزيد من المقالات.
        """,
        
        "text_paragraph": f"""
        اكتب لي فقرة او فقرتين او ثلاث فقرات كتابية عادية عن ({section_title}) لنية الباحث كأن خبير بيتكلم احترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو أي فقرة (فقرة / فقرتين / ثلاث فقرات) يجب ان تكون ثلاث اسطر فقط ولا تزيد الفقرة عن الثلاث اسطر ويكون في مسافة بسيطة (لو كتبت عن فقرتين او ثلاث فقرات) بين كل فقرة والاخري مع مرادفات اخرى للكلمة المفتاحية المستهدفة الأساسية ({keyword}) بشكل طبيعي غير متكلف.
        """,
        
        "summary_box": f"""
        اكتب لي عنوان جذاب وفقرة بعنوان "خلاصة سريعة" تلخص المقال لكل الموضوع اللي تكلمنا عنه لنية الباحث مع مرادف اخر للكلمة المفتاحية المستهدفة الأساسية ({keyword}) بشكل طبيعي غير متكلف.
        ابدأ بجملة ترحيبية تشرح أن هذا هو ملخص ما سيجده القارئ، ثم ضع كل النقاط مركزة جداً تعبر عن أهم فوائد المقال.
        اجعل الأسلوب كأن خبيراً يكلم صديقه ليوفر وقته.
        نسقها داخل div بخلفية تاخذ الوان قالبي بلوجر تلقائي.
        """,
        
        "motivation_box": f"""
        اكتب فقرة قصيرة جداً (سطرين) احترافية وفضولية ومشوقة لتحفيز القارئ على إكمال القراءة.
        أسلوب بشري جذاب بعيد عن البيع.
        """
    }
    
    return prompts.get(section_type, prompts["text_paragraph"])

def write_full_article(article_data):
    """المرحلة 2 & 3: التهيئة والتنفيذ بجلسة واحدة"""
    title = article_data['title']
    keyword = article_data['keyword']
    
    print(f"🏗️ Generating structure for: {title}")
    structure = generate_article_structure(title, keyword)
    
    # بدء جلسة الشات
    model = get_gemini_model()
    chat = model.start_chat(history=[])
    
    # 1. تهيئة الأسلوب (System Instruction via Chat) + تعليمات الـ Bold
    try:
        setup_prompt = """
        بما انك كاتب وخبير في صناعة المحتوي الكتابي المتوافق مع معايير السيو الجديدة اريد
        ان تعطيني اي اجابة في هذه المحادثة باللهجة الفصحى (البسيطة) والكلام بطريقة
        بشرية في كل اجابة او رد منك علي في هذه المحادثة من البداية الي النهاية وان
        امكن ترد بطريقة البشر وكتابة الفقرات والاجابة علي طلباتي ايضا تجيب عليها
        بطريقة بشرية باسلوب جديد احترافي وحصري ومميز وبلهجة الفصحى البسيطة.
        """
        # إضافة شرط الـ Bold للبرومبت
        setup_prompt += f"\n ملاحظة هامة جداً: أي ذكر للكلمة المفتاحية '{keyword}' في أي نص تكتبه، اجعلها عريضة (Bold) بوضعها بين وسمي <b> و </b> هكذا: <b>{keyword}</b>."
        chat.send_message(setup_prompt)
        time.sleep(10)  # انتظار 10 ثواني بعد التهيئة
    except Exception as e:
        print(f"⚠️ Setup warning: {e}")
    
    full_html = ""
    
    # حساب نقطة المنتصف لإضافة الفقرة التحفيزية
    mid_index = len(structure) // 2
    
    # 2. المرور على الأقسام وكتابتها
    for i, section in enumerate(structure):
        title_text = section.get('title', '')   # نص العنوان
        sec_type = section.get('type', 'text')  # نوع المحتوى
        
        # أ) كتابة العنوان في HTML (ما عدا المقدمة والخاتمة لا نكتب لها عنوان منفصل)
        # لأن المحتوى نفسه سيحتوي على العنوان
        if sec_type not in ['introduction', 'conclusion']:
            full_html += f"<h2>{title_text}</h2>\n"
        
        # ب) طلب المحتوى من Gemini
        prompt = get_content_prompt(sec_type, title_text, keyword)
        # إضافة تذكير دائم بـ HTML
        prompt += "\n" + "اجعل الإجابة بصيغة HTML tags فقط (p, ul, li, table...) بدون تغليفها بـ ```html"
        
        # --- نظام المحاولات الذكي لتجنب خطأ 429 ---
        success = False
        retries = 0
        while not success and retries < 3:
            try:
                print(f"   - Writing section: {title_text}...")
                response = chat.send_message(prompt)
                content = response.text.replace("```html", "").replace("```", "").strip()
            
                # إضافة المحتوى للمقال
                full_html += content + "\n<br>\n"
                print(f"   ✅ Done.")
                success = True
                
                # --- الإضافات المحشورة (Injections) ---
                
                # 1. إذا كان القسم هو "intro" (المقدمة) -> نضيف تحته الخلاصة السريعة فوراً
                if sec_type == 'introduction':
                    print("   -> Injecting Summary Box...")
                    summary_prompt = get_content_prompt("summary_box", "ملخص سريع", keyword)
                    summary_prompt += "\n" + "اجعل الإجابة بصيغة HTML tags فقط (p, ul, li, div...) بدون تغليفها بـ ```html"
                    resp_sum = chat.send_message(summary_prompt)
                    clean_sum = resp_sum.text.replace("```html", "").replace("```", "").strip()
                    full_html += clean_sum + "\n<br>\n"
                    time.sleep(25)

                # 2. إذا وصلنا لمنتصف المقال -> نضيف الفقرة التحفيزية
                if i == mid_index:
                    print("   -> Injecting Motivation Box...")
                    mot_prompt = get_content_prompt("motivation_box", "تحفيز القراءة", keyword)
                    mot_prompt += "\n" + "اجعل الإجابة بصيغة HTML tags فقط (p, div...) بدون تغليفها بـ ```html"
                    resp_mot = chat.send_message(mot_prompt)
                    clean_mot = resp_mot.text.replace("```html", "").replace("```", "").strip()
                    # تنسيق بسيط لتمييزها
                    full_html += f"<div style='text-align:center; margin: 20px 0;'>{clean_mot}</div>\n<br>\n"
                    time.sleep(25)
                
                # أهم سطر: الانتظار 25 ثانية بين كل فقرة وفقرة لتجنب الحظر
                time.sleep(25)
            
            except Exception as e:
                if "429" in str(e):
                    print(f"   ⚠️ Quota hit! Sleeping for 30 seconds before retry {retries+1}/3...")
                    time.sleep(35) # انتظار طويل إذا اكتشف أن الكوتا انتهت
                    retries += 1
                else:
                    print(f"   ❌ Error: {e}")
                    break # خطأ آخر غير الكوتا، توقف عن المحاولة في هذه الفقرة

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
    
    # تجهيز الرابط (اختياري)
    eng_keyword = article.get('translated_keyword', article['keyword']) 
    permalink_slug = create_permalink(eng_keyword)

    # النشر على بلوجر
    try:
        service = get_blogger_service()
        category_name = selected_file.name.replace("content_plan_", "").replace(".json", "").replace("_", " ")
        
        post_data = {
            "kind": "blogger#post",
            "blog": {"id": BLOG_ID},
            "title": article['title'],
            "content": post_body,
            "labels": [category_name]
        }
        
        # محاولة تعيين الوصف
        if 'meta_description' in article:
            # الوصف لا يُدعم مباشرة في الـ insert العادي في بعض نسخ API القديمة،
            # لكنه مدعوم في النسخ الحديثة كـ 'searchDescription' ولكن قد يحتاج صلاحيات admin.
            # سنجرب وضعه، إذا لم يعمل لن يوقف السكريبت.
            pass 

        # نشر المقالة كمسودة (isDraft=True)
        service.posts().insert(blogId=BLOG_ID, body=post_data, isDraft=True).execute()
        print(f"✅ Published draft: {article['title']}")

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
