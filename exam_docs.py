"""إنشاء ملفات الاختبار: PDF و Word (عربي من اليمين لليسار)"""
import io
import os
import re
import logging

log = logging.getLogger("bot.docs")

TYPE_NAMES = {"mcq": "اختيار من متعدد", "tf": "صح وخطأ", "essay": "مقالي"}
ORDINALS = ["الأول", "الثاني", "الثالث"]
LETTERS = ["أ", "ب", "ج", "د"]

try:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import arabic_reshaper
    try:
        from bidi.algorithm import get_display
    except ImportError:
        from bidi import get_display
    PDF_OK = True
except Exception:
    PDF_OK = False

try:
    from docx import Document
    from docx.shared import Pt, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    DOCX_OK = True
except Exception:
    DOCX_OK = False

FONT_CANDIDATES = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "font.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
_font_name = None


# ---------- أدوات عامة ----------
def fmt(n) -> str:
    n = float(n)
    return str(int(n)) if n.is_integer() else f"{n:g}"


def clean_md(t: str) -> str:
    t = re.sub(r"^\s*[-*_]{3,}\s*$", "", t, flags=re.M)
    t = re.sub(r"^\s*#+\s*", "", t, flags=re.M)
    t = t.replace("**", "").replace("__", "").replace("`", "")
    t = re.sub(r"^\s*\*\s+", "• ", t, flags=re.M)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def total_marks(exam: dict) -> float:
    return sum(len(s["questions"]) * s["points"] for s in exam["sections"])


def sec_title(i: int, sec: dict) -> str:
    return f"القسم {ORDINALS[i]}: {TYPE_NAMES[sec['type']]}"


def sec_sub(sec: dict) -> str:
    n = len(sec["questions"])
    p = sec["points"]
    return f"({n} أسئلة | درجة السؤال: {fmt(p)} | المجموع: {fmt(n * p)})"


# ---------- PDF ----------
def get_font():
    global _font_name
    if _font_name:
        return _font_name
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            pdfmetrics.registerFont(TTFont("AR", p))
            _font_name = "AR"
            return _font_name
    return None


def rtl(s: str) -> str:
    s = arabic_reshaper.reshape(s)
    try:
        return get_display(s, base_dir="R")
    except TypeError:
        return get_display(s)


def wrap(text: str, font: str, size: int, maxw: float):
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if not cur or pdfmetrics.stringWidth(rtl(t), font, size) <= maxw:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def make_exam_pdf(exam: dict):
    """يرجع بايتات PDF أو None."""
    try:
        if not PDF_OK:
            return None
        font = get_font()
        if not font:
            return None
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        W, H = A4
        M, size, lead = 50, 13, 21
        st = {"y": H - M}

        def newpage():
            c.showPage()
            st["y"] = H - M

        def line(text, f=size, gap=lead, center=False, indent=0):
            if st["y"] < M + gap:
                newpage()
            c.setFont(font, f)
            if center:
                c.drawCentredString(W / 2, st["y"], rtl(text))
            else:
                c.drawRightString(W - M - indent, st["y"], rtl(text))
            st["y"] -= gap

        def para(text, indent=0, f=size, gap=lead):
            for ln in wrap(text, font, f, W - 2 * M - indent):
                line(ln, f, gap, indent=indent)

        def gap(h):
            st["y"] -= h

        # الترويسة
        line(exam["title"], 18, 30, center=True)
        if exam.get("subtitle"):
            line(exam["subtitle"], 12, 24, center=True)
        line(f"الدرجة الكلية: {fmt(total_marks(exam))}", 13, 26, center=True)
        line("اسم الطالب: ..............................      التاريخ: ................", 12, 32)

        # الأسئلة
        for i, sec in enumerate(exam["sections"]):
            gap(6)
            para(sec_title(i, sec), f=15, gap=24)
            para(sec_sub(sec), f=11, gap=20)
            gap(4)
            for n, q in enumerate(sec["questions"], 1):
                suffix = "   ( ........ )" if sec["type"] == "tf" else ""
                para(f"{n}. {q['q']}{suffix}")
                if sec["type"] == "mcq":
                    for k, opt in enumerate(q.get("options", [])[:4]):
                        para(f"{LETTERS[k]}) {opt}", indent=24)
                if sec["type"] == "essay":
                    gap(lead * 2)
                gap(5)

        # الإجابات في صفحة منفصلة
        newpage()
        line("نموذج الإجابة", 18, 30, center=True)
        for i, sec in enumerate(exam["sections"]):
            gap(6)
            para(sec_title(i, sec), f=15, gap=24)
            for n, q in enumerate(sec["questions"], 1):
                ref = f" (ص {q['page']})" if q.get("page") else ""
                para(f"{n}. {q['answer']}{ref}")
        c.save()
        return buf.getvalue()
    except Exception:
        log.exception("make_exam_pdf failed")
        return None


