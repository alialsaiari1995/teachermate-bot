import os, fitz, asyncio, threading
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import google.generativeai as genai

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")
curriculum_db = {}
app_flask = Flask(__name__)

@app_flask.route('/upload/<int:user_id>', methods=['GET','POST'])
def upload_page(user_id):
    if request.method == 'POST':
        f = request.files.get('file')
        tmp_path = f"/tmp/{user_id}.pdf"
        f.save(tmp_path)
        pdf = fitz.open(tmp_path)
        text = ""
        for i, page in enumerate(pdf):
            t = page.get_text()
            if t.strip():
                text += f"\n--- صفحة {i+1} ---\n{t}"
        pdf.close()
        os.remove(tmp_path)
        curriculum_db[user_id] = text
        return f"<h2>✅ تم! ارجع تليجرام واكتب /start</h2>"
    return """
    <html dir='rtl'><body style='text-align:center;padding:20px'>
    <h2>📂 رفع المنهج (يدعم 500 ميجا)</h2>
    <form method='post' enctype='multipart/form-data'>
    <input type='file' name='file' accept='.pdf' required style='padding:20px;border:2px dashed green;width:90%'>
    <br><br><button type='submit' style='background:green;color:white;padding:15px 40px;font-size:18px'>رفع</button>
    </form></body></html>
    """

@app_flask.route('/')
def home(): return "Bot running ✅"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host='0.0.0.0', port=port)

STRICT = "أنت مقفل على هذا المنهج فقط. المنهج: {cur}\n\n"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    has = uid in curriculum_db
    status = "🔒 مقفل" if has else "📂 لا يوجد منهج"
    kb = [[InlineKeyboardButton("📂 رفع المنهج (للملفات الكبيرة 144 ميجا)", callback_data="upload_link")],[InlineKeyboardButton("📝 انشاء اختبار 10 اسئلة", callback_data="exam")],[InlineKeyboardButton("🗑️ مسح", callback_data="clear")]]
    await update.message.reply_text(f"أهلا ✅ {status}\nلو ملفك أقل من 20 ميجا أرسله هنا، لو أكبر اضغط الزر.", reply_markup=InlineKeyboardMarkup(kb))

async def handle_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    doc = update.message.document
    if doc.file_size/1024/1024 > 20:
        await update.message.reply_text("📂 ملفك كبير، اضغط زر رفع المنهج بالرابط (يدعم 500 ميجا)")
        return
    await update.message.reply_text("⏳ جاري تحويله لنص...")
    tg_file = await context.bot.get_file(doc.file_id)
    path = f"/tmp/{doc.file_id}.pdf"
    await tg_file.download_to_drive(path)
    pdf = fitz.open(path)
    text = ""
    for i, page in enumerate(pdf):
        text += f"\n--- صفحة {i+1} ---\n{page.get_text()}"
    pdf.close()
    os.remove(path)
    curriculum_db[uid] = text
    await update.message.reply_text("✅ تم! حولت لنص ومقفل على منهجك")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    txt = update.message.text.strip()
    if txt in ["كنسل","الغاء","/cancel"]: 
        context.user_data.clear()
        await update.message.reply_text("تم ✅ /start")
        return
    if uid not in curriculum_db:
        await update.message.reply_text("📂 أولا ارفع المنهج")
        return
    if context.user_data.get("awaiting_exam"):
        context.user_data["awaiting_exam"] = False
        await update.message.reply_text(f"⏳ جاري انشاء اختبار عن: {txt}... (30 ثانية)")
        try:
            cur = curriculum_db[uid][:12000]
            prompt = STRICT.format(cur=cur) + f"أنشئ 10 أسئلة فقط عن: {txt} من المنهج فقط"
            resp = await asyncio.to_thread(model.generate_content, prompt, request_options={"timeout": 90})
            await update.message.reply_text(resp.text[:4000])
        except Exception as e:
            await update.message.reply_text(f"جرب موضوع أصغر: {e}")
        return
    cur = curriculum_db[uid][:12000]
    prompt = STRICT.format(cur=cur) + f"سؤال: {txt}"
    resp = await asyncio.to_thread(model.generate_content, prompt)
    await update.message.reply_text(resp.text[:4000])

async def btn_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = update.effective_user.id
    if q.data == "upload_link":
        base_url = os.environ.get("RENDER_EXTERNAL_URL", "https://teachermate-bot.onrender.com")
        link = f"{base_url}/upload/{uid}"
        await q.message.reply_text(f"📂 ارفع من هنا (500 ميجا):\n{link}")
    elif q.data == "exam":
        if uid not in curriculum_db: 
            await q.message.reply_text("📂 ارفع المنهج أولا")
            return
        context.user_data["awaiting_exam"] = True
        await q.message.reply_text("اكتب موضوع الاختبار؟ مثال: من صفحة 20 الى 25 (10 اسئلة فقط عشان ما يعلق)")
    elif q.data == "clear":
        curriculum_db.pop(uid, None)
        await q.message.reply_text("🗑️ تم المسح")

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(btn_handler))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_doc))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()

if __name__ == "__main__":
    main()
