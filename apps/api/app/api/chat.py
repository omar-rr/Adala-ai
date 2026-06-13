from __future__ import annotations

import re
import time
import uuid
from collections.abc import Iterable

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app import db
from app.api.events import sse_event
from app.config import settings
from app.models import ChatRequest, ConversationOut, MessageOut
from app.rag.articles import extract_article_number
from app.rag.extractive import build_extractive_answer, has_arabic, stream_text
from app.rag.llm import stream_answer
from app.rag.prompt import NOT_FOUND_MESSAGE, build_chat_messages, build_messages
from app.rag.retriever import RetrievedChunk, retrieve
from app.security import sanitize_query


router = APIRouter(prefix="/api", tags=["chat"])


STAGES = [
    "Searching legal documents...",
    "Checking exact legal issue in retrieved evidence...",
    "Analyzing relevant articles...",
    "Comparing legal provisions...",
    "Generating grounded response...",
]
STAGE_DELAY_SECONDS = 0.65
TOKEN_DELAY_SECONDS = 0.018


LEGAL_INTENT_TERMS = {
    "article",
    "articles",
    "law",
    "legal",
    "constitution",
    "constitutional",
    "court",
    "ruling",
    "judgment",
    "regulation",
    "contract",
    "rights",
    "obligations",
    "penalty",
    "punishment",
    "crime",
    "due process",
    "defense",
    "trial",
    "source",
    "citation",
    "document",
    "documents",
    "pdf",
    "uploaded",
    "ماده",
    "الماده",
    "مواد",
    "قانون",
    "القانون",
    "دستور",
    "الدستور",
    "لائحه",
    "اللائحه",
    "حكم",
    "احكام",
    "محكمه",
    "قضاء",
    "تقاضي",
    "دفاع",
    "عقد",
    "حق",
    "حقوق",
    "التزامات",
    "عقوبه",
    "جريمه",
    "مصدر",
    "مصادر",
    "مستند",
    "مستندات",
    "وثيقه",
    "وثائق",
    "ملف",
    "ملفات",
    "مرفوع",
    "المرفوعه",
}

FOLLOW_UP_TERMS = {
    "summarize",
    "summary",
    "simplify",
    "explain",
    "explain it",
    "tell me more",
    "compare",
    "continue",
    "what does it mean",
    "what about this",
    "make it simpler",
    "لخص",
    "تلخيص",
    "اشرح",
    "وضح",
    "بسط",
    "ببساطه",
    "قارن",
    "اكمل",
    "ماذا يعني",
    "يعني ايه",
}

META_CHAT_TERMS = {
    "help me write",
    "write a better",
    "phrase this",
    "rephrase",
    "how should i ask",
    "how can i ask",
    "make this question better",
    "better question",
    "prompt",
    "research question",
    "صياغه سؤال",
    "صياغة سؤال",
    "اكتب سؤال",
    "اكتب لي سؤال",
    "ازاي اسال",
    "كيف اسال",
    "حسن السؤال",
}


