from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re

from app.config import settings


@lru_cache(maxsize=1)
def get_ocr_reader():
    try:
        import easyocr
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "OCR is enabled but EasyOCR is not installed. Install apps/api requirements again."
        ) from exc

    return easyocr.Reader(["ar", "en"], gpu=False, verbose=False)


def ocr_cache_path(document_id: str, page_number: int) -> Path:
    return settings.ocr_dir / f"{document_id}_p{page_number}.txt"


OCR_REPLACEMENTS = {
    "تاربخ": "تاريخ",
    "علان": "إعلان",
    "اشع": "الشعب",
    "عىبها": "عليها",
    "يعما": "يعمل",
    "بهده": "بهذه",
    "الوثبقة": "الوثيقة",
    "الدستوريه": "الدستورية",
    "الاصوات": "الأصوات",
    "لامشاركين": "للمشاركين",
    "الشبوخ": "الشيوخ",
    "الشيوح": "الشيوخ",
    "الدبمقراطية": "الديمقراطية",
    "الديمفراطية": "الديمقراطية",
    "الديموفراطى": "الديمقراطى",
    "الحربات": "الحريات",
    "الحفو": "الحقوق",
    "المفومات": "المقومات",
    "الافتصادية": "الاقتصادية",
    "الجمهوربة": "الجمهورية",
    "رنبس": "رئيس",
    "رئبس": "رئيس",
    "المانون": "القانون",
    "فانون": "قانون",
    "قالون": "قانون",
    "بحدده": "يحدده",
    "النطام": "النظام",
    "مبلادية": "ميلادية",
}


def clean_ocr_text(text: str) -> str:
    cleaned_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if re.search(r"(?:node|روابط سريعة|روابط|فريق العمل|اتصل بنا)", stripped, re.IGNORECASE):
            break
        cleaned_lines.append(stripped)

    cleaned = "\n".join(cleaned_lines)
    for wrong, right in OCR_REPLACEMENTS.items():
        cleaned = cleaned.replace(wrong, right)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    return cleaned.strip()


def ocr_pdf_page(document_id: str, pdf_path: Path, page_number: int) -> str:
    cache_path = ocr_cache_path(document_id, page_number)
    if cache_path.exists():
        return clean_ocr_text(cache_path.read_text(encoding="utf-8"))

    try:
        import fitz
    except ModuleNotFoundError as exc:
        raise RuntimeError("OCR requires PyMuPDF.") from exc

    with fitz.open(pdf_path) as document:
        if page_number < 1 or page_number > document.page_count:
            return ""
        page = document[page_number - 1]
        pixmap = page.get_pixmap(
            matrix=fitz.Matrix(settings.ocr_scale, settings.ocr_scale),
            alpha=False,
        )
        image_path = settings.ocr_dir / f"{document_id}_p{page_number}.png"
        pixmap.save(str(image_path))

    reader = get_ocr_reader()
    lines = reader.readtext(
        str(image_path),
        detail=0,
        paragraph=True,
        decoder="greedy",
        batch_size=16,
        canvas_size=settings.ocr_canvas_size,
        mag_ratio=1.0,
    )
    text = clean_ocr_text("\n".join(str(line) for line in lines))
    cache_path.write_text(text, encoding="utf-8")
    return text
