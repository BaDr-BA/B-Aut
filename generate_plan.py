import os
import json
import random
import time
from github import Github, UnknownObjectException
import google.generativeai as genai

# --- الإعدادات الأساسية (عدّل هنا فقط) ---

# 1. قائمة مفاتيح Gemini API
GEMINI_API_KEYS = [
    os.environ.get("GEMINI_API_KEY_1"),
    os.environ.get("GEMINI_API_KEY_2"),
    os.environ.get("GEMINI_API_KEY_3"),
    os.environ.get("GEMINI_API_KEY_4"),
    os.environ.get("GEMINI_API_KEY_5"),
    os.environ.get("GEMINI_API_KEY_6"),
]
GEMINI_API_KEYS = [key for key in GEMINI_API_KEYS if key]

# 2. مفتاح GitHub Token
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")

# 3. إعدادات مستودع GitHub
GITHUB_REPO_NAME = "BaDr-BA/B-Aut"  #  مثال: "Badr-BA/my-blog-automation"

# 4. أقسام مدونتك
# <<! مهم جدًا !>> لإضافة قسم جديد في المستقبل، فقط أضف سطرًا جديدًا هنا.
BLOG_CATEGORIES = [
    "أدوات AI",
    "شروحات AI",
    "ربح من AI",
    "برومبتات AI",
    "أتمتة AI",
]

# 5. قائمة نماذج Gemini (مرتبة من الأقوى للأقدم + نماذج مستقبلية)
GEMINI_MODELS = [
    'gemini-3-flash',    
    'gemini-2.5-flash',    
    'gemini-2.5-flash-lite',    
    'gemini-2.5-flash-tts',    
    'gemini-1.5-pro-latest',
    'gemini-1.5-flash-latest',
    'gemini-pro',
]

# 6. المسار الذي سيتم حفظ الخطط فيه داخل مستودع GitHub
PLANS_DIRECTORY = "plans"
PUBLISHED_TITLES_FILE_PATH = "published_titles.txt"

# --- (الكود البرمجي - لا تعدل ما لم تكن تعرف ماذا تفعل) ---

def get_github_repo():
    """يتصل بمستودع GitHub."""
    if not GITHUB_TOKEN:
        raise ValueError("خطأ: لم يتم العثور على GitHub Token.")
    return Github(GITHUB_TOKEN).get_repo(GITHUB_REPO_NAME)

def get_file_content(repo, file_path):
    """يحصل على محتوى ملف من GitHub، ويعيد None إذا لم يكن موجودًا."""
    try:
        file_content = repo.get_contents(file_path)
        return file_content.decoded_content.decode('utf-8')
    except UnknownObjectException:
        return None # الملف غير موجود
    except Exception as e:
        print(f"⚠️ تحذير: لم أتمكن من قراءة الملف {file_path}. السبب: {e}")
        return "" # نعيد نص فارغ لمنع توقف السكريبت

def upload_or_update_github_file(repo, file_path, content, commit_message):
    """يرفع أو يحدّث ملف على GitHub."""
    try:
        existing_file = repo.get_contents(file_path)
        repo.update_file(existing_file.path, commit_message, content, existing_file.sha)
        print(f"✅ تم تحديث الملف: {file_path}")
    except UnknownObjectException:
        repo.create_file(file_path, commit_message, content)
        print(f"✅ تم إنشاء ملف جديد: {file_path}")
    except Exception as e:
        raise IOError(f"فشل الرفع إلى GitHub للملف {file_path}. السبب: {e}")

def get_content_plan_prompt(category, excluded_titles):
    """ينشئ البرومبت النهائي مع إضافة القسم وقائمة العناوين المستبعدة."""
    exclusion_prompt_part = ""
    if excluded_titles:
        excluded_titles_text = "\n- ".join(excluded_titles)
        exclusion_prompt_part = f"""
ملاحظة هامة جدا: لقد قمت بالفعل بنشر المقالات التالية. لا تقم بتوليد أي من هذه العناوين مرة أخرى أو عناوين شديدة الشبه بها:
- {excluded_titles_text}
"""
    return f"""
بصفتك خبيرًا في تحسين محركات البحث (SEO)، أنشئ لي خطة محتوى احترافية لقسم ({category}).
المطلوب:
1- اقتراح (20) عنوان مقال جديد ومبتكر.
2- كل عنوان يجب أن يكون قابل للبحث، احترافي وجذاب.
3- قدم النتائج في جدول، ثم حول هذا الجدول إلى تنسيق JSON Array صالح.
{exclusion_prompt_part}
IMPORTANT: Your final output MUST be a valid JSON array of objects. Each object must have these keys in English: "title", "keyword", "meta_description", "goal", "competition", "search_volume", "cpc". Do not include any text or markdown formatting before or after the JSON array.
"""

