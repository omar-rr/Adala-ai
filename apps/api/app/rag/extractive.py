from __future__ import annotations

from app.rag.prompt import NOT_FOUND_MESSAGE
from app.rag.articles import extract_article_number
from app.rag.retriever import RetrievedChunk, has_article_count_intent


def has_arabic(text: str) -> bool:
    return any("\u0600" <= char <= "\u06ff" for char in text)


def compact_quote(text: str, limit: int = 620) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def asks_for_simplification(query: str) -> bool:
    lowered = query.lower()
    terms = [
        "summarize",
        "summary",
        "simplify",
        "explain",
        "plain",
        "meaning",
        "لخص",
        "تلخيص",
        "اشرح",
        "وضح",
        "بسط",
        "ببساطة",
        "ببساطه",
        "يعني",
    ]
    return any(term in lowered for term in terms)


def plain_language_note(text: str, arabic: bool) -> str:
    normalized = " ".join(text.split())
    lowered = normalized.lower()
    if arabic:
        if "التعليم" in normalized and "مجاني" in normalized:
            return "بمعنى أبسط: النص يقرر أن التعليم في مؤسسات الدولة التعليمية يكون مجانيا في مراحله المختلفة."
        if "رئيس الجمهورية" in normalized and "مجلس الشعب" in normalized:
            return "بمعنى أبسط: النص ينظم علاقة أو اختصاصا مرتبطا برئيس الجمهورية ومجلس الشعب كما ورد في المصدر."
        if "المتهم" in normalized or "الدفاع" in normalized or "التقاضي" in normalized:
            return "بمعنى أبسط: النص يتناول ضمانات العدالة أو التقاضي أو حق الدفاع كما ورد في المصدر."
        return "بمعنى أبسط: هذه هي القاعدة أو الحكم كما ورد في النص المرفوع، ولا أضيف إليها معلومات من خارج المستند."

    if "education" in lowered and "free" in lowered:
        return "In plain language, the provision says state educational institutions provide education free of charge across its stages."
    if "president" in lowered and ("people's assembly" in lowered or "assembly" in lowered):
        return "In plain language, this provision regulates a power or procedure involving the President and the legislature, as stated in the source."
    if "accused" in lowered or "defense" in lowered or "trial" in lowered:
        return "In plain language, this passage concerns procedural justice, trial guarantees, or defense rights as stated in the source."
    return "In plain language, this is the rule stated in the uploaded text. I am not adding legal information from outside the document."


def source_ref(index: int, chunk: RetrievedChunk, arabic: bool) -> str:
    article = chunk.metadata.get("article_number")
    page = chunk.metadata.get("page_number") or ("غير محددة" if arabic else "N/A")
    if arabic:
        article_text = f"المادة {article}" if article else "مادة غير محددة"
        return f"المصدر {index}، {article_text}، صفحة {page}"
    article_text = f"Article {article}" if article else "Article N/A"
    return f"Source {index}, {article_text}, Page {page}"


def article_follow_up(article: str | None, arabic: bool) -> str:
    if arabic:
        if article and article.isdigit():
            return f"يمكنك أن تسألني بعد ذلك عن المادة {int(article) + 1} أو تطلب تلخيصا أبسط."
        return "يمكنك أن تسألني عن مادة محددة أو تطلب مقارنة بين مصدرين."
    if article and article.isdigit():
        return f"You can ask me next about Article {int(article) + 1}, or ask for a simpler summary."
    return "You can ask about a specific article or ask me to compare two cited sources."


