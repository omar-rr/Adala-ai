from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import math
import re
import unicodedata
from pathlib import Path

from app import db
from app.config import settings
from app.rag.articles import extract_article_number
from app.rag.ingestion import candidate_pages_for_article, ocr_index_pages


@dataclass(frozen=True)
class RetrievedChunk:
    content: str
    score: float
    metadata: dict


def _score_from_distance(distance: float) -> float:
    return max(0.0, min(1.0, 1.0 / (1.0 + distance)))


def normalize_for_search(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    text = re.sub(r"[إأٱ]", "ا", text)
    text = text.replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي")
    text = text.replace("ـ", "")
    text = re.sub(r"[\u064B-\u065F]", "", text)
    return text


def terms_for(text: str) -> list[str]:
    normalized = normalize_for_search(text)
    variants = [normalized]
    if "آ" in normalized:
        variants.extend([normalized.replace("آ", "ا"), normalized.replace("آ", "ك")])
    terms: list[str] = []
    seen: set[str] = set()
    for variant in variants:
        for term in re.findall(r"[a-z0-9_]+|[\u0621-\u064A\u0660-\u0669]+", variant, re.IGNORECASE):
            if len(term) < 2:
                continue
            term_variants = [term]
            if re.search(r"[\u0600-\u06FF]", term):
                for prefix in ("وال", "بال", "كال", "فال", "لل", "ال", "و", "ف", "ب", "ل"):
                    if term.startswith(prefix) and len(term) - len(prefix) >= 2:
                        term_variants.append(term[len(prefix) :])
                        break
            for term_variant in term_variants:
                if term_variant not in seen:
                    terms.append(term_variant)
                    seen.add(term_variant)
    return terms


def numeric_article(value: str | None) -> int | None:
    if not value:
        return None
    if not str(value).isdigit():
        return None
    return int(str(value))


def result_from_row(row: dict, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        content=str(row["text"]),
        score=score,
        metadata={
            "document_id": row["document_id"],
            "document_name": row["document_name"],
            "page_number": row["page_number"],
            "article_number": row["article_number"] or "",
            "chunk_id": row["id"],
            "original_text": row["text"],
        },
    )


TERM_SYNONYMS = {
    "labor": ["work", "worker", "employee", "employment", "عمل", "عامل", "عمال", "العامل", "العمل"],
    "employee": ["worker", "labor", "employment", "عامل", "عمال", "موظف", "العمل"],
    "employment": ["labor", "work", "employee", "عمل", "عمال", "عامل"],
    "termination": ["terminate", "terminated", "dismissal", "end", "ending", "انهاء", "فصل", "فسخ", "انتهاء", "انقضاء"],
    "terminate": ["termination", "dismissal", "انهاء", "فصل", "فسخ"],
    "contract": ["agreement", "عقد", "العقد", "عقود", "اتفاق"],
    "constitution": ["دستور", "الدستور"],
    "due": ["right", "rights", "guarantee", "ضمان", "ضمانات", "حق", "حقوق"],
    "process": ["procedure", "trial", "court", "defense", "اجراءات", "تقاضي", "محاكمه", "دفاع", "قضاء"],
    "trial": ["court", "defense", "محاكمه", "محاكمات", "قضاء", "دفاع"],
    "defense": ["trial", "court", "دفاع", "محاكمه", "تقاضي"],
    "انهاء": ["فصل", "فسخ", "انتهاء", "انقضاء", "termination", "terminate"],
    "فصل": ["انهاء", "فسخ", "termination", "dismissal"],
    "عقد": ["العقد", "عقود", "contract", "agreement"],
    "عمل": ["العمل", "عامل", "عمال", "labor", "employee", "employment"],
    "دستور": ["الدستور", "constitution"],
    "تقاضي": ["محاكمه", "دفاع", "اجراءات", "قضاء", "due", "process"],
    "محاكمه": ["تقاضي", "دفاع", "قضاء", "trial", "process"],
}

PHRASE_SYNONYMS = {
    "due process": ["محاكمه", "عادله", "دفاع", "تقاضي", "اجراءات", "قانون", "حقوق", "ضمانات"],
    "employee termination": ["انهاء", "فصل", "فسخ", "عقد", "عمل", "عامل", "عمال"],
    "labor contract": ["عقد", "عمل", "عامل", "عمال"],
    "انهاء عقد العمل": ["فصل", "فسخ", "انتهاء", "عقد", "عمل", "عامل", "عمال"],
}

CONCEPT_GROUPS = {
    "termination": ["termination", "terminate", "dismissal", "انهاء", "فصل", "فسخ", "انتهاء", "انقضاء"],
    "labor": ["labor", "employment", "work", "عمل", "العمل"],
    "worker": [
        "employee",
        "worker",
        "عامل",
        "عمال",
        "العامل",
        "العاملون",
        "موظف",
        "موظفين",
        "وظيفه",
        "وظائف",
        "الوظائف",
    ],
    "contract": ["contract", "agreement", "عقد", "العقد", "عقود", "اتفاق"],
    "due_process": [
        "due",
        "process",
        "trial",
        "defense",
        "court",
        "محاكمه",
        "تقاضي",
        "دفاع",
        "قضاء",
        "قضائي",
        "متهم",
        "برئ",
        "بريء",
        "حريه",
    ],
}

DUE_PROCESS_WEIGHTS = {
    "تقاضي": 2.0,
    "محاكمه": 1.8,
    "دفاع": 1.7,
    "ضمانات": 1.5,
    "متهم": 1.4,
    "برئ": 1.3,
    "بريء": 1.3,
    "قضاء": 1.2,
    "قضائي": 1.2,
    "قاضي": 1.1,
    "محام": 1.1,
    "عقوبه": 1.0,
    "جريمه": 1.0,
    "دعوي": 0.9,
    "حكم": 0.8,
    "حقوق": 0.8,
    "حريات": 0.8,
    "قانون": 0.7,
}

DUE_PROCESS_ANCHORS = {
    "تقاضي",
    "محاكمه",
    "متهم",
    "قضاء",
    "قضائي",
    "قاضي",
    "محام",
    "عقوبه",
    "جريمه",
    "دعوي",
}

GENERIC_QUERY_TERMS = {
    "a",
    "about",
    "answer",
    "article",
    "articles",
    "based",
    "book",
    "books",
    "document",
    "documents",
    "does",
    "find",
    "for",
    "from",
    "give",
    "in",
    "is",
    "law",
    "legal",
    "locate",
    "me",
    "number",
    "of",
    "on",
    "penalty",
    "punishment",
    "rule",
    "say",
    "section",
    "source",
    "summarize",
    "tell",
    "the",
    "uploaded",
    "what",
    "which",
    "ما",
    "ماهي",
    "ماهو",
    "هي",
    "هو",
    "في",
    "من",
    "عن",
    "على",
    "الي",
    "إلى",
    "الى",
    "هل",
    "اذكر",
    "اشرح",
    "لخص",
    "تلخيص",
    "المرفوعه",
    "المرفوعة",
    "المستندات",
    "المستند",
    "الوثائق",
    "الوثيقه",
    "الوثيقة",
    "قانون",
    "القانون",
    "القانونيه",
    "القانونية",
    "ماده",
    "الماده",
    "مادة",
    "المادة",
    "نص",
    "حكم",
    "احكام",
    "أحكام",
    "جزاء",
    "العقوبه",
    "عقوبه",
    "عقوبة",
    "عقوبات",
    "عقاب",
    "شروط",
    "حقوق",
    "حق",
    "واجبات",
    "التزامات",
    "مصدر",
    "مصادر",
}

SPECIFIC_TERM_SYNONYMS = {
    "اغتصاب": {"اغتصاب", "مواقعه", "انثي", "انثى", "أنثى", "رضاها", "هتك"},
    "rape": {"rape", "rapist", "sexual", "assault", "اغتصاب", "انثي", "انثى", "رضاها", "هتك"},
}

PUNISHMENT_QUERY_TERMS = {
    "penalty",
    "punishment",
    "sentence",
    "عقوبه",
    "العقوبه",
    "عقوبات",
    "عقاب",
    "جزاء",
}

ARTICLE_COUNT_TERMS = {
    "maximum",
    "highest",
    "last",
    "latest",
    "max",
    "article",
    "articles",
    "know",
    "اكبر",
    "أكبر",
    "اعلي",
    "أعلى",
    "اخر",
    "آخر",
    "اقصي",
    "أقصى",
    "ماده",
    "مادة",
    "الماده",
    "المادة",
    "مواد",
}


def expanded_query_terms(query: str) -> list[str]:
    normalized_query = normalize_for_search(query)
    terms = terms_for(query)
    expanded = list(terms)
    for phrase, synonyms in PHRASE_SYNONYMS.items():
        if normalize_for_search(phrase) in normalized_query:
            expanded.extend(synonyms)
    for term in terms:
        expanded.extend(TERM_SYNONYMS.get(term, []))
    return terms_for(" ".join(expanded))


def specific_term_groups_for(query: str) -> list[set[str]]:
    terms = terms_for(query)
    term_set = set(terms)
    has_punishment_intent = bool(term_set & PUNISHMENT_QUERY_TERMS)
    groups: list[set[str]] = []
    for term in terms:
        if term in GENERIC_QUERY_TERMS:
            continue
        if re.fullmatch(r"\d+[a-z]?", term, re.IGNORECASE):
            continue
        is_arabic = bool(re.search(r"[\u0600-\u06FF]", term))
        if (is_arabic and len(term) < 3) or (not is_arabic and len(term) < 4):
            continue
        if not has_punishment_intent and term not in SPECIFIC_TERM_SYNONYMS:
            continue
        groups.append(set(terms_for(" ".join(SPECIFIC_TERM_SYNONYMS.get(term, {term})))))

    deduped: list[set[str]] = []
    seen: set[tuple[str, ...]] = set()
    for group in groups:
        signature = tuple(sorted(group))
        if signature not in seen:
            deduped.append(group)
            seen.add(signature)
    return deduped


def normalized_group(name: str) -> set[str]:
    return set(terms_for(" ".join(CONCEPT_GROUPS[name])))


def required_groups_for(query: str) -> list[set[str]]:
    normalized_query = normalize_for_search(query)
    terms = set(terms_for(query))
    required: list[set[str]] = []

    termination_group = normalized_group("termination")
    labor_group = normalized_group("labor")
    worker_group = normalized_group("worker")
    contract_group = normalized_group("contract")
    due_process_group = normalized_group("due_process")

    if "employee termination" in normalized_query:
        required.extend([termination_group, worker_group])
    elif "labor contract" in normalized_query or "انهاء عقد العمل" in normalized_query:
        required.extend([termination_group, labor_group, contract_group])
    elif terms & contract_group and terms & termination_group:
        required.extend([termination_group, contract_group])
    elif terms & worker_group and terms & termination_group:
        required.extend([termination_group, worker_group])
    elif terms & termination_group:
        required.append(termination_group)
    if "due process" in normalized_query or terms & {"تقاضي", "محاكمه", "دفاع"}:
        required.append(due_process_group)
    return required


def has_due_process_intent(query: str) -> bool:
    normalized_query = normalize_for_search(query)
    terms = set(terms_for(query))
    return bool(
        "due process" in normalized_query
        or terms & {"تقاضي", "محاكمه", "محاكمات"}
        or (terms & {"دفاع"} and terms & {"حق", "حقوق", "قضاء", "تقاضي", "متهم"})
    )


def has_article_count_intent(query: str) -> bool:
    terms = set(terms_for(query))
    english = bool(terms & {"maximum", "highest", "last", "latest", "max"}) and bool(
        terms & {"article", "articles"}
    )
    arabic = bool(terms & {"اكبر", "اعلي", "اخر", "اقصي"}) and bool(
        terms & {"ماده", "مادة", "الماده", "المادة", "مواد"}
    )
    loose_user_phrase = bool(terms & {"maximum", "highest", "max"}) and "know" in terms
    return english or arabic or loose_user_phrase


def token_similarity(query_term: str, chunk_term: str) -> float:
    if query_term == chunk_term:
        return 1.0
    if len(query_term) >= 4 and len(chunk_term) >= 4:
        if query_term.startswith(chunk_term[:4]) or chunk_term.startswith(query_term[:4]):
            return 0.72
        if query_term in chunk_term or chunk_term in query_term:
            return 0.68
    if abs(len(query_term) - len(chunk_term)) <= 2:
        ratio = SequenceMatcher(None, query_term, chunk_term).ratio()
        if ratio >= 0.84:
            return ratio * 0.62
    return 0.0


def supports_specific_terms(query: str, chunk_terms: set[str]) -> bool:
    groups = specific_term_groups_for(query)
    if not groups:
        return True
    for group in groups:
        if group & chunk_terms:
            return True
    return False


def document_relevance(query: str, document_name: str) -> float:
    query_terms = set(terms_for(query))
    document_terms = set(terms_for(document_name))
    score = 0.0
    if query_terms and document_terms:
        score += min(0.12, 0.03 * len(query_terms & document_terms))
    normalized_query = normalize_for_search(query)
    normalized_name = normalize_for_search(document_name)
    if ("constitution" in normalized_query or "دستور" in normalized_query) and (
        "constitution" in normalized_name or "دستور" in normalized_name
    ):
        score += 0.2
    if ("labor" in normalized_query or "عمل" in normalized_query) and (
        "labor" in normalized_name or "عمل" in normalized_name
    ):
        score += 0.2
    return score


def retrieve_exact_article(query: str, article_number: str, top_k: int) -> list[RetrievedChunk]:
    rows = db.find_chunks_by_article(article_number)
    if not rows and settings.ocr_enabled:
        rows = retrieve_exact_article_with_lazy_ocr(article_number)
    if not rows:
        return []

    ranked: list[RetrievedChunk] = []
    for row in rows:
        score = min(1.0, 0.82 + document_relevance(query, str(row["document_name"])))
        ranked.append(result_from_row(row, score))
    ranked.sort(
        key=lambda item: (
            item.score,
            -int(item.metadata.get("page_number") or 0),
            str(item.metadata.get("document_name") or ""),
        ),
        reverse=True,
    )
    return ranked[:top_k]


def document_needs_lazy_ocr(document: dict, requested_article: str | None = None) -> bool:
    article_numbers = [numeric_article(value) for value in db.list_article_numbers_for_document(document["id"])]
    numeric_articles = [value for value in article_numbers if value is not None]
    if not numeric_articles:
        return True
    requested = numeric_article(requested_article)
    return requested is not None and requested > max(numeric_articles)


def document_needs_highest_article_ocr(document: dict) -> bool:
    article_numbers = [numeric_article(value) for value in db.list_article_numbers_for_document(document["id"])]
    numeric_articles = [value for value in article_numbers if value is not None]
    if not numeric_articles:
        return True
    return max(numeric_articles) >= 220


def retrieve_exact_article_with_lazy_ocr(article_number: str) -> list[dict]:
    requested = numeric_article(article_number)
    if requested is None:
        return []

    for document in db.list_documents():
        if not document_needs_lazy_ocr(document, article_number):
            continue
        path = Path(document["path"])
        if not path.exists():
            continue
        for page_number in candidate_pages_for_article(article_number, int(document["pages"] or 0)):
            ocr_index_pages(document["id"], document["name"], path, [page_number])
            rows = db.find_chunks_by_article(article_number)
            if rows:
                return rows
    return []


def retrieve_highest_articles(top_k: int) -> list[RetrievedChunk]:
    if settings.ocr_enabled:
        for document in db.list_documents():
            if not document_needs_highest_article_ocr(document):
                continue
            path = Path(document["path"])
            if not path.exists():
                continue
            pages = int(document["pages"] or 0)
            candidate_pages = list(range(max(1, pages - 2), pages + 1))
            ocr_index_pages(document["id"], document["name"], path, candidate_pages)

    rows = db.find_highest_article_chunks(limit=max(top_k * 4, 8))
    if not rows:
        return []
    return [result_from_row(rows[0], 1.0)]


def weighted_term_score(weighted_terms: dict[str, float], chunk_terms: set[str]) -> float:
    total = 0.0
    for wanted, weight in weighted_terms.items():
        if wanted in chunk_terms:
            total += weight
            continue
        best = max((token_similarity(wanted, chunk_term) for chunk_term in chunk_terms), default=0.0)
        if best >= 0.68:
            total += weight * best
    return total


def retrieve_due_process(query: str, top_k: int) -> list[RetrievedChunk]:
    ranked: list[RetrievedChunk] = []
    query_terms = set(terms_for(query))
    office_terms = {"رئيس", "رييس", "جمهوريه", "وزير", "وزراء", "minister", "president"}
    office_query = bool(query_terms & office_terms)
    for row in db.list_searchable_chunks():
        chunk_terms = set(terms_for(str(row["text"])))
        if not chunk_terms:
            continue
        if not any(
            anchor in chunk_terms
            or any(token_similarity(anchor, chunk_term) >= 0.68 for chunk_term in chunk_terms)
            for anchor in DUE_PROCESS_ANCHORS
        ):
            continue
        raw_score = weighted_term_score(DUE_PROCESS_WEIGHTS, chunk_terms)
        if raw_score < 1.5:
            continue
        boost = 0.0
        if "تقاضي" in chunk_terms:
            boost += 0.28
        if "دفاع" in chunk_terms:
            boost += 0.24
        if "متهم" in chunk_terms:
            boost += 0.16
        if chunk_terms & {"عقوبه", "جريمه"} and chunk_terms & {"قضائي", "حكم"}:
            boost += 0.14
        if chunk_terms & {"حقوق", "حريات"} and chunk_terms & {"قضاء", "قضائي"}:
            boost += 0.12
        penalty = 0.0
        if not office_query and chunk_terms & office_terms:
            penalty += 0.45
        score = min(1.0, max(0.0, (raw_score / 7.5) + boost + document_relevance(query, str(row["document_name"])) - penalty))
        ranked.append(result_from_row(row, score))
    ranked.sort(key=lambda item: item.score, reverse=True)
    return ranked[:top_k]


def retrieve_local(query: str, top_k: int) -> list[RetrievedChunk]:
    if has_due_process_intent(query):
        due_process_results = retrieve_due_process(query, top_k)
        if due_process_results:
            return due_process_results

    query_terms = expanded_query_terms(query)
    if not query_terms:
        return []
    query_set = set(query_terms)
    required_groups = required_groups_for(query)

    scored: list[RetrievedChunk] = []
    for row in db.list_searchable_chunks():
        chunk_terms = terms_for(str(row["text"]))
        if not chunk_terms:
            continue
        chunk_set = set(chunk_terms)
        if not supports_specific_terms(query, chunk_set):
            continue
        if required_groups and any(not (group & chunk_set) for group in required_groups):
            continue
        matched_weight = 0.0
        matched_terms = 0
        for query_term in query_set:
            best = 0.0
            for chunk_term in chunk_set:
                best = max(best, token_similarity(query_term, chunk_term))
                if best >= 1.0:
                    break
            if best > 0:
                matched_weight += best
                matched_terms += 1
        if matched_terms == 0:
            continue
        frequency = sum(chunk_terms.count(term) for term in query_set & chunk_set)
        coverage = matched_weight / max(1, len(query_set))
        density = frequency / math.sqrt(len(chunk_terms))
        score = min(1.0, (coverage * 0.88) + (density * 0.06))
        if score < settings.min_relevance:
            continue
        scored.append(result_from_row(row, score))

    scored.sort(key=lambda item: item.score, reverse=True)
    return scored[:top_k]


def retrieve_chroma(query: str, top_k: int) -> list[RetrievedChunk]:
    try:
        from app.rag.vectorstore import get_vectorstore
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "VECTOR_BACKEND=chroma requires langchain-chroma and embedding dependencies."
        ) from exc

    store = get_vectorstore()
    search_k = max(top_k * 4, top_k)
    try:
        raw = store.similarity_search_with_relevance_scores(query, k=search_k)
        pairs = [(doc, float(score)) for doc, score in raw]
    except Exception:
        raw_with_distance = store.similarity_search_with_score(query, k=search_k)
        pairs = [(doc, _score_from_distance(float(distance))) for doc, distance in raw_with_distance]

    results: list[RetrievedChunk] = []
    for doc, score in pairs:
        if score < settings.min_relevance:
            continue
        if not supports_specific_terms(query, set(terms_for(doc.page_content))):
            continue
        metadata = dict(doc.metadata or {})
        results.append(RetrievedChunk(content=doc.page_content, score=score, metadata=metadata))
    return results[:top_k]


def retrieve(query: str, top_k: int | None = None) -> list[RetrievedChunk]:
    k = top_k or settings.top_k
    article_number = extract_article_number(query)
    if article_number:
        return retrieve_exact_article(query, article_number, k)
    if has_article_count_intent(query):
        return retrieve_highest_articles(k)
    if settings.vector_backend.lower() == "chroma":
        return retrieve_chroma(query, k)
    return retrieve_local(query, k)


def format_context(chunks: list[RetrievedChunk]) -> str:
    blocks = []
    for index, chunk in enumerate(chunks, start=1):
        article = chunk.metadata.get("article_number") or "N/A"
        blocks.append(
            "\n".join(
                [
                    f"[SOURCE {index}]",
                    f"document_id: {chunk.metadata.get('document_id')}",
                    f"document_name: {chunk.metadata.get('document_name')}",
                    f"page: {chunk.metadata.get('page_number')}",
                    f"article: {article}",
                    f"chunk_id: {chunk.metadata.get('chunk_id')}",
                    "text:",
                    chunk.content,
                ]
            )
        )
    return "\n\n---\n\n".join(blocks)