def generate_plan_for_category(category, excluded_titles):
    """يولد خطة محتوى لقسم معين باستخدام Gemini."""
    if not GEMINI_API_KEYS:
        raise ValueError("خطأ: لم يتم العثور على أي مفاتيح Gemini API.")

    selected_api_key = random.choice(GEMINI_API_KEYS)
    genai.configure(api_key=selected_api_key)

    prompt = get_content_plan_prompt(category, excluded_titles)

    for model_name in GEMINI_MODELS:
        print(f"   - محاولة مع نموذج: {model_name}...")
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt, request_options={'timeout': 120}) # زيادة مهلة الانتظار
            cleaned_response = response.text.strip().replace("```json", "").replace("```", "")
            
            # تحقق بسيط من صحة الـ JSON
            json.loads(cleaned_response) 
            
            print(f"   🎉 نجح! تم توليد الخطة باستخدام {model_name}.")
            return json.dumps(json.loads(cleaned_response), indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"   ❌ فشل مع {model_name}. السبب: {e}")
            time.sleep(2) # انتظار ثانيتين قبل المحاولة التالية
    
    raise RuntimeError(f"فشلت جميع النماذج في توليد خطة للقسم: {category}")

# --- السكريبت الرئيسي ---
if __name__ == "__main__":
    try:
        print("🚀 بدء عملية فحص وتحديث خطط المحتوى...")
        repo = get_github_repo()
        
        # قراءة قائمة العناوين المنشورة مرة واحدة في البداية
        published_titles_content = get_file_content(repo, PUBLISHED_TITLES_FILE_PATH)
        published_titles = published_titles_content.splitlines() if published_titles_content else []
        if published_titles:
            print(f"تم العثور على {len(published_titles)} عنوانًا منشورًا سابقًا لتجنبها.")

        # المرور على كل قسم للتحقق من خطته
        for category in BLOG_CATEGORIES:
            print(f"\n🔎 يتم الآن فحص قسم: '{category}'...")
            plan_path = f"{PLANS_DIRECTORY}/content_plan_{category}.json"
            
            content = get_file_content(repo, plan_path)
            
            # التحقق إذا كانت الخطة بحاجة للتجديد (غير موجودة أو فارغة)
            needs_regeneration = False
            if content is None:
                print("   - الحالة: الخطة غير موجودة. سيتم إنشاؤها.")
                needs_regeneration = True
            else:
                try:
                    plan_data = json.loads(content)
                    if not isinstance(plan_data, list) or not plan_data:
                        print("   - الحالة: الخطة موجودة لكنها فارغة. سيتم تجديدها.")
                        needs_regeneration = True
                    else:
                        print(f"   - الحالة: الخطة موجودة وتحتوي على {len(plan_data)} مقال. لا يلزم اتخاذ أي إجراء.")
                except json.JSONDecodeError:
                    print("   - الحالة: الخطة موجودة لكنها تالفة. سيتم تجديدها.")
                    needs_regeneration = True
            
            if needs_regeneration:
                try:
                    print("   - جاري توليد خطة محتوى جديدة...")
                    new_plan_json = generate_plan_for_category(category, published_titles)
                    commit_msg = f"feat: Regenerate content plan for '{category}'"
                    upload_or_update_github_file(repo, plan_path, new_plan_json, commit_msg)
                except (RuntimeError, IOError) as e:
                    print(f"   🛑 فشلت عملية التجديد للقسم '{category}'. السبب: {e}")
        
        print("\n\n🏁 انتهت عملية الفحص بالكامل.")

    except (ValueError, IOError) as e:
        print(f"\n🛑 توقفت العملية بسبب خطأ فادح: {e}")

