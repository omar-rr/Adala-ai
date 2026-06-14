"use client";

import { AnimatePresence, motion } from "framer-motion";
import {
  BookOpen,
  Bot,
  CheckCircle2,
  Cpu,
  Download,
  ExternalLink,
  FileText,
  Loader2,
  MessageSquareText,
  Paperclip,
  Plus,
  RefreshCcw,
  Scale,
  Search,
  SendHorizontal,
  ShieldCheck,
  Sparkles,
  Upload,
  X,
} from "lucide-react";
import * as React from "react";

import { PdfViewer } from "@/components/pdf-viewer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  enableLocalModel,
  getLocalModelStatus,
  listConversations,
  listDocuments,
  listMessages,
  streamChat,
  streamLocalModelPull,
  supportsLocalModelSetupClient,
  uploadDocument,
} from "@/lib/api";
import type { ChatMessage, Citation, Conversation, LegalDocument, LocalModelStatus } from "@/lib/types";
import { cn, formatArticle, isArabic } from "@/lib/utils";

const suggestions = [
  "ما هي المادة 20؟",
  "What is Article 247?",
  "What is the highest article available?",
  "ما أهم الحقوق والحريات في المستندات؟",
];

const LOCAL_MODEL = "qwen3:1.7b";

type UploadState = "idle" | "uploading" | "done" | "error";
type ModelProgress = {
  status: string;
  completed?: number | null;
  total?: number | null;
  error?: string | null;
};