def build_extractive_answer(query: str, chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return NOT_FOUND_MESSAGE

    requested_article = extract_article_number(query)
    if has_arabic(query):
        if has_article_count_intent(query):
            top = chunks[0]
            article = top.metadata.get("article_number") or "غير محدد"
            document = top.metadata.get("document_name") or "مستند مرفوع"
            page = top.metadata.get("page_number") or "غير محددة"
            return "\n".join(
                [
                    f"أعلى رقم مادة أستطيع تحديده حاليا من المستندات المرفوعة هو المادة {article}.",
                    "",
                    f"المصدر 1: {document}، صفحة {page}:",
                    compact_quote(top.content),
                    "",
                    "إذا أردت، اسألني عن نص هذه المادة أو عن المواد السابقة لها.",
                ]
            )

        if requested_article:
            first_article = chunks[0].metadata.get("article_number")
            first_document = chunks[0].metadata.get("document_name") or "المستند المرفوع"
            first_page = chunks[0].metadata.get("page_number") or "غير محددة"
            lines = [
                f"نعم، وجدت المادة {requested_article} في {first_document}، صفحة {first_page}.",
                "",
                "النص كما ورد في المصدر:",
                "",
            ]
            for index, chunk in enumerate(chunks[:3], start=1):
                document = chunk.metadata.get("document_name") or "مستند مرفوع"
                page = chunk.metadata.get("page_number") or "غير محددة"
                lines.append(f"المصدر {index}: {document}، صفحة {page}")
                lines.append(compact_quote(chunk.content))
                lines.append("")
            lines.append(plain_language_note(chunks[0].content, arabic=True))
            lines.append("")
            lines.append(article_follow_up(first_article, arabic=True))
            return "\n".join(lines).strip()

        if asks_for_simplification(query):
            first = chunks[0]
            document = first.metadata.get("document_name") or "مستند مرفوع"
            page = first.metadata.get("page_number") or "غير محددة"
            article = first.metadata.get("article_number") or "غير محددة"
            return "\n".join(
                [
                    plain_language_note(first.content, arabic=True),
                    "",
                    "النص الذي اعتمدت عليه:",
                    compact_quote(first.content),
                    "",
                    f"المصدر: {document}، المادة {article}، صفحة {page}.",
                ]
            )

        lines = [
            "اطلعت على المقاطع الأقرب لسؤالك داخل المستندات المرفوعة. هذه خلاصة مدعومة بالمصادر:",
            "",
        ]
        for index, chunk in enumerate(chunks[:3], start=1):
            lines.append(f"{index}. {source_ref(index, chunk, arabic=True)}:")
            lines.append(compact_quote(chunk.content))
            lines.append("")
        lines.append("الخلاصة أعلاه مبنية فقط على النصوص المسترجعة من ملفاتك. يمكنك أن تطلب تلخيصا أبسط أو مقارنة بين المصادر.")
        return "\n".join(lines).strip()

    if has_article_count_intent(query):
        top = chunks[0]
        article = top.metadata.get("article_number") or "N/A"
        document = top.metadata.get("document_name") or "Uploaded document"
        page = top.metadata.get("page_number") or "N/A"
        return "\n".join(
            [
                f"The highest article number I can currently identify in the uploaded documents is Article {article}.",
                "",
                f"Source 1: {document}, Page {page}:",
                compact_quote(top.content),
                "",
                "You can ask me for that article's text, a simpler explanation, or the articles immediately before it.",
            ]
        )

    if requested_article:
        first_article = chunks[0].metadata.get("article_number")
        first_document = chunks[0].metadata.get("document_name") or "the uploaded document"
        first_page = chunks[0].metadata.get("page_number") or "N/A"
        lines = [
            f"Yes. I found Article {requested_article} in {first_document}, page {first_page}.",
            "",
            "Here is the text from the source:",
            "",
        ]
        for index, chunk in enumerate(chunks[:3], start=1):
            document = chunk.metadata.get("document_name") or "Uploaded document"
            page = chunk.metadata.get("page_number") or "N/A"
            lines.append(f"Source {index}: {document}, Page {page}")
            lines.append(compact_quote(chunk.content))
            lines.append("")
        lines.append(plain_language_note(chunks[0].content, arabic=False))
        lines.append("")
        lines.append(article_follow_up(first_article, arabic=False))
        return "\n".join(lines).strip()

    if asks_for_simplification(query):
        first = chunks[0]
        document = first.metadata.get("document_name") or "Uploaded document"
        page = first.metadata.get("page_number") or "N/A"
        article = first.metadata.get("article_number") or "N/A"
        return "\n".join(
            [
                plain_language_note(first.content, arabic=False),
                "",
                "Text I relied on:",
                compact_quote(first.content),
                "",
                f"Source: {document}, Article {article}, Page {page}.",
            ]
        )

    lines = [
        "I searched the uploaded documents and found the closest grounded material for your question:",
        "",
    ]
    for index, chunk in enumerate(chunks[:3], start=1):
        lines.append(f"{index}. {source_ref(index, chunk, arabic=False)}:")
        lines.append(compact_quote(chunk.content))
        lines.append("")
    lines.append("This answer is based only on the retrieved text above. You can ask me to simplify it, compare the sources, or focus on a specific article.")
    return "\n".join(lines).strip()


def stream_text(text: str, chunk_size: int = 18):
    for start in range(0, len(text), chunk_size):
        yield text[start : start + chunk_size]
