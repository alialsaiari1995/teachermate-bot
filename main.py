import os, io, re, json, logging, threading, asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
from pypdf import PdfReader
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import arabic_reshaper
try:
    from bidi.algorithm import get_display
except ImportError:
    from bidi import get_display

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          MessageHandler, filters, ContextTypes)

logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.environ["BOT_TOKEN"]
MODEL = os.environ.get("MODEL", "gemini-2.5-flash")
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "Amiri-Regular.ttf")
HAS_FONT = os.path.exists(FONT_PATH)
if HAS_FONT:
    pdfmetrics.registerFont(TTFont("Arabic", FONT_PATH))

MAX_CHARS = 300_000

SYSTEM = (
    "أنت مساعد لمعلّم. اعتمد حصرياً على نص المنهج المرفق داخل الوسم <curriculum>. "
    "ممنوع منعاً باتاً استخدام أي معلومة من خارج هذا النص أو من معرفتك العامة. "
    "إذا لم يكفِ النص لسؤال معيّن فتجنّبه. اكتب باللغة العربية."
)

# ---------------- أدوات مساعدة ----------------
AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def nums(text):
    return [int(x) for x in re.findall(r"\d+", text.translate(AR_DIGITS))]


def menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 إضافة اختبار", callback_data="act:exam"),
         InlineKeyboardButton("📖 شرح", callback_data="act:explain")],
        [InlineKeyboardButton("🗒 تحضير", callback_data="act:prep"),
         InlineKeyboardButton("📌 ملخص", callback_data="act:summary")],
        [InlineKeyboardButton("📚 منهج جديد", callback_data="add")],
    ])


def extract_pages(name, data):
    name = name.lower()
    if name.endswith(".pdf"):
        r = PdfReader(io.BytesIO(data))
        return [(p.extract_text() or "") for p in r.pages]
    if name.endswith(".docx"):
        d = Document(io.BytesIO(data))
        text = "\n".join(p.text for p in d.paragraphs)
    elif name.endswith(".txt"):
        text = data.decode("utf-8", errors="ignore")
    else:
        return None
    # docx/txt ما فيها صفحات حقيقية: نقسمها كل 2500 حرف "صفحة"
    return [text[i:i + 2500] for i in range(0, len(text), 2500)] or [""]


def pick_text(pages, a, b):
    chunk = pages[a - 1:b]
    text = "\n".join(f"[صفحة {a + i}]\n{t}" for i, t in enumerate(chunk))
    return text[:MAX_CHARS]


