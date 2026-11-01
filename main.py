import os, logging, threading, re
from flask import Flask
import PyPDF2
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from google import genai

# === 1. حل مشكلة البورت ===
app = Flask(__name__)
@app.route('/')
def home(): return "TeacherMateBot - gemini-3.8-flash ✅"
def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
threading.Thread(target=run_flask, daemon=True).start()

# === 2. الاعدادات ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)
logging.basicConfig(level=logging.INFO)

# === 3. البرومبت المتكامل ===
SYSTEM_PROMPT = """
أنت TeacherMateBot - معلم خبير ومُساعد تعليمي شامل لكتاب "لغتي الخالدة".

قواعدك:
1. أنت تملك نص الكتاب كاملاً في الذاكرة. جاوب على أي سؤال: قصائد، دروس، نحو، بلاغة، معاني، شرح، تلخيص، واجبات، اختبارات.
2. لا تسأل الطالب "ما القصيدة التي تريدها؟" - جاوب مباشرة. إذا ذكر صفحة (مثل صفحة 72) اذهب لتلك الصفحة واعط النص كاملاً.
3. إذا طلب اختبار: أنشئ اختبار متكامل (اختيار من متعدد + صح وخطأ + أسئلة مقالية + إجابات نموذجية). نظمه وجاهز للطباعة.
4. إذا طلب ملف PDF أو Word: قل له "سأجهز لك النص، انسخه" وأعط النص منسق وجاهز للنسخ في Word.
5. لا تذكر اسم "أحمد" أبداً. خاطب المستخدم بـ "أستاذ" أو بشكل عام.
6. لا تقل "النص المرسل لا يحتوي". أنت قرأت 234 صفحة كاملة. ابحث بذكاء.
7. اذا طلب تلخيص وحدة: لخصها بعناوين واضحة.
8. اللغة: عربية فصحى مبسطة مع تشكيل خفيف.
"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "أهلاً بك! 👋\n"
        "أرسل لي كتاب لغتي الخالدة PDF، وبعدها اسألني أي شيء:\n"
        "• اشرح لي درس كذا\n"
        "• قصيدة صفحة 72\n"
        "• سوي لي اختبار للوحدة الأولى\n"
        "• لخص لي الوحدة\n"
        "أنا معك 📚"
    )

async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("جاري قراءة الكتاب كامل (234 صفحة)... ⏳ قد يأخذ دقيقة")
    try:
        file = await context.bot.get_file(update.message.document.file_id)
        await file.download_to_drive("book.pdf")
        text = ""
        with open("book.pdf", "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for i, page in enumerate(reader.pages):
                page_text = page.extract_text() or ""
                # نحفظ مع