export function LegalAssistantApp() {
  const [documents, setDocuments] = React.useState<LegalDocument[]>([]);
  const [conversations, setConversations] = React.useState<Conversation[]>([]);
  const [messages, setMessages] = React.useState<ChatMessage[]>([]);
  const [conversationId, setConversationId] = React.useState<string | null>(null);
  const [query, setQuery] = React.useState("");
  const [documentSearch, setDocumentSearch] = React.useState("");
  const [selectedCitation, setSelectedCitation] = React.useState<Citation | null>(() => {
    if (typeof window === "undefined") return null;
    const params = new URLSearchParams(window.location.search);
    const documentId = params.get("doc");
    const pageNumber = Number(params.get("page") || "1");
    const chunkId = params.get("chunk") || "";
    if (!documentId) return null;
    return {
      source_index: 1,
      document_id: documentId,
      document_name: "Linked document",
      page_number: Number.isFinite(pageNumber) ? pageNumber : 1,
      article_number: null,
      chunk_id: chunkId,
      quote: "",
      score: 0,
    };
  });
  const [stages, setStages] = React.useState<string[]>([]);
  const [isStreaming, setIsStreaming] = React.useState(false);
  const [uploadState, setUploadState] = React.useState<UploadState>("idle");
  const [statusText, setStatusText] = React.useState<string | null>(null);
  const [modelStatus, setModelStatus] = React.useState<LocalModelStatus | null>(null);
  const [modelSetupOpen, setModelSetupOpen] = React.useState(() => supportsLocalModelSetupClient());
  const [modelBusy, setModelBusy] = React.useState(false);
  const [modelProgress, setModelProgress] = React.useState<ModelProgress | null>(null);
  const fileInputRef = React.useRef<HTMLInputElement | null>(null);
  const composerFileInputRef = React.useRef<HTMLInputElement | null>(null);
  const chatEndRef = React.useRef<HTMLDivElement | null>(null);

  const refreshDocuments = React.useCallback(async () => {
    return listDocuments();
  }, []);

  const refreshConversations = React.useCallback(async () => {
    return listConversations();
  }, []);

  const refreshModelStatus = React.useCallback(async () => {
    const nextStatus = await getLocalModelStatus(LOCAL_MODEL);
    setModelStatus(nextStatus);
    return nextStatus;
  }, []);

  React.useEffect(() => {
    let active = true;
    async function loadInitialState() {
      const [documentResult, conversationResult, modelResult] = await Promise.allSettled([
          refreshDocuments(),
          refreshConversations(),
          refreshModelStatus(),
      ]);
      if (!active) return;

      if (documentResult.status === "fulfilled") {
        setDocuments(documentResult.value);
      }
      if (conversationResult.status === "fulfilled") {
        setConversations(conversationResult.value);
      }
      if (modelResult.status === "fulfilled") {
        setModelStatus(modelResult.value);
        if (!modelResult.value.local_setup_supported) {
          setModelSetupOpen(false);
        } else if (modelResult.value.model_available && !modelResult.value.local_model_enabled) {
          try {
            const enabledStatus = await enableLocalModel(LOCAL_MODEL);
            if (!active) return;
            setModelStatus(enabledStatus);
            setModelSetupOpen(!enabledStatus.local_model_enabled);
          } catch {
            setModelSetupOpen(true);
          }
        } else {
          setModelSetupOpen(!modelResult.value.local_model_enabled);
        }
      } else {
        setModelStatus({
          ollama_running: false,
          installed_models: [],
          target_model: LOCAL_MODEL,
          model_available: false,
          llm_provider: "extractive",
          app_env: "unknown",
          local_setup_supported: supportsLocalModelSetupClient(),
          local_model_enabled: false,
          ollama_base_url: "http://localhost:11434",
          error: "Could not check local AI model.",
        });
        setModelSetupOpen(supportsLocalModelSetupClient());
      }

      if (documentResult.status === "rejected" || conversationResult.status === "rejected") {
        setStatusText("Could not load some workspace data. The app is still usable.");
      }
    }
    void loadInitialState();
    return () => {
      active = false;
    };
  }, [refreshDocuments, refreshConversations, refreshModelStatus]);

  React.useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, stages, isStreaming]);

  const filteredDocuments = React.useMemo(() => {
    const needle = documentSearch.trim().toLowerCase();
    if (!needle) return documents;
    return documents.filter((doc) => doc.name.toLowerCase().includes(needle));
  }, [documents, documentSearch]);

  const handleUpload = async (file?: File | null) => {
    if (!file) return;
    if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
      setStatusText("Only PDF uploads are accepted.");
      setUploadState("error");
      return;
    }
    setUploadState("uploading");
    setStatusText(`Indexing ${file.name}... OCR may run for scanned or hard-to-read pages.`);
    try {
      const result = await uploadDocument(file);
      setDocuments(await refreshDocuments());
      setUploadState("done");
      setStatusText(
        result.duplicate
          ? "This PDF was already indexed."
          : `Indexed ${result.chunk_count} searchable legal chunks.`,
      );
    } catch (error) {
      setUploadState("error");
      setStatusText(error instanceof Error ? error.message : "Upload failed.");
    }
  };

  const openCitation = React.useCallback((citation: Citation) => {
    setSelectedCitation(citation);
    const params = new URLSearchParams(window.location.search);
    params.set("doc", citation.document_id);
    params.set("page", String(citation.page_number));
    params.set("chunk", citation.chunk_id);
    window.history.replaceState(null, "", `?${params.toString()}`);
  }, []);

  const openDocument = (document: LegalDocument) => {
    openCitation({
      source_index: 1,
      document_id: document.id,
      document_name: document.name,
      page_number: 1,
      article_number: null,
      chunk_id: "",
      quote: "",
      score: 0,
    });
  };

  const startNewChat = () => {
    setConversationId(null);
    setMessages([]);
    setStages([]);
    setQuery("");
  };

  const loadConversation = async (conversation: Conversation) => {
    setConversationId(conversation.id);
    setStages([]);
    setMessages(await listMessages(conversation.id));
  };

  const closeModelSetupForNow = () => {
    setModelSetupOpen(false);
  };

  const openModelSetup = () => {
    if (modelStatus && !modelStatus.local_setup_supported) {
      setStatusText(
        "Local AI setup is available in the desktop/local app. Hugging Face Spaces run in hosted document mode.",
      );
      return;
    }
    setModelSetupOpen(true);
  };

  const handleRefreshModel = async () => {
    setModelBusy(true);
    setModelProgress(null);
    try {
      await refreshModelStatus();
    } catch (error) {
      setModelProgress({
        status: "Could not check local Ollama.",
        error: error instanceof Error ? error.message : "Model status check failed.",
      });
    } finally {
      setModelBusy(false);
    }
  };

  const handleEnableModel = async () => {
    setModelBusy(true);
    setModelProgress({ status: "Enabling local AI mode..." });
    try {
      const nextStatus = await enableLocalModel(LOCAL_MODEL);
      setModelStatus(nextStatus);
      setModelProgress({ status: "Local AI mode is enabled." });
      setStatusText("Local AI mode enabled. General chat now uses your local Qwen model.");
      setModelSetupOpen(false);
    } catch (error) {
      setModelProgress({
        status: "Could not enable local AI mode.",
        error: error instanceof Error ? error.message : "Enable failed.",
      });
    } finally {
      setModelBusy(false);
    }
  };

  const handlePullModel = async () => {
    setModelBusy(true);
    setModelProgress({ status: `Starting ${LOCAL_MODEL} download...` });
    let streamError: string | null = null;
    try {
      await streamLocalModelPull(LOCAL_MODEL, {
        onProgress: (event) => {
          setModelProgress({
            status: event.status,
            completed: event.completed,
            total: event.total,
          });
        },
        onDone: () => {
          setModelProgress({ status: "Download complete. Enabling local AI mode..." });
        },
        onError: (error) => {
          streamError = error;
          setModelProgress({ status: "Model download failed.", error });
        },
      });
      if (streamError) {
        throw new Error(streamError);
      }
      const nextStatus = await refreshModelStatus();
      if (nextStatus.local_model_enabled) {
        setStatusText("Local AI model downloaded and enabled.");
        setModelSetupOpen(false);
      }
    } catch (error) {
      setModelProgress({
        status: "Model download failed.",
        error: error instanceof Error ? error.message : "Download failed.",
      });
    } finally {
      setModelBusy(false);
    }
  };

  const sendMessage = async (value = query) => {
    const clean = value.trim();
    if (!clean || isStreaming) return;

    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: clean,
    };
    const assistantId = crypto.randomUUID();
    const assistantMessage: ChatMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
      citations: [],
    };

    setMessages((current) => [...current, userMessage, assistantMessage]);
    setQuery("");
    setStages([]);
    setIsStreaming(true);
    setStatusText(null);

    try {
      await streamChat(
        {
          message: clean,
          conversation_id: conversationId,
          top_k: 6,
        },
        {
          onConversation: (conversation) => {
            setConversationId(conversation.id);
          },
          onStage: (label) => {
            setStages((current) => (current.includes(label) ? current : [...current, label]));
          },
          onCitations: (citations) => {
            setMessages((current) =>
              current.map((message) =>
                message.id === assistantId ? { ...message, citations } : message,
              ),
            );
          },
          onDelta: (delta) => {
            setMessages((current) =>
              current.map((message) =>
                message.id === assistantId
                  ? { ...message, content: `${message.content}${delta}` }
                  : message,
              ),
            );
          },
          onDone: async (id) => {
            setConversationId(id);
            setConversations(await refreshConversations());
          },
          onError: (error) => {
            setStatusText(error);
          },
        },
      );
    } catch (error) {
      setStatusText(error instanceof Error ? error.message : "Chat stream failed.");
      setMessages((current) =>
        current.map((message) =>
          message.id === assistantId
            ? {
                ...message,
                content:
                  "I could not complete the response because the AI service returned an error.",
              }
            : message,
        ),
      );
    } finally {
      setIsStreaming(false);
    }
  };

  return (
    <main className="relative h-dvh overflow-hidden p-3 text-white lg:p-5">
      <div
        className={cn(
          "grid h-full min-h-0 gap-3 transition duration-300 lg:grid-cols-[316px_minmax(0,1fr)]",
          modelSetupOpen && "pointer-events-none blur-sm brightness-50",
        )}
      >
        <aside className="glass flex min-h-0 flex-col rounded-[8px]">
          <div className="border-b border-white/10 p-4">
            <div className="flex items-center gap-3">
              <div className="grid h-10 w-10 place-items-center rounded-[8px] bg-[#23d6a2] text-[#06100d]">
                <Scale className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <h1 className="truncate text-sm font-semibold">adala ai</h1>
                <p className="truncate text-xs text-white/48">Grounded legal research</p>
              </div>
            </div>
            <div className="mt-4 grid grid-cols-[1fr_auto] gap-2">
              <Button variant="secondary" onClick={startNewChat}>
                <Plus className="h-4 w-4" />
                New chat
              </Button>
              <Button
                size="icon"
                title="Upload PDF"
                variant="default"
                onClick={() => fileInputRef.current?.click()}
              >
                {uploadState === "uploading" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Upload className="h-4 w-4" />
                )}
              </Button>
              <input
                ref={fileInputRef}
                className="hidden"
                type="file"
                accept="application/pdf"
                onChange={(event) => {
                  void handleUpload(event.target.files?.[0]);
                  event.currentTarget.value = "";
                }}
              />
            </div>
          </div>

          <div className="border-b border-white/10 p-3">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/38" />
              <Input
                value={documentSearch}
                onChange={(event) => setDocumentSearch(event.target.value)}
                placeholder="Search documents"
                className="pl-9"
              />
            </div>
          </div>

          <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto p-3">
            <SectionTitle icon={BookOpen} label="Uploaded books" count={documents.length} />
            <div className="mt-2 space-y-1">
              {filteredDocuments.length === 0 ? (
                <EmptyLine text="No PDFs indexed yet." />
              ) : (
                filteredDocuments.map((document, index) => (
                  <button
                    key={document.id || `${document.name}-${index}`}
                    className="group flex w-full items-center gap-3 rounded-[8px] border border-transparent px-3 py-2 text-left transition hover:border-white/10 hover:bg-white/[0.06]"
                    onClick={() => openDocument(document)}
                  >
                    <FileText className="h-4 w-4 shrink-0 text-[#f6c85f]" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm text-white/86">{document.name}</span>
                      <span className="text-xs text-white/40">{document.pages} pages</span>
                    </span>
                  </button>
                ))
              )}
            </div>

            <div className="mt-6">
              <SectionTitle icon={MessageSquareText} label="Conversation history" count={conversations.length} />
              <div className="mt-2 space-y-1">
                {conversations.length === 0 ? (
                  <EmptyLine text="No saved chats yet." />
                ) : (
                  conversations.map((conversation, index) => (
                    <button
                      key={conversation.id || `${conversation.title}-${index}`}
                      className={cn(
                        "w-full rounded-[8px] px-3 py-2 text-left text-sm text-white/72 transition hover:bg-white/[0.06] hover:text-white",
                        conversation.id === conversationId && "bg-white/[0.08] text-white",
                      )}
                      onClick={() => void loadConversation(conversation)}
                    >
                      <span className="block truncate">{conversation.title}</span>
                    </button>
                  ))
                )}
              </div>
            </div>
          </div>

          <AnimatePresence>
            {statusText ? (
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 8 }}
                className="border-t border-white/10 p-3 text-xs text-white/62"
              >
                {statusText}
              </motion.div>
            ) : null}
          </AnimatePresence>
        </aside>

        <section
          className={cn(
            "grid min-h-0 gap-3",
            selectedCitation ? "xl:grid-cols-[minmax(0,1fr)_520px]" : "grid-cols-1",
          )}
        >
          <div className="glass flex min-h-0 flex-col rounded-[8px]">
            <header className="flex items-center justify-between border-b border-white/10 px-4 py-3">
              <div className="flex min-w-0 items-center gap-3">
                <div className="grid h-9 w-9 place-items-center rounded-[8px] bg-white/[0.07]">
                  <Bot className="h-4 w-4 text-[#23d6a2]" />
                </div>
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">adala ai Workspace</p>
                  <p className="truncate text-xs text-white/45">
                    Arabic, English, and mixed legal queries
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  title="Local AI model setup"
                  onClick={openModelSetup}
                >
                  <Cpu className="h-3.5 w-3.5" />
                  {modelStatus?.local_model_enabled
                    ? "Local AI"
                    : modelStatus?.local_setup_supported === false
                      ? "Hosted"
                      : "AI mode"}
                </Button>
                <Badge className="hidden border-[#23d6a2]/30 bg-[#23d6a2]/10 text-[#8af0cf] sm:inline-flex">
                  <ShieldCheck className="mr-1 h-3 w-3" />
                  Context-only
                </Badge>
              </div>
            </header>

            <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto px-4 py-5">
              {messages.length === 0 ? (
                <WelcomeScreen onSelect={(value) => void sendMessage(value)} />
              ) : (
                <div className="mx-auto flex max-w-4xl flex-col gap-5">
                  {messages.map((message, index) => (
                    <MessageBubble
                      key={message.id || `${message.role}-${index}`}
                      message={message}
                      isStreaming={isStreaming && index === messages.length - 1}
                      onCitationClick={openCitation}
                      onFollowUp={(question) => void sendMessage(question)}
                    />
                  ))}
                  <ThinkingTrace stages={stages} active={isStreaming} />
                  <div ref={chatEndRef} />
                </div>
              )}
            </div>

            <div className="border-t border-white/10 p-3">
              <div className="mx-auto max-w-4xl">
                <div className="rounded-[8px] border border-white/10 bg-[#080b10]/78">
                  <Textarea
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="Ask about uploaded Egyptian legal documents..."
                    dir="auto"
                    className="max-h-40 min-h-20 border-0"
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && !event.shiftKey) {
                        event.preventDefault();
                        void sendMessage();
                      }
                    }}
                  />
                  <div className="flex items-center justify-between gap-2 border-t border-white/10 px-3 py-2">
                    <div className="flex items-center gap-2">
                      <Button
                        size="icon"
                        variant="ghost"
                        title="Attach PDF"
                        onClick={() => composerFileInputRef.current?.click()}
                      >
                        <Paperclip className="h-4 w-4" />
                      </Button>
                      <input
                        ref={composerFileInputRef}
                        className="hidden"
                        type="file"
                        accept="application/pdf"
                        onChange={(event) => {
                          void handleUpload(event.target.files?.[0]);
                          event.currentTarget.value = "";
                        }}
                      />
                      <span className="hidden text-xs text-white/40 sm:inline">
                        Responses cite only retrieved chunks.
                      </span>
                    </div>
                    <Button
                      title="Send"
                      disabled={!query.trim() || isStreaming}
                      onClick={() => void sendMessage()}
                    >
                      {isStreaming ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <SendHorizontal className="h-4 w-4" />
                      )}
                      Send
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <AnimatePresence>
            {selectedCitation ? (
              <motion.div
                initial={{ opacity: 0, x: 24 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 24 }}
                className="min-h-0"
              >
                <PdfViewer
                  key={`${selectedCitation.document_id}:${selectedCitation.page_number}:${selectedCitation.chunk_id}`}
                  citation={selectedCitation}
                  onClose={() => setSelectedCitation(null)}
                />
              </motion.div>
            ) : null}
          </AnimatePresence>
        </section>
      </div>
      <AnimatePresence>
        {modelSetupOpen ? (
          <LocalModelSetup
            status={modelStatus}
            progress={modelProgress}
            busy={modelBusy}
            modelName={LOCAL_MODEL}
            onClose={closeModelSetupForNow}
            onRefresh={() => void handleRefreshModel()}
            onPull={() => void handlePullModel()}
            onEnable={() => void handleEnableModel()}
          />
        ) : null}
      </AnimatePresence>
    </main>
  );
}

