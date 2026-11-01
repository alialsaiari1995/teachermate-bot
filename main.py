import os
import PyPDF2
import google.generativeai as genai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from flask import Flask
import threading

BOT_TOKEN = os.getenv("BOT_TOKEN","").strip().replace(" ", "").replace("\n","").replace("\r","")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY","").strip().replace(" ", "").replace("\n","").replace("\r","")
print(f"Token length: {len(BOT_TOKEN)}")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is Live!"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("أهلا بك! أنا برنامج المعلم الآلي 🤖\nارسل لي ملف PDF وسألخصه لك.")

async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("جاري قراءة الملف... ⏳")
    try:
        file = await context.bot.get_file(update.message.document.file_id)
        await file.download_to_drive("temp.pdf")
        text = ""
        with open("temp.pdf", "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                text += page.extract_text() or ""
        if not text.strip():
            await update.message.reply_text("ما قدرت اقرأ النص من الملف")
            return
        prompt = f"لخص هذا النص للمعلم بشكل مرتب: {text[:15000]}"
        response = model.generate_content(prompt)
        await update.message.reply_text(response.text[:4000])
    except Exception as e:
        await update.message.reply_text(f"حدث خطأ: {e}")

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    bot_app = ApplicationBuilder().token(BOT_TOKEN).build()
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
    print("Bot started polling...")
    bot_app.run_polling()
