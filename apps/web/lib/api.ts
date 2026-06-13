import type { ChatMessage, Citation, Conversation, LegalDocument, StreamHandlers } from "@/lib/types";

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8001/api").replace(
  /\/$/,
  "",
);

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text();
    let apiMessage: string | undefined;
    try {
      const payload = JSON.parse(text) as { detail?: string };
      apiMessage = payload.detail;
    } catch {
      apiMessage = undefined;
    }
    throw new Error(apiMessage || text || response.statusText);
  }
  return response.json() as Promise<T>;
}

export async function listDocuments(search?: string) {
  const url = new URL(`${API_BASE}/documents`);
  if (search) url.searchParams.set("search", search);
  return readJson<LegalDocument[]>(await fetch(url));
}

export async function uploadDocument(file: File) {
  const form = new FormData();
  form.append("file", file);
  return readJson<LegalDocument & { chunk_count: number; duplicate: boolean }>(
    await fetch(`${API_BASE}/documents/upload`, {
      method: "POST",
      body: form,
    }),
  );
}

export async function listConversations() {
  return readJson<Conversation[]>(await fetch(`${API_BASE}/conversations`));
}

export async function listMessages(conversationId: string) {
  return readJson<ChatMessage[]>(await fetch(`${API_BASE}/conversations/${conversationId}/messages`));
}

export function documentFileUrl(documentId: string) {
  return `${API_BASE}/documents/${documentId}/file`;
}

export async function streamChat(
  request: { message: string; conversation_id?: string | null; top_k?: number },
  handlers: StreamHandlers,
) {
  const response = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

  if (!response.ok || !response.body) {
    throw new Error((await response.text()) || "Unable to start chat stream.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const handlePayload = (line: string) => {
    if (!line.startsWith("data:")) return;
    const raw = line.slice(5).trim();
    if (!raw) return;
    const event = JSON.parse(raw) as {
      type: string;
      conversation?: Conversation;
      label?: string;
      citations?: Citation[];
      delta?: string;
      conversation_id?: string;
      error?: string;
    };
    if (event.type === "conversation" && event.conversation) handlers.onConversation?.(event.conversation);
    if (event.type === "stage" && event.label) handlers.onStage?.(event.label);
    if (event.type === "citations" && event.citations) handlers.onCitations?.(event.citations);
    if (event.type === "answer_delta" && event.delta) handlers.onDelta?.(event.delta);
    if (event.type === "done" && event.conversation_id) handlers.onDone?.(event.conversation_id);
    if (event.type === "error" && event.error) handlers.onError?.(event.error);
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() || "";
    for (const event of events) {
      for (const line of event.split("\n")) {
        handlePayload(line);
      }
    }
  }

  if (buffer.trim()) {
    for (const line of buffer.split("\n")) {
      handlePayload(line);
    }
  }
}