function LocalModelSetup({
  status,
  progress,
  busy,
  modelName,
  onClose,
  onRefresh,
  onPull,
  onEnable,
}: {
  status: LocalModelStatus | null;
  progress: ModelProgress | null;
  busy: boolean;
  modelName: string;
  onClose: () => void;
  onRefresh: () => void;
  onPull: () => void;
  onEnable: () => void;
}) {
  const completedBytes = progress?.completed ?? null;
  const totalBytes = progress?.total ?? null;
  const hasProgressBytes = completedBytes !== null && totalBytes !== null;
  const progressPercent =
    hasProgressBytes && totalBytes > 0
      ? Math.max(0, Math.min(100, Math.round((completedBytes / totalBytes) * 100)))
      : null;
  const ollamaRunning = Boolean(status?.ollama_running);
  const modelAvailable = Boolean(status?.model_available);
  const localModelEnabled = Boolean(status?.local_model_enabled);

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 grid place-items-center bg-black/70 px-4 backdrop-blur-md"
    >
      <motion.section
        initial={{ opacity: 0, y: 18, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 18, scale: 0.98 }}
        className="w-full max-w-[640px] rounded-[8px] border border-white/12 bg-[#080b10]/95 p-5 shadow-2xl"
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <Badge className="border-[#23d6a2]/30 bg-[#23d6a2]/10 text-[#8af0cf]">
              <Cpu className="mr-1 h-3 w-3" />
              Local AI model
            </Badge>
            <h2 className="mt-4 text-2xl font-semibold text-white">Download local AI model to use</h2>
            <p className="mt-3 max-w-xl text-sm leading-6 text-white/58">
              Adala AI can search and cite PDFs now. For full conversational AI, install Ollama and
              download {modelName}; the model runs privately on this computer.
            </p>
          </div>
          <Button size="icon" variant="ghost" title="Use document mode for now" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="mt-5 grid gap-2 sm:grid-cols-3">
          <ModelStatusTile
            label="Ollama app"
            ready={ollamaRunning}
            text={ollamaRunning ? "Running" : "Not detected"}
          />
          <ModelStatusTile
            label="Qwen model"
            ready={modelAvailable}
            text={modelAvailable ? "Downloaded" : "Needs download"}
          />
          <ModelStatusTile
            label="AI mode"
            ready={localModelEnabled}
            text={localModelEnabled ? "Enabled" : "Document mode"}
          />
        </div>

        {progress ? (
          <div className="mt-5 rounded-[8px] border border-white/10 bg-white/[0.04] p-4">
            <div className="flex items-center justify-between gap-3 text-sm text-white/72">
              <span>{progress.status}</span>
              {busy ? <Loader2 className="h-4 w-4 animate-spin text-[#23d6a2]" /> : null}
            </div>
            {progressPercent !== null ? (
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/10">
                <div className="h-full bg-[#23d6a2]" style={{ width: `${progressPercent}%` }} />
              </div>
            ) : null}
            {hasProgressBytes ? (
              <p className="mt-2 text-xs text-white/42">
                {formatModelBytes(completedBytes)} of {formatModelBytes(totalBytes)}
              </p>
            ) : null}
            {progress.error ? <p className="mt-2 text-xs text-[#ff8995]">{progress.error}</p> : null}
          </div>
        ) : null}

        <div className="mt-5 rounded-[8px] border border-[#f6c85f]/20 bg-[#f6c85f]/[0.08] p-4 text-sm leading-6 text-[#f7d983]">
          {ollamaRunning
            ? modelAvailable
              ? "The local model is ready. Enable AI mode and continue inside Adala AI."
              : "Ollama is running. Download the Qwen model once, then Adala AI can use it locally."
            : "Install Ollama, open it once, then return here and press Check again."}
        </div>

        <div className="mt-5 flex flex-wrap items-center gap-2">
          {!ollamaRunning ? (
            <Button asChild>
              <a href="https://ollama.com/download/windows" target="_blank" rel="noreferrer">
                <ExternalLink className="h-4 w-4" />
                Download Ollama
              </a>
            </Button>
          ) : null}
          {ollamaRunning && !modelAvailable ? (
            <Button disabled={busy} onClick={onPull}>
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
              Download {modelName}
            </Button>
          ) : null}
          {ollamaRunning && modelAvailable && !localModelEnabled ? (
            <Button disabled={busy} onClick={onEnable}>
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
              Enable AI mode
            </Button>
          ) : null}
          {localModelEnabled ? (
            <Button onClick={onClose}>
              <CheckCircle2 className="h-4 w-4" />
              Continue
            </Button>
          ) : null}
          <Button disabled={busy} variant="secondary" onClick={onRefresh}>
            <RefreshCcw className={cn("h-4 w-4", busy && "animate-spin")} />
            Check again
          </Button>
          <Button disabled={busy} variant="ghost" onClick={onClose}>
            Use document mode for now
          </Button>
        </div>
      </motion.section>
    </motion.div>
  );
}

