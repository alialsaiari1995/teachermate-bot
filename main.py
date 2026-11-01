import os
import logging
import threading
from flask import Flask
import PyPDF2
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from google import genai

# ===== 1. حل مشكلة البورت في Render =====
app = Flask(__name__)
@app.route('/')
def home():
    return "TeacherMateBot is Running with gemini-3.8-flash ✅"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

threading.Thread(target=run_flask, daemon=True).start()

# ===== 2. اعدادات البوت =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

if not BOT_TOKEN or not GEMINI_API_KEY:
    print("خطأ: BOT_TOKEN أو GEMINI_API_KEY ناقص في Render Environment")

client = genai.Client(api_key=GEMINI_API_KEY)
logging.basicConfig(level=logging.INFO)

# ===== 3. اوامر التلقرام =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("أهلا أستاذ أحمد! 👋\nأرسل لي ملف لغتي الخالدة PDF 📚")

async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("جاري قراءة الملف... ⏳")
    try:
        file = await context.bot.get_file(update.message.document.file_id)
        await file.download_to_drive("book.pdf")
        text = ""
        with open("book.pdf", "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages[:45]: # يقرأ اول 45 صفحة
                text += (page.extract_text() or "") + "\n"
        
        context.user_data['book_text'] = text
        await update.message.reply_text(f"تم! ✅ قرأت {len(reader.pages)} صفحة. الحين اسألني: اي قصيدة في صفحة 72؟")
    except Exception as e:
        await update.message.reply_text(f"خطأ في قراءة PDF: {e}")

async def handle_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'book_text' not in context.user_data:
        await update.message.reply_text("أرسل كتاب لغتي الخالدة أولا PDF 📘")
        return

    await update.message.reply_text("جاري التفكير... 🤔")
    try:
        book = context.user_data['book_text'][:25000]
        prompt = f"""
        أنت مساعد معلم لغة عربية. هذا نص من كتاب لغتي الخالدة:
        {book}
        
        سؤال الطالب: {update.message.text}
        جاوب بالعربية وبشكل مباشر من الكتاب، واذكر رقم الصفحة اذا موجود.
        """
        
        # الموديل الجديد الرسمي
        response = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=prompt
        )
        await update.message.reply_text(response.text[:4000])
    except Exception as e:
        await update.message.reply_text(f"خطأ: {e}")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_question))
    print("Bot Started...")
    application.run_polling()

if __name__ == "__main__":
    main()