async def ask_claude(prompt, max_tokens=8000, json_mode=False):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    body = {
        "system_instruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    r = None
    for attempt in range(4):  # يعيد المحاولة تلقائياً لو Google مشغول
        async with httpx.AsyncClient(timeout=180) as h:
            r = await h.post(url, json=body, headers={"x-goog-api-key": GEMINI_API_KEY})
        if r.status_code not in (429, 500, 503):
            break
        await asyncio.sleep(5 * (attempt + 1))
    if r.status_code != 200:
        raise RuntimeError(f"Gemini {r.status_code}: {r.text[:300]}")
    parts = r.json()["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts)


# ---------------- Word / PDF ----------------
def rtl_par(doc, text, bold=False, size=14):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p._p.get_or_add_pPr().append(OxmlElement("w:bidi"))
    run = p.add_run(text)
    run.bold = bold
    run.font.size = __import__("docx").shared.Pt(size)
    run._r.get_or_add_rPr().append(OxmlElement("w:rtl"))
    return p


def exam_lines(exam, cfg):
    """يرجع (أسئلة, نموذج إجابة) كقوائم نصوص."""
    L, K = [], []
    n = 1
    L.append(("h", exam.get("title", "اختبار")))
    if exam.get("mcq"):
        L.append(("h2", f"أولاً: اختيار من متعدد ({cfg['mcq_m']} درجة لكل سؤال)"))
        K.append(("h2", "اختيار من متعدد"))
        for q in exam["mcq"]:
            L.append(("p", f"{n}) {q['q']}"))
            for lab, o in zip("أبجد", q["options"]):
                L.append(("p", f"      {lab}- {o}"))
            K.append(("p", f"{n}) {q['answer']}"))
            n += 1
    if exam.get("tf"):
        L.append(("h2", f"ثانياً: صح أو خطأ ({cfg['tf_m']} درجة لكل سؤال)"))
        K.append(("h2", "صح وخطأ"))
        for q in exam["tf"]:
            L.append(("p", f"{n}) {q['q']}  (        )"))
            K.append(("p", f"{n}) {'صح' if q['answer'] else 'خطأ'}"))
            n += 1
    if exam.get("essay"):
        L.append(("h2", f"ثالثاً: أسئلة مقالية ({cfg['es_m']} درجة لكل سؤال)"))
        K.append(("h2", "مقالي"))
        for q in exam["essay"]:
            L.append(("p", f"{n}) {q['q']}"))
            K.append(("p", f"{n}) {q.get('model_answer', '')}"))
            n += 1
    return L, K


def build_docx(lines, key):
    d = Document()
    for kind, t in lines:
        rtl_par(d, t, bold=kind != "p", size=18 if kind == "h" else 14)
    d.add_page_break()
    rtl_par(d, "نموذج الإجابة", bold=True, size=18)
    for kind, t in key:
        rtl_par(d, t, bold=kind != "p")
    buf = io.BytesIO()
    d.save(buf)
    buf.seek(0)
    return buf


def shape(t):
    return get_display(arabic_reshaper.reshape(t))


def build_pdf(lines, key):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4
    margin = 50
    y = H - margin

    def new_page():
        nonlocal y
        c.showPage()
        y = H - margin

    def write(text, size):
        nonlocal y
        c.setFont("Arabic", size)
        width = W - 2 * margin
        cur = ""
        out = []
        for w in text.split(" "):
            test = (cur + " " + w).strip()
            if pdfmetrics.stringWidth(shape(test), "Arabic", size) > width and cur:
                out.append(cur)
                cur = w
            else:
                cur = test
        out.append(cur)
        for ln in out:
            if y < margin + size:
                new_page()
                c.setFont("Arabic", size)
            c.drawRightString(W - margin, y, shape(ln))
            y -= size * 1.7

    for kind, t in lines:
        write(t, 18 if kind == "h" else 14)
    new_page()
    write("نموذج الإجابة", 18)
    for kind, t in key:
        write(t, 14)
    c.save()
    buf.seek(0)
    return buf


async def send_files(update, lines, key, base):
    msg = update.effective_message
    w = build_docx(lines, key)
    await msg.reply_document(w, filename=f"{base}.docx")
    if HAS_FONT:
        p = build_pdf(lines, key)
        await msg.reply_document(p, filename=f"{base}.pdf")
    else:
        await msg.reply_text("⚠️ ملف PDF ما انعمل لأن الخط fonts/Amiri-Regular.ttf غير موجود في GitHub.")


# ---------------- المحادثة ----------------
EXAM_STEPS = [
    ("mcq_n", "كم سؤال *اختيار من متعدد* تبغى؟ (اكتب 0 للتخطي)"),
    ("mcq_m", "كم درجة كل سؤال اختيار؟"),
    ("tf_n", "كم سؤال *صح وخطأ* تبغى؟ (0 للتخطي)"),
    ("tf_m", "كم درجة كل سؤال صح وخطأ؟"),
    ("es_n", "كم سؤال *مقالي* تبغى؟ (0 للتخطي)"),
    ("es_m", "كم درجة كل سؤال مقالي؟"),
]


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ إضافة المنهج", callback_data="add")]])
    await update.message.reply_text("أهلاً يا أستاذ 👋", reply_markup=kb)


async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ud = ctx.user_data
    if q.data == "add":
        ud.clear()
        ud["state"] = "file"
        await q.message.reply_text("أرسل ملف المنهج (PDF أو Word أو TXT) 📎")
    elif q.data.startswith("act:"):
        if "pages" not in ud:
            await q.message.reply_text("أرسل المنهج أول /start")
            return
        ud["action"] = q.data[4:]
        ud["state"] = "range"
        n = len(ud["pages"])
        await q.message.reply_text(
            f"من أي صفحة إلى أي صفحة؟ مثال: 5-40\nأو اكتب (الكل) — الملف فيه {n} صفحة.")


async def on_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if ctx.user_data.get("state") != "file":
        await update.message.reply_text("اضغط /start ثم إضافة المنهج أول.")
        return
    await update.message.reply_text("⏳ جاري قراءة الملف...")
    f = await doc.get_file()
    data = bytes(await f.download_as_bytearray())
    pages = extract_pages(doc.file_name or "", data)
    if pages is None:
        await update.message.reply_text("الصيغة غير مدعومة. أرسل PDF أو DOCX أو TXT.")
        return
    if not any(p.strip() for p in pages):
        await update.message.reply_text("ما قدرت أستخرج نص من الملف (يمكن ممسوح صور). جرّب ملف ثاني.")
        return
    ctx.user_data["pages"] = pages
    ctx.user_data["state"] = None
    await update.message.reply_text(
        f"✅ الملف جاهز وقريته كامل ({len(pages)} صفحة).\nوش تبغى بالضبط؟",
        reply_markup=menu_kb())


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ud = ctx.user_data
    st = ud.get("state")
    txt = update.message.text.strip()

    if st == "range":
        n = len(ud["pages"])
        ns = nums(txt)
        if "كل" in txt or not ns:
            a, b = 1, n
        else:
            a, b = ns[0], (ns[1] if len(ns) > 1 else ns[0])
        a, b = max(1, min(a, b)), min(n, max(a, b))
        ud["range"] = (a, b)
        if ud["action"] == "exam":
            ud["cfg"], ud["step"], ud["state"] = {}, 0, "exam"
            await update.message.reply_text(EXAM_STEPS[0][1], parse_mode="Markdown")
        else:
            await run_text_task(update, ctx)
        return

    if st == "exam":
        ns = nums(txt)
        if not ns:
            await update.message.reply_text("اكتب رقم فقط 🙏")
            return
        key = EXAM_STEPS[ud["step"]][0]
        ud["cfg"][key] = ns[0]
        ud["step"] += 1
        # تخطي سؤال الدرجة إذا العدد صفر
        if key.endswith("_n") and ns[0] == 0:
            ud["cfg"][key[:-2] + "_m"] = 0
            ud["step"] += 1
        if ud["step"] >= len(EXAM_STEPS):
            ud["state"] = None
            await run_exam(update, ctx)
        else:
            await update.message.reply_text(EXAM_STEPS[ud["step"]][1], parse_mode="Markdown")
        return

    await update.message.reply_text("اضغط /start للبدء.")


async def run_exam(update, ctx):
    ud = ctx.user_data
    cfg = ud["cfg"]
    a, b = ud["range"]
    if cfg["mcq_n"] + cfg["tf_n"] + cfg["es_n"] == 0:
        await update.message.reply_text("ما حددت أي أسئلة. اضغط /start وابدأ من جديد.")
        return
    await update.message.reply_text("⏳ جاري تجهيز الاختبار...")
    prompt = f"""<curriculum>
{pick_text(ud['pages'], a, b)}
</curriculum>

ضع اختباراً من نص المنهج أعلاه فقط (الصفحات {a} إلى {b}):
- {cfg['mcq_n']} سؤال اختيار من متعدد (4 خيارات لكل سؤال)
- {cfg['tf_n']} سؤال صح وخطأ
- {cfg['es_n']} سؤال مقالي مع إجابة نموذجية
أرجع JSON فقط بدون أي شرح وبدون ``` بهذا الشكل:
{{"title":"اختبار","mcq":[{{"q":"","options":["","","",""],"answer":"أ"}}],"tf":[{{"q":"","answer":true}}],"essay":[{{"q":"","model_answer":""}}]}}"""
    try:
        raw = await ask_claude(prompt, json_mode=True)
        raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
        exam = json.loads(raw)
    except Exception as e:
        logging.exception(e)
        await update.message.reply_text(f"صار خطأ: {str(e)[:300]}")
        return
    total = (cfg["mcq_n"] * cfg["mcq_m"] + cfg["tf_n"] * cfg["tf_m"] + cfg["es_n"] * cfg["es_m"])
    exam["title"] = f"اختبار (الصفحات {a}-{b}) — الدرجة الكلية {total}"
    lines, key = exam_lines(exam, cfg)
    await send_files(update, lines, key, "exam")
    await update.message.reply_text("تبغى شي ثاني؟", reply_markup=menu_kb())


async def run_text_task(update, ctx):
    ud = ctx.user_data
    a, b = ud["range"]
    ud["state"] = None
    task = {
        "explain": "اشرح هذا الجزء شرحاً مبسطاً ومنظماً للطلاب.",
        "prep": "أعد تحضيراً للدرس: الأهداف، التمهيد، خطوات الشرح، الأنشطة، التقويم.",
        "summary": "لخّص هذا الجزء في نقاط مرتبة.",
    }[ud["action"]]
    await update.message.reply_text("⏳ لحظة...")
    prompt = f"<curriculum>\n{pick_text(ud['pages'], a, b)}\n</curriculum>\n\n{task} (الصفحات {a}-{b}) من نص المنهج فقط."
    try:
        out = await ask_claude(prompt)
    except Exception as e:
        logging.exception(e)
        await update.message.reply_text(f"صار خطأ: {str(e)[:300]}")
        return
    for i in range(0, len(out), 4000):
        await update.message.reply_text(out[i:i + 4000])
    lines = [("p", l) for l in out.split("\n") if l.strip()]
    await send_files(update, lines, [], ud["action"])
    await update.message.reply_text("تبغى شي ثاني؟", reply_markup=menu_kb())


# ---------------- سيرفر صغير لـ Render ----------------
class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


def run_health():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), Health).serve_forever()


def main():
    threading.Thread(target=run_health, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.Document.ALL, on_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()


if __name__ == "__main__":
    main()