# ---------- Word ----------
def _style_run(run, size=12, bold=False):
    run.font.name = "Arial"
    run.font.size = Pt(size)
    run.font.bold = bold
    rPr = run._r.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.insert(0, rFonts)
    for a in ("w:ascii", "w:hAnsi", "w:cs"):
        rFonts.set(qn(a), "Arial")
    szcs = OxmlElement("w:szCs")
    szcs.set(qn("w:val"), str(int(size * 2)))
    rPr.append(szcs)
    if bold:
        rPr.append(OxmlElement("w:bCs"))
    rPr.append(OxmlElement("w:rtl"))


def _par(doc, text, size=12, bold=False, center=False, indent_cm=0, space_after=4):
    p = doc.add_paragraph()
    p._p.get_or_add_pPr().insert(0, OxmlElement("w:bidi"))
    if center:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pf = p.paragraph_format
    pf.space_after = Pt(space_after)
    if indent_cm:
        pf.right_indent = Cm(indent_cm)
    _style_run(p.add_run(text), size, bold)
    return p


def make_exam_docx(exam: dict):
    """يرجع بايتات Word أو None."""
    try:
        if not DOCX_OK:
            return None
        doc = Document()
        sec0 = doc.sections[0]
        sec0.right_margin = sec0.left_margin = Cm(2)
        _par(doc, exam["title"], 18, True, center=True, space_after=6)
        if exam.get("subtitle"):
            _par(doc, exam["subtitle"], 12, center=True)
        _par(doc, f"الدرجة الكلية: {fmt(total_marks(exam))}", 13, True, center=True, space_after=10)
        _par(doc, "اسم الطالب: ..............................      التاريخ: ................", 12, space_after=10)

        for i, sec in enumerate(exam["sections"]):
            _par(doc, sec_title(i, sec), 15, True, space_after=2)
            _par(doc, sec_sub(sec), 11, space_after=8)
            for n, q in enumerate(sec["questions"], 1):
                suffix = "   ( ........ )" if sec["type"] == "tf" else ""
                _par(doc, f"{n}. {q['q']}{suffix}", 12, space_after=3)
                if sec["type"] == "mcq":
                    for k, opt in enumerate(q.get("options", [])[:4]):
                        _par(doc, f"{LETTERS[k]}) {opt}", 12, indent_cm=1, space_after=1)
                if sec["type"] == "essay":
                    _par(doc, "", 12, space_after=24)
                _par(doc, "", 6, space_after=2)

        doc.add_page_break()
        _par(doc, "نموذج الإجابة", 18, True, center=True, space_after=8)
        for i, sec in enumerate(exam["sections"]):
            _par(doc, sec_title(i, sec), 15, True, space_after=4)
            for n, q in enumerate(sec["questions"], 1):
                ref = f" (ص {q['page']})" if q.get("page") else ""
                _par(doc, f"{n}. {q['answer']}{ref}", 12, space_after=3)
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()
    except Exception:
        log.exception("make_exam_docx failed")
        return None


# ---------- نص عادي (احتياط إذا تعذر إنشاء الملفات) ----------
def exam_to_text(exam: dict) -> str:
    out = [exam["title"], exam.get("subtitle", ""), f"الدرجة الكلية: {fmt(total_marks(exam))}", ""]
    for i, sec in enumerate(exam["sections"]):
        out += [sec_title(i, sec), sec_sub(sec), ""]
        for n, q in enumerate(sec["questions"], 1):
            out.append(f"{n}. {q['q']}")
            if sec["type"] == "mcq":
                out += [f"   {LETTERS[k]}) {o}" for k, o in enumerate(q.get("options", [])[:4])]
        out.append("")
    out.append("نموذج الإجابة:")
    for i, sec in enumerate(exam["sections"]):
        out.append(sec_title(i, sec))
        for n, q in enumerate(sec["questions"], 1):
            ref = f" (ص {q['page']})" if q.get("page") else ""
            out.append(f"{n}. {q['answer']}{ref}")
    return "\n".join(out).strip()
