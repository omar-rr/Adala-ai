export type LegalDocument = {
  id: string;
  name: string;
  pages: number;
  created_at: string;
};

export type Conversation = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type Citation = {
  source_index: number;
  document_id: string;
  document_name: string;
  page_number: number;
  article_number: string | null;
  chunk_id: string;
  quote: string;
  score: number;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  created_at?: string;
};

export type StreamHandlers = {
  onConversation?: (conversation: Conversation) => void;
  onStage?: (label: string) => void;
  onCitations?: (citations: Citation[]) => void;
  onDelta?: (delta: string) => void;
  onDone?: (conversationId: string) => void;
  onError?: (error: string) => void;
};