function ModelStatusTile({ label, ready, text }: { label: string; ready: boolean; text: string }) {
  return (
    <div className="rounded-[8px] border border-white/10 bg-white/[0.04] p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs uppercase tracking-[0.12em] text-white/38">{label}</p>
        <span className={cn("h-2 w-2 rounded-full", ready ? "bg-[#23d6a2]" : "bg-[#f6c85f]")} />
      </div>
      <p className="mt-2 text-sm text-white/76">{text}</p>
    </div>
  );
}

function formatModelBytes(value: number) {
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB"];
  let next = value / 1024;
  for (const unit of units) {
    if (next < 1024) return `${next.toFixed(next >= 100 ? 0 : 1)} ${unit}`;
    next /= 1024;
  }
  return `${next.toFixed(1)} TB`;
}

function SectionTitle({
  icon: Icon,
  label,
  count,
}: {
  icon: React.ElementType;
  label: string;
  count: number;
}) {
  return (
    <div className="flex items-center justify-between px-1">
      <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.12em] text-white/42">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <span className="text-xs text-white/34">{count}</span>
    </div>
  );
}

function EmptyLine({ text }: { text: string }) {
  return <p className="px-3 py-2 text-sm text-white/34">{text}</p>;
}

function WelcomeScreen({ onSelect }: { onSelect: (question: string) => void }) {
  return (
    <div className="mx-auto flex min-h-full max-w-4xl flex-col justify-center py-10">
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
        <Badge className="border-[#f6c85f]/30 bg-[#f6c85f]/10 text-[#f7d983]">
          <Sparkles className="mr-1 h-3 w-3" />
          Retrieval-Augmented Legal Research
        </Badge>
        <h2 className="mt-5 max-w-3xl text-4xl font-semibold leading-tight text-white sm:text-5xl">
          Chat with adala ai about your Egyptian law library.
        </h2>
        <p className="mt-4 max-w-2xl text-sm leading-7 text-white/56 sm:text-base">
          Upload constitutions, statutes, regulations, pleadings, judgments, or law books. The
          assistant searches only those documents and returns clickable source-backed answers.
        </p>
      </motion.div>

      <div className="mt-8 grid gap-3 sm:grid-cols-2">
        {suggestions.map((question, index) => (
          <motion.button
            key={question}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.05 }}
            className="rounded-[8px] border border-white/10 bg-white/[0.04] p-4 text-left text-sm leading-6 text-white/76 transition hover:border-[#23d6a2]/45 hover:bg-[#23d6a2]/10"
            dir={isArabic(question) ? "rtl" : "ltr"}
            onClick={() => onSelect(question)}
          >
            {question}
          </motion.button>
        ))}
      </div>
    </div>
  );
}

