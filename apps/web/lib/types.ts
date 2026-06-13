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

export type LocalModelStatus = {
  ollama_running: boolean;
  installed_models: string[];
  target_model: string;
  model_available: boolean;
  llm_provider: string;
  local_model_enabled: boolean;
  ollama_base_url: string;
  error?: string | null;
};

export type ModelPullHandlers = {
  onProgress?: (event: { status: string; completed?: number | null; total?: number | null }) => void;
  onDone?: (model: string) => void;
  onError?: (error: string) => void;
};
