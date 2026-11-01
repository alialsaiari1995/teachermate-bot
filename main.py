import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import PyPDF2
import google.generativeai as genai
from flask import Flask
import threading

# سيرفر وهمي
app = Flask('')
@app.route('/')
def home(): return "Bot is Live!"
threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# اهم سطر - هذا اللي يصلح الخطأ حقك
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")

logging.basicConfig(level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("أهلا أستاذ! أرسل لي ملف PDF للكتاب وراح أساعدك 📚")

async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("جاري قراءة الملف... ⏳")
    try:
        file = await context.bot.get_file(update.message.document.file_id)
        await file.download_to_drive("book.pdf")
        text = ""
        with open("book.pdf", "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages[:25]:
                text += page.extract_text() or ""
        context.user_data['book_text'] = text[:20000]
        await update.message.reply_text("تم! ✅ الحين اسألني أي سؤال عن الكتاب أو اضغط (شرح درس / إنشاء اختبار)")
    except Exception as e:
        await update.message.reply_text(f"خطأ في قراءة الملف: {e}")

async def handle_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'book_text' not in context.user_data:
        await update.message.reply_text("أرسل الكتاب أولا PDF من زر (رفع المنهج) 📘")
        return
    question = update.message.text
    await update.message.reply_text("جاري التفكير... 🤔")
    try:
        prompt = f"أنت مساعد معلم خبير. بناء على هذا النص من الكتاب: {context.user_data['book_text']}\n\nأجب على: {question}"
        response = model.generate_content(prompt)
        await update.message.reply_text(response.text)
    except Exception as e:
        await update.message.reply_text(f"حدث خطأ: {e}")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_question))
    application.run_polling()

if __name__ == "__main__":
    main()