function ThinkingTrace({ stages, active }: { stages: string[]; active: boolean }) {
  if (stages.length === 0) return null;
  return (
    <div className="rounded-[8px] border border-white/10 bg-white/[0.035] px-4 py-3">
      <div className="flex items-center gap-2 text-sm text-white/62">
        {active ? <Loader2 className="h-4 w-4 animate-spin text-[#23d6a2]" /> : null}
        AI research trace
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        {stages.map((stage, index) => (
          <motion.div
            key={`${stage}-${index}`}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex items-center gap-2 rounded-[8px] bg-black/18 px-3 py-2 text-xs text-white/58"
          >
            <span className="h-1.5 w-1.5 rounded-full bg-[#23d6a2]" />
            {stage}
          </motion.div>
        ))}
      </div>
    </div>
  );
}

function MessageBubble({
  message,
  isStreaming,
  onCitationClick,
  onFollowUp,
}: {
  message: ChatMessage;
  isStreaming: boolean;
  onCitationClick: (citation: Citation) => void;
  onFollowUp: (question: string) => void;
}) {
  const assistant = message.role === "assistant";
  const followUps = assistant && !isStreaming ? followUpsForMessage(message) : [];
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn("flex", assistant ? "justify-start" : "justify-end")}
    >
      <div
        className={cn(
          "max-w-[min(820px,92%)] rounded-[8px] border px-4 py-3",
          assistant
            ? "border-white/10 bg-white/[0.045]"
            : "border-[#23d6a2]/25 bg-[#23d6a2]/12",
        )}
      >
        <div className="mb-2 flex items-center gap-2 text-xs text-white/42">
          {assistant ? <Bot className="h-3.5 w-3.5" /> : <Scale className="h-3.5 w-3.5" />}
          {assistant ? "Assistant" : "You"}
          {isStreaming ? <Loader2 className="h-3.5 w-3.5 animate-spin text-[#23d6a2]" /> : null}
        </div>
        <div
          className="arabic-friendly whitespace-pre-wrap text-sm text-white/86"
          dir={isArabic(message.content) ? "rtl" : "auto"}
        >
          {message.content || (assistant ? "Preparing grounded response..." : "")}
          {assistant && isStreaming ? (
            <span className="ml-1 inline-block h-4 w-1 translate-y-0.5 animate-pulse rounded-full bg-[#23d6a2]" />
          ) : null}
        </div>
        {assistant && message.citations && message.citations.length > 0 ? (
          <div className="mt-4 flex flex-wrap gap-2">
            {message.citations.map((citation, index) => (
              <button
                key={`${citation.chunk_id || citation.document_id || "citation"}-${citation.source_index ?? index}-${index}`}
                className="inline-flex items-center gap-2 rounded-[8px] border border-white/10 bg-black/18 px-3 py-2 text-left text-xs text-white/68 transition hover:border-[#f6c85f]/50 hover:text-white"
                onClick={() => onCitationClick(citation)}
              >
                <FileText className="h-3.5 w-3.5 text-[#f6c85f]" />
                <span className="max-w-48 truncate">
                  Source {citation.source_index} · {formatArticle(citation.article_number)} · Page{" "}
                  {citation.page_number}
                </span>
              </button>
            ))}
          </div>
        ) : null}
        {followUps.length > 0 ? (
          <div className="mt-4 flex flex-wrap gap-2">
            {followUps.map((question) => (
              <button
                key={question}
                className="rounded-[8px] border border-[#23d6a2]/20 bg-[#23d6a2]/10 px-3 py-2 text-xs text-[#9cf4d8] transition hover:border-[#23d6a2]/50 hover:bg-[#23d6a2]/15"
                dir={isArabic(question) ? "rtl" : "ltr"}
                onClick={() => onFollowUp(question)}
              >
                {question}
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </motion.div>
  );
}

function followUpsForMessage(message: ChatMessage) {
  const citations = message.citations || [];
  const arabic = isArabic(message.content);
  const firstArticle = citations.find((citation) => citation.article_number)?.article_number || null;
  if (firstArticle && /^\d+$/.test(firstArticle)) {
    const nextArticle = String(Number(firstArticle) + 1);
    return arabic
      ? [
          `لخص المادة ${firstArticle} ببساطة`,
          `ما هي المادة ${nextArticle}؟`,
          "قارن بين المصادر",
        ]
      : [
          `Summarize Article ${firstArticle}`,
          `What is Article ${nextArticle}?`,
          "Compare the cited sources",
        ];
  }
  if (citations.length > 0) {
    return arabic
      ? ["لخص الإجابة", "ما أهم النقاط؟", "اشرح المصدر الأول"]
      : ["Summarize this answer", "What are the key points?", "Explain Source 1"];
  }
  return arabic
    ? ["ما أعلى مادة متاحة؟", "ما المستندات المرفوعة؟", "اسأل عن المادة 247"]
    : ["What is the highest article available?", "What documents are uploaded?", "Ask about Article 247"];
}