def normalize_chat_text(message: str) -> str:
    text = message.strip().lower()
    text = text.translate(str.maketrans("أإآٱىة", "اااايه"))
    text = re.sub(r"[^\w\u0600-\u06ff\s]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def contains_phrase(normalized: str, phrases: set[str] | list[str]) -> bool:
    return any(phrase in normalized for phrase in phrases)


def has_retrieval_intent(message: str) -> bool:
    normalized = normalize_chat_text(message)
    if extract_article_number(message):
        return True
    return contains_phrase(normalized, LEGAL_INTENT_TERMS)


def has_follow_up_intent(message: str) -> bool:
    normalized = normalize_chat_text(message)
    return contains_phrase(normalized, FOLLOW_UP_TERMS)


def has_meta_chat_intent(message: str) -> bool:
    normalized = normalize_chat_text(message)
    return contains_phrase(normalized, META_CHAT_TERMS)


def documents_answer(arabic: bool) -> str:
    documents = db.list_documents()
    if not documents:
        if arabic:
            return (
                "لا توجد مستندات مرفوعة حتى الآن. ارفع ملف PDF أولا، وبعدها اسألني عن مادة، "
                "حكم، تعريف، أو مقارنة بين النصوص."
            )
        return (
            "No documents are uploaded yet. Upload a PDF first, then ask me about an article, "
            "a rule, a definition, or a comparison between provisions."
        )

    if arabic:
        lines = ["المستندات المرفوعة حاليا:"]
        for document in documents:
            lines.append(f"- {document['name']} ({document['pages']} صفحة)")
        lines.append("")
        lines.append("يمكنك أن تسألني عن مادة محددة أو تطلب تلخيصا أو مقارنة بين النصوص.")
        return "\n".join(lines)

    lines = ["These documents are currently uploaded:"]
    for document in documents:
        lines.append(f"- {document['name']} ({document['pages']} pages)")
    lines.append("")
    lines.append("You can ask me about a specific article, request a summary, or compare provisions.")
    return "\n".join(lines)


def local_chat_answer(message: str, history: list[dict] | None = None) -> str:
    arabic = has_arabic(message)
    normalized = normalize_chat_text(message)
    recent_assistant = ""
    for item in reversed(history or []):
        if item.get("role") == "assistant":
            recent_assistant = str(item.get("content") or "").strip()
            break

    if arabic:
        if recent_assistant and has_follow_up_intent(message):
            return (
                "أقدر أكمل معك، لكن حتى أظل دقيقا قانونيا أحتاج أن يكون السؤال مرتبطا بمصدر أو مادة محددة. "
                "اكتب مثلا: لخص المادة 20، أو قارن بين المصدرين، أو ما معنى هذه الفقرة؟"
            )
        if "اسمك" in normalized or "مين انت" in normalized or "من انت" in normalized:
            return "أنا adala ai، مساعد دردشة وبحث قانوني للمستندات المصرية التي ترفعها."
        return (
            "أنا معك. أستطيع الدردشة معك ومساعدتك في صياغة الأسئلة، لكن عندما يكون السؤال قانونيا "
            "سأعتمد فقط على المستندات المرفوعة. جرّب أن تسألني عن مادة محددة، أو اطلب تلخيص مستند، "
            "أو قل لي ما الذي تريد استخراجه من الملفات."
        )

    if recent_assistant and has_follow_up_intent(message):
        return (
            "I can continue from the previous answer, but for legal accuracy I need the follow-up "
            "to point at a cited article, source, or document. Try: summarize Article 20, explain Source 1, "
            "or compare the cited sources."
        )
    if "your name" in normalized or "who are you" in normalized:
        return "I'm adala ai, a conversational legal research assistant for your uploaded Egyptian documents."
    return (
        "I'm here with you. I can chat, help you shape better questions, and research the uploaded legal PDFs. "
        "For legal answers, I will use only your uploaded documents and cite the sources I rely on."
    )


def direct_chat_answer(message: str) -> str | None:
    normalized = normalize_chat_text(message)
    arabic = has_arabic(message)

    greetings = {
        "hi",
        "hello",
        "hey",
        "hi there",
        "hello there",
        "good morning",
        "good afternoon",
        "good evening",
        "السلام عليكم",
        "مرحبا",
        "اهلا",
        "اهلا وسهلا",
        "هاي",
        "هلا",
        "صباح الخير",
        "مساء الخير",
    }
    thanks = {
        "thanks",
        "thank you",
        "thx",
        "ok thanks",
        "تمام",
        "شكرا",
        "شكرًا",
        "متشكر",
        "مشكور",
        "تسلم",
    }

    if normalized in greetings:
        if arabic:
            return (
                "أهلا، أنا adala ai. أقدر أدردش معك وأبحث داخل ملفاتك القانونية المرفوعة فقط. "
                "اسألني مثلا: ما هي المادة 20؟ أو ما أعلى مادة موجودة؟"
            )
        return (
            "Hi, I'm adala ai. I can chat with you and answer questions from your uploaded "
            "Egyptian legal documents. Try asking: What is Article 20? or What documents are uploaded?"
        )

    if normalized in thanks:
        return "على الرحب والسعة. اسألني عن أي مادة أو مستند مرفوع." if arabic else (
            "You're welcome. Ask me about any uploaded document or article when you're ready."
        )

    if normalized in {"how are you", "how are you doing"}:
        return (
            "I'm ready and watching your uploaded legal library. What would you like to look up?"
        )
    if normalized in {"عامل ايه", "ازيك", "كيف حالك"}:
        return "أنا جاهز لمساعدتك في البحث داخل المستندات المرفوعة. ما السؤال الذي تريد أن نبدأ به؟"

    document_phrases = [
        "what documents are uploaded",
        "which documents are uploaded",
        "list documents",
        "list uploaded documents",
        "uploaded documents",
        "uploaded files",
        "which files are uploaded",
        "what files are uploaded",
        "ما المستندات المرفوعه",
        "ما الوثائق المرفوعه",
        "ما الملفات المرفوعه",
        "اعرض المستندات",
        "اعرض الملفات",
        "المستندات المرفوعه",
        "الملفات المرفوعه",
    ]
    if any(phrase in normalized for phrase in document_phrases):
        return documents_answer(arabic)

    help_phrases = [
        "what can you do",
        "how do i use you",
        "how do i use this",
        "who are you",
        "what are you",
        "ماذا تستطيع",
        "ما الذي تستطيع",
        "تقدر تعمل ايه",
        "كيف استخدم",
        "ساعدني",
        "من انت",
        "مين انت",
    ]
    if normalized == "help" or any(phrase in normalized for phrase in help_phrases):
        if arabic:
            return (
                "أنا adala ai، مساعد بحث قانوني للمستندات المصرية التي ترفعها.\n\n"
                "أستطيع أن أساعدك في:\n"
                "- العثور على مادة برقمها مثل: ما هي المادة 101؟\n"
                "- تلخيص مواد أو صفحات من المستندات.\n"
                "- مقارنة النصوص والحقوق والالتزامات.\n"
                "- فتح المصادر والصفحات المرتبطة بالإجابة.\n\n"
                "للمسائل القانونية، سأعتمد فقط على النصوص الموجودة في ملفاتك المرفوعة."
            )
        return (
            "I'm adala ai, a legal research assistant for the Egyptian documents you upload.\n\n"
            "I can help you:\n"
            "- Find an article by number, like: What is Article 101?\n"
            "- Summarize articles or pages from uploaded PDFs.\n"
            "- Compare provisions, rights, and obligations.\n"
            "- Open cited sources and pages from the answer.\n\n"
            "For legal questions, I only use the text found in your uploaded files."
        )

    return None


def chunks_from_previous_citations(history: list[dict]) -> list[RetrievedChunk]:
    for item in reversed(history):
        if item.get("role") != "assistant":
            continue
        citations = item.get("citations") or []
        chunks: list[RetrievedChunk] = []
        for citation in citations:
            quote = str(citation.get("quote") or "").strip()
            if not quote:
                continue
            chunks.append(
                RetrievedChunk(
                    content=quote,
                    score=float(citation.get("score") or 1.0),
                    metadata={
                        "document_id": citation.get("document_id"),
                        "document_name": citation.get("document_name"),
                        "page_number": citation.get("page_number"),
                        "article_number": citation.get("article_number") or "",
                        "chunk_id": citation.get("chunk_id"),
                        "original_text": quote,
                    },
                )
            )
        if chunks:
            return chunks
    return []


def conversation_title(message: str) -> str:
    title = " ".join(message.strip().split())
    return title[:64] or "Legal research chat"


def citation_payload(chunks: list[RetrievedChunk]) -> list[dict]:
    citations = []
    for index, chunk in enumerate(chunks, start=1):
        metadata = chunk.metadata
        quote = chunk.content.strip()
        if len(quote) > 900:
            quote = quote[:897].rstrip() + "..."
        article = metadata.get("article_number") or None
        citations.append(
            {
                "source_index": index,
                "document_id": metadata.get("document_id"),
                "document_name": metadata.get("document_name"),
                "page_number": int(metadata.get("page_number") or 1),
                "article_number": article,
                "chunk_id": metadata.get("chunk_id"),
                "quote": quote,
                "score": round(float(chunk.score), 4),
            }
        )
    return citations


def source_block(citations: list[dict]) -> str:
    if not citations:
        return ""
    lines = ["", "Sources:"]
    for citation in citations:
        lines.extend(
            [
                f"Source {citation['source_index']}:",
                str(citation["document_name"]),
                f"Article {citation['article_number'] or 'N/A'}",
                f"Page {citation['page_number']}",
            ]
        )
    return "\n".join(lines)


def stream_chat_response(request: ChatRequest) -> Iterable[str]:
    user_message = sanitize_query(request.message)
    conversation_id = request.conversation_id or uuid.uuid4().hex
    conversation = db.get_conversation(conversation_id)
    if not conversation:
        conversation = db.create_conversation(conversation_id, conversation_title(user_message))
        history: list[dict] = []
    else:
        history = db.list_messages(conversation_id)

    db.add_message(uuid.uuid4().hex, conversation_id, "user", user_message)
    yield sse_event({"type": "conversation", "conversation": conversation})

    direct_answer = direct_chat_answer(user_message)
    if direct_answer:
        generated = []
        yield sse_event({"type": "citations", "citations": []})
        for token in stream_text(direct_answer):
            generated.append(token)
            yield sse_event({"type": "answer_delta", "delta": token})
            time.sleep(TOKEN_DELAY_SECONDS)
        final_answer = "".join(generated).strip()
        db.add_message(uuid.uuid4().hex, conversation_id, "assistant", final_answer, [])
        yield sse_event({"type": "done", "conversation_id": conversation_id})
        return

    previous_chunks = chunks_from_previous_citations(history) if has_follow_up_intent(user_message) else []
    if not previous_chunks and (has_meta_chat_intent(user_message) or not has_retrieval_intent(user_message)):
        generated = []
        yield sse_event({"type": "citations", "citations": []})
        if settings.llm_provider.lower() != "extractive":
            try:
                for token in stream_answer(build_chat_messages(user_message, history)):
                    generated.append(token)
                    yield sse_event({"type": "answer_delta", "delta": token})
                    time.sleep(TOKEN_DELAY_SECONDS)
            except Exception:
                generated.clear()
                for token in stream_text(local_chat_answer(user_message, history)):
                    generated.append(token)
                    yield sse_event({"type": "answer_delta", "delta": token})
                    time.sleep(TOKEN_DELAY_SECONDS)
        else:
            for token in stream_text(local_chat_answer(user_message, history)):
                generated.append(token)
                yield sse_event({"type": "answer_delta", "delta": token})
                time.sleep(TOKEN_DELAY_SECONDS)
        final_answer = "".join(generated).strip()
        db.add_message(uuid.uuid4().hex, conversation_id, "assistant", final_answer, [])
        yield sse_event({"type": "done", "conversation_id": conversation_id})
        return

    if previous_chunks:
        chunks = previous_chunks
        yield sse_event({"type": "stage", "label": "Using the previous cited sources..."})
        time.sleep(STAGE_DELAY_SECONDS)
    else:
        yield sse_event({"type": "stage", "label": STAGES[0]})
        time.sleep(STAGE_DELAY_SECONDS)
        try:
            chunks = retrieve(user_message, top_k=request.top_k)
        except Exception as exc:
            yield sse_event({"type": "error", "error": str(exc)})
            db.add_message(uuid.uuid4().hex, conversation_id, "assistant", NOT_FOUND_MESSAGE, [])
            yield sse_event({"type": "answer_delta", "delta": NOT_FOUND_MESSAGE})
            yield sse_event({"type": "done", "conversation_id": conversation_id})
            return
    citations = citation_payload(chunks)
    yield sse_event({"type": "citations", "citations": citations})

    if not chunks:
        answer = NOT_FOUND_MESSAGE
        db.add_message(uuid.uuid4().hex, conversation_id, "assistant", answer, [])
        yield sse_event({"type": "stage", "label": STAGES[1]})
        time.sleep(STAGE_DELAY_SECONDS)
        yield sse_event({"type": "stage", "label": STAGES[-1]})
        time.sleep(STAGE_DELAY_SECONDS)
        yield sse_event({"type": "answer_delta", "delta": answer})
        yield sse_event({"type": "done", "conversation_id": conversation_id})
        return

    yield sse_event({"type": "stage", "label": STAGES[1]})
    time.sleep(STAGE_DELAY_SECONDS)
    yield sse_event({"type": "stage", "label": STAGES[2]})
    time.sleep(STAGE_DELAY_SECONDS)
    yield sse_event({"type": "stage", "label": STAGES[3]})
    time.sleep(STAGE_DELAY_SECONDS)
    yield sse_event({"type": "stage", "label": STAGES[4]})
    time.sleep(STAGE_DELAY_SECONDS)

    generated = []
    if settings.llm_provider.lower() != "extractive" and settings.rag_llm_enabled:
        messages = build_messages(user_message, chunks)
        try:
            for token in stream_answer(messages):
                generated.append(token)
                yield sse_event({"type": "answer_delta", "delta": token})
                time.sleep(TOKEN_DELAY_SECONDS)
        except Exception:
            fallback = build_extractive_answer(user_message, chunks)
            generated.clear()
            for token in stream_text(fallback):
                generated.append(token)
                yield sse_event({"type": "answer_delta", "delta": token})
                time.sleep(TOKEN_DELAY_SECONDS)
    else:
        for token in stream_text(build_extractive_answer(user_message, chunks)):
            generated.append(token)
            yield sse_event({"type": "answer_delta", "delta": token})
            time.sleep(TOKEN_DELAY_SECONDS)

    citations_text = source_block(citations)
    if citations_text:
        generated.append(citations_text)
        yield sse_event({"type": "answer_delta", "delta": citations_text})

    final_answer = "".join(generated).strip()
    db.add_message(uuid.uuid4().hex, conversation_id, "assistant", final_answer, citations)
    yield sse_event({"type": "done", "conversation_id": conversation_id})


@router.post("/chat")
def chat(request: ChatRequest) -> StreamingResponse:
    return StreamingResponse(
        stream_chat_response(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/conversations", response_model=list[ConversationOut])
def conversations() -> list[dict]:
    return db.list_conversations()


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def messages(conversation_id: str) -> list[dict]:
    return db.list_messages(conversation_id)
