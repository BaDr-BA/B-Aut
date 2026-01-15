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
    'gemini-3-flash',    
    'gemini-2.5-flash',    
    'gemini-2.5-flash-lite',    
    'gemini-2.5-flash-tts',    
    'gemini-1.5-pro-latest',
    'gemini-1.5-flash-latest',
    'gemini-pro',
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
        اكتب لي فقرة باستخدام الايموجي (✅ و ❌) لتوضيح الصحيح والخاطئ حول ({section_title}).
        ابدأ بمقدمة قصيرة، ثم القائمة، ثم نصيحة ختامية.
        """,
        
        "conclusion": f"""
        اكتب لي خاتمة كأن خبير بيتكلم احترافية وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو تلخص المقال كاملا الذي يتكلم عن ({section_title}) لنية الباحث مع مرادفات اخرى للكلمة المفتاحية المستهدفة الأساسية ({keyword}) بشكل طبيعي غير متكلف ولا تزيد عدد كلمات الخاتمة عن ثلاث اسطر مع تشد القارئ للتعليق ومشاركة المقالة باسلوب لا وعي وانه يشوف المزيد من المقالات.
        """,
        
        "text_paragraph": f"""
        اكتب لي فقرة او فقرتين او ثلاث فقرات كتابية عادية عن ({section_title}) لنية الباحث كأن خبير بيتكلم احترافية وتشد القارئ لنهاية المقال وفضولية ومشوقة وجذابة ومتوافقة مع معايير السيو أي فقرة (فقرة / فقرتين / ثلاث فقرات) يجب ان تكون ثلاث اسطر فقط ولا تزيد الفقرة عن الثلاث اسطر ويكون في مسافة بسيطة (لو كتبت عن فقرتين او ثلاث فقرات) بين كل فقرة والاخري مع مرادفات اخرى للكلمة المفتاحية المستهدفة الأساسية ({keyword}) بشكل طبيعي غير متكلف.
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
    
    # 1. تهيئة الأسلوب (System Instruction via Chat)
    setup_prompt = """
    بما انك كاتب وخبير في صناعة المحتوي الكتابي المتوافق مع معايير السيو الجديدة اريد
    ان تعطيني اي اجابة في هذه المحادثة باللهجة الفصحى (البسيطة) والكلام بطريقة
    بشرية في كل اجابة او رد منك علي في هذه المحادثة من البداية الي النهاية وان
    امكن ترد بطريقة البشر وكتابة الفقرات والاجابة علي طلباتي ايضا تجيب عليها
    بطريقة بشرية باسلوب جديد احترافي وحصري ومميز وبلهجة الفصحى البسيطة.
    """
    chat.send_message(setup_prompt)
    
    full_html = ""
    
    # 2. المرور على الأقسام وكتابتها
    for section in structure:
        sec_type = section.get('type', 'text_paragraph')
        sec_title = section.get('title', 'عنوان فرعي')
        
        # تخطي المقدمة والخاتمة من وضع H2 لأنهم لا يحتاجون عنوان ظاهر عادة، أو حسب رغبتك
        # هنا سأضع العنوان لكل شيء ما عدا المقدمة إذا أردت
        if sec_type != 'introduction':
            full_html += f"<h2>{sec_title}</h2>\n"
            
        prompt = get_content_prompt(sec_type, sec_title, keyword)
        
        # إضافة تعليمات التنسيق HTML للبرومبت
        prompt += "\n" + "اجعل الإجابة بصيغة HTML tags فقط (p, ul, li, table...) بدون تغليفها بـ ```html"
        
        try:
            response = chat.send_message(prompt)
            content = response.text.replace("```html", "").replace("```", "").strip()
            full_html += content + "\n<br>\n" # مسافة بين الأقسام
            print(f"   - Wrote section: {sec_title} ({sec_type})")
            time.sleep(2) # راحة بسيطة لتجنب الضغط
        except Exception as e:
            print(f"   ⚠️ Error writing section {sec_title}: {e}")

    return full_html

def main():
    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(REPO_NAME)
    
    # اختيار خطة
    plan_files = [f for f in repo.get_contents(PLANS_DIR) if f.name.endswith(".json")]
    if not plan_files: return

    selected_file = random.choice(plan_files)
    content_json = json.loads(selected_file.decoded_content.decode("utf-8"))
    
    if not content_json: return

    article = content_json[0]
    
    # توليد المحتوى
    post_body = write_full_article(article)
    
    # تجهيز الرابط (Permalink)
    # ملاحظة: إذا لم يكن لديك حقل 'translated_keyword' في الـ JSON، سنستخدم الكلمة العادية مؤقتاً
    # أو يمكنك طلب ترجمتها من Gemini في خطوة منفصلة. هنا سأفترض وجودها أو استخدام الكلمة الأصلية.
    eng_keyword = article.get('translated_keyword', article['keyword']) 
    permalink_slug = create_permalink(eng_keyword)

    # النشر
    try:
        service = get_blogger_service()
        category_name = selected_file.name.replace("content_plan_", "").replace(".json", "").replace("_", " ")
        
        post_data = {
            "kind": "blogger#post",
            "blog": {"id": BLOG_ID},
            "title": article['title'],
            "content": post_body,
            "labels": [category_name],
            # ملاحظة: بلوجر لا يسمح بتحديد الرابط المخصص عبر API إلا في حالات خاصة،
            # لكن يمكننا المحاولة أو الاعتماد على العنوان.
            # الحقل المخصص للرابط هو 'customMetaData' في بعض النسخ أو يتم توليده من العنوان.
            "status": "DRAFT"
        }
        
        # محاولة تعيين الوصف
        if 'meta_description' in article:
            # الوصف لا يُدعم مباشرة في الـ insert العادي في بعض نسخ API القديمة،
            # لكنه مدعوم في النسخ الحديثة كـ 'searchDescription' ولكن قد يحتاج صلاحيات admin.
            # سنجرب وضعه، إذا لم يعمل لن يوقف السكريبت.
            pass 

        service.posts().insert(blogId=BLOG_ID, body=post_data).execute()
        print(f"✅ Published draft: {article['title']}")
        
        # تحديث الخطة
        new_plan = content_json[1:]
        repo.update_file(selected_file.path, f"Published: {article['title']}", json.dumps(new_plan, indent=2, ensure_ascii=False), selected_file.sha)
        
        # تحديث سجل العناوين المنشورة
        try:
            pub_file = repo.get_contents("published_titles.txt")
            new_pub = pub_file.decoded_content.decode("utf-8") + "\n" + article['title']
            repo.update_file("published_titles.txt", "Update log", new_pub, pub_file.sha)
        except:
            repo.create_file("published_titles.txt", "Create log", article['title'])

    except Exception as e:
        print(f"❌ Error publishing: {e}")

if __name__ == "__main__":
    main()
