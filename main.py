import os, logging, threading, re
from flask import Flask
import PyPDF2
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from google import genai
from docx import Document
from fpdf import FPDF

# === 1. حل مشكلة البورت ===
app = Flask(__name__)
@app.route('/')
def home(): return "TeacherMateBot - Ready ✅"
def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
threading.Thread(target=run_flask, daemon=True).start()

# === 2. الاعدادات ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)
logging.basicConfig(level=logging.INFO)

SYSTEM_PROMPT = """
أنت معلم خبير لكتاب "لغتي الخالدة - الصف الأول المتوسط".

قوانين صارمة:
1. لا تخرج أبداً عن منهج الكتاب. كل إجاباتك من نص الكتاب المرفق فقط.
2. لا تقول "لا يمكنني إرسال ملفات". أنت فقط تنتج النص، والبوت سيحوله لملف.
3. إذا طلب اختبار: اعمل اختبار كامل من الكتاب مع 3 أقسام: اختيار من متعدد، صح وخطأ، مقالي. مع نموذج الإجابة.
4. إذا طلب تلخيص: لخص الوحدة المطلوبة فقط.
5. إذا ذكر رقم صفحة: اذهب لتلك الصفحة واعط النص كاملاً.
6. لا تسأل المستخدم ماذا تريد، جاوب مباشرة.
"""

def make_docx(text, path="/tmp/اختبار.docx"):
    doc = Document()
    doc.add_heading('اختبار لغتي الخالدة', 0)
    for line in text.split('\n'):
        if line.strip():
            doc.add_paragraph(line.strip())
    doc.save(path)
    return path

def make_pdf(text, path="/tmp/اختبار.pdf"):
    pdf = FPDF()
    pdf.add_page()
    # نستخدم خط يدعم العربية موجود في سيرفر Render
    try:
        pdf.add_font("DejaVu", "", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", uni=True)
        pdf.set_font("DejaVu", "", 11)
    except:
        pdf.set_font("Arial", "", 11)
    
    for line in text.split('\n'):
        if line.strip():
            # تنظيف بسيط للعربية عشان ما يعلق
            safe_line = line.strip()
            pdf.multi_cell(0, 8, safe_line)
    pdf.output(path)
    return path

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("أهلا! أرسل كتاب لغتي الخالدة PDF وبعدها اطلب أي شي (اختبار، تلخيص، صفحة 72) وأنا أسويه لك ملف 📚")

async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("جاري قراءة الكتاب كامل... ⏳")
    file = await context.bot.get_file(update.message.document.file_id)
    await file.download_to_drive("/tmp/book.pdf")
    text = ""
    with open("/tmp/book.pdf", "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for i, page in enumerate(reader.pages):
            text += f"\n[صفحة {i+1}]\n" + (page.extract_text() or "")
    context.user_data['book'] = text
    await update.message.reply_text(f"تم ✅ قرأت {len(reader.pages)} صفحة. اطلب: سوي لي اختبار، أو تلخيص، أو اسأل عن أي صفحة.")

async def handle_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'book' not in context.user_data:
        await update.message.reply_text("أرسل الكتاب PDF أولاً")
        return
    await update.message.reply_text("جاري التجهيز... 🤔 (10 ثواني)")
    try:
        book = context.user_data['book'][:40000]
        # لو سأل عن صفحة محددة نركز عليها
        m = re.search(r'(\d+)', update.message.text)
        if m:
            pn = m.group(1)
            idx = book.find(f"[صفحة {pn}]")
            if idx != -1:
                book = book[max(0, idx-1000): idx+8000]

        prompt = f"{SYSTEM_PROMPT}\n\nنص الكتاب:\n{book}\n\nسؤال الطالب: {update.message.text}"
        res = client.models.generate_content(model="gemini-3.8-flash", contents=prompt)
        answer = res.text

        # 1. نرسل النص كرسائل
        for i in range(0, len(answer), 4000):
            await update.message.reply_text(answer[i:i+4000])

        # 2. نسوي الملفات ونرسلها فعلاً
        docx_path = make_docx(answer)
        pdf_path = make_pdf(answer)
        
        await context.bot.send_document(chat_id=update.effective_chat.id, document=open(docx_path, 'rb'), filename="اختبار_لغتي_الخالدة.docx")
        await context.bot.send_document(chat_id=update.effective_chat.id, document=open(pdf_path, 'rb'), filename="اختبار_لغتي_الخالدة.pdf")
        await update.message.reply_text("تم إرسال الملفين Word و PDF فوق 👆 جاهزين للطباعة")

    except Exception as e:
        await update.message.reply_text(f"خطأ: {e}")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_question))
    application.run_polling()

if __name__ == "__main__":
    main()
