import os, logging, threading, re, asyncio, random
from flask import Flask
import PyPDF2
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from google import genai
from docx import Document
from fpdf import FPDF

app = Flask(__name__)
@app.route('/')
def home(): return "OK"
def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
threading.Thread(target=run_flask, daemon=True).start()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)

def make_docx(text):
    path="/tmp/test.docx"
    doc=Document()
    doc.add_heading('اختبار لغتي الخالدة',0)
    for l in text.split('\n'):
        if l.strip(): doc.add_paragraph(l)
    doc.save(path)
    return path

def make_pdf(text):
    path="/tmp/test.pdf"
    pdf=FPDF()
    pdf.add_page()
    pdf.set_font("Arial","",11)
    for l in text.split('\n'):
        if l.strip():
            try: pdf.multi_cell(0,8,l)
            except: pdf.multi_cell(0,8,l.encode('utf-8','ignore').decode())
    pdf.output(path)
    return path

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("أرسل الكتاب PDF")

async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("جاري القراءة...")
    f=await context.bot.get_file(update.message.document.file_id)
    await f.download_to_drive("/tmp/book.pdf")
    txt=""
    with open("/tmp/book.pdf","rb") as file:
        r=PyPDF2.PdfReader(file)
        for i,p in enumerate(r.pages):
            txt+=f"\n[صفحة {i+1}]\n"+(p.extract_text()or"")
    context.user_data['book']=txt
    await update.message.reply_text(f"تم {len(r.pages)} صفحة. اطلب اختبار")

async def handle_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'book' not in context.user_data:
        await update.message.reply_text("أرسل الكتاب أول")
        return
    await update.message.reply_text("جاري التجهيز...")
    MODELS=["gemini-3.8-flash","gemini-2.5-flash","gemini-1.5-flash"]
    book=context.user_data['book'][:35000]
    prompt=f"أنت معلم. من هذا الكتاب: {book}\n\nأجب: {update.message.text}\nاعمل اختبار 15 درجة 5 اختيار و5 صح وخطأ و5 مقالي مع الاجابات"
    ans=None
    for m in MODELS:
        try:
            res=client.models.generate_content(model=m, contents=prompt)
            ans=res.text
            break
        except Exception as e:
            if "503" in str(e): 
                await asyncio.sleep(2)
                continue
            else: break
    if not ans:
        await update.message.reply_text("جوجل مضغوط جرب بعد دقيقة")
        return
    await update.message.reply_text(ans[:4000])
    d=make_docx(ans)
    p=make_pdf(ans)
    await context.bot.send_document(chat_id=update.effective_chat.id, document=open(d,'rb'), filename="اختبار.docx")
    await context.bot.send_document(chat_id=update.effective_chat.id, document=open(p,'rb'), filename="اختبار.pdf")
    await update.message.reply_text("الملفين فوق 👆")

def main():
    app2=Application.builder().token(BOT_TOKEN).build()
    app2.add_handler(CommandHandler("start",start))
    app2.add_handler(MessageHandler(filters.Document.PDF,handle_pdf))
    app2.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,handle_question))
    app2.run_polling()

if __name__=="__main__": main()t
