"use client";

import {
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  FileSearch,
  Highlighter,
  Loader2,
  X,
} from "lucide-react";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { documentFileUrl } from "@/lib/api";
import type { Citation } from "@/lib/types";
import { cn, formatArticle } from "@/lib/utils";

type PdfJsModule = typeof import("pdfjs-dist");
type PdfDocument = {
  numPages: number;
  getPage: (pageNumber: number) => Promise<PdfPage>;
  destroy?: () => Promise<void>;
};
type PdfPage = {
  getViewport: (options: { scale: number }) => PdfViewport;
  render: (options: {
    canvas?: HTMLCanvasElement;
    canvasContext: CanvasRenderingContext2D;
    viewport: PdfViewport;
    transform?: number[];
  }) => { promise: Promise<void> };
  getTextContent: () => Promise<{ items: TextItem[] }>;
  cleanup?: () => void;
};
type PdfViewport = {
  width: number;
  height: number;
  transform: number[];
};
type TextItem = {
  str?: string;
  width?: number;
  height?: number;
  transform?: number[];
};
type HighlightBox = {
  left: number;
  top: number;
  width: number;
  height: number;
  kind: "citation" | "search";
};

export function PdfViewer({ citation, onClose }: { citation: Citation; onClose: () => void }) {
  const [pdfjs, setPdfjs] = React.useState<PdfJsModule | null>(null);
  const [pdf, setPdf] = React.useState<PdfDocument | null>(null);
  const [pageNumber, setPageNumber] = React.useState(citation.page_number || 1);
  const [search, setSearch] = React.useState("");
  const [highlights, setHighlights] = React.useState<HighlightBox[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [pageSize, setPageSize] = React.useState({ width: 0, height: 0 });
  const canvasRef = React.useRef<HTMLCanvasElement | null>(null);
  const containerRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    async function loadPdfJs() {
      const mod = await import("pdfjs-dist");
      mod.GlobalWorkerOptions.workerSrc = new URL(
        "pdfjs-dist/build/pdf.worker.mjs",
        import.meta.url,
      ).toString();
      if (!cancelled) setPdfjs(mod);
    }
    void loadPdfJs().catch(() => setError("PDF.js could not be loaded."));
    return () => {
      cancelled = true;
    };
  }, []);

  React.useEffect(() => {
    if (!pdfjs) return;
    const currentPdfjs = pdfjs;
    let cancelled = false;
    let loadingTask: { promise: Promise<PdfDocument>; destroy?: () => Promise<void> } | null = null;

    async function loadDocument() {
      setLoading(true);
      setError(null);
      try {
        loadingTask = currentPdfjs.getDocument({ url: documentFileUrl(citation.document_id) }) as unknown as {
          promise: Promise<PdfDocument>;
          destroy?: () => Promise<void>;
        };
        const loaded = await loadingTask.promise;
        if (!cancelled) {
          setPdf(loaded);
          setLoading(false);
        }
      } catch {
        if (!cancelled) {
          setError("Unable to open the source PDF.");
          setLoading(false);
        }
      }
    }

    void loadDocument();
    return () => {
      cancelled = true;
      void loadingTask?.destroy?.();
    };
  }, [citation.document_id, pdfjs]);

  React.useEffect(() => {
    if (!pdf || !pdfjs || !canvasRef.current) return;
    const currentPdf = pdf;
    const currentPdfjs = pdfjs;
    let cancelled = false;

    async function renderPage() {
      setLoading(true);
      const page = await currentPdf.getPage(pageNumber);
      if (cancelled) return;

      const unscaled = page.getViewport({ scale: 1 });
      const availableWidth = Math.max(320, (containerRef.current?.clientWidth || 860) - 28);
      const scale = Math.max(0.78, Math.min(2.15, availableWidth / unscaled.width));
      const viewport = page.getViewport({ scale });
      const canvas = canvasRef.current;
      const context = canvas?.getContext("2d");
      if (!canvas || !context) return;

      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.floor(viewport.width * ratio);
      canvas.height = Math.floor(viewport.height * ratio);
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = `${viewport.height}px`;
      setPageSize({ width: viewport.width, height: viewport.height });

      await page.render({
        canvas,
        canvasContext: context,
        viewport,
        transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : undefined,
      }).promise;

      const textContent = await page.getTextContent();
      if (!cancelled) {
        setHighlights(
          buildHighlightBoxes(
            currentPdfjs,
            textContent.items,
            viewport,
            search.trim() ? search : citation.quote,
            search.trim() ? "search" : "citation",
          ),
        );
        setLoading(false);
      }
      page.cleanup?.();
    }

    void renderPage().catch(() => {
      if (!cancelled) {
        setError("Unable to render this PDF page.");
        setLoading(false);
      }
    });

    return () => {
      cancelled = true;
    };
  }, [citation.quote, pageNumber, pdf, pdfjs, search]);

  const pageCount = pdf?.numPages || 1;
  const fileHref = `${documentFileUrl(citation.document_id)}#page=${pageNumber}`;

  return (
    <div className="glass flex h-full min-h-0 flex-col rounded-[8px]">
      <header className="border-b border-white/10 p-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Highlighter className="h-4 w-4 text-[#f6c85f]" />
              <p className="truncate text-sm font-medium">{citation.document_name}</p>
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              <Badge>{formatArticle(citation.article_number)}</Badge>
              <Badge>Page {pageNumber}</Badge>
              <Badge>Source {citation.source_index}</Badge>
            </div>
          </div>
          <Button size="icon" variant="ghost" title="Close PDF viewer" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="mt-3 grid grid-cols-[auto_1fr_auto] gap-2">
          <Button
            size="icon"
            variant="secondary"
            title="Previous page"
            disabled={pageNumber <= 1}
            onClick={() => setPageNumber((value) => Math.max(1, value - 1))}
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <div className="relative">
            <FileSearch className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/38" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search inside page"
              className="pl-9"
            />
          </div>
          <Button
            size="icon"
            variant="secondary"
            title="Next page"
            disabled={pageNumber >= pageCount}
            onClick={() => setPageNumber((value) => Math.min(pageCount, value + 1))}
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>

        <div className="mt-3 flex items-center justify-between gap-2 text-xs text-white/42">
          <span>
            {pageNumber} / {pageCount}
          </span>
          <a
            href={fileHref}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-white/58 transition hover:text-white"
          >
            Open PDF
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
        </div>
      </header>

      <div ref={containerRef} className="thin-scrollbar min-h-0 flex-1 overflow-auto bg-black/18 p-3">
        {error ? (
          <div className="rounded-[8px] border border-[#ff6b7a]/30 bg-[#ff6b7a]/10 p-4 text-sm text-white/72">
            {error}
          </div>
        ) : (
          <div
            className="relative mx-auto overflow-hidden rounded-[8px] bg-white shadow-2xl shadow-black/40"
            style={{
              width: pageSize.width || undefined,
              height: pageSize.height || undefined,
            }}
          >
            <canvas ref={canvasRef} />
            <div className="pointer-events-none absolute inset-0">
              {highlights.map((box, index) => (
                <span
                  key={`${box.left}-${box.top}-${index}`}
                  className={cn(
                    "absolute rounded-[3px] mix-blend-multiply",
                    box.kind === "search" ? "bg-[#23d6a2]/40" : "bg-[#f6c85f]/48",
                  )}
                  style={{
                    left: box.left,
                    top: box.top,
                    width: box.width,
                    height: box.height,
                  }}
                />
              ))}
            </div>
            {loading ? (
              <div className="absolute inset-0 grid place-items-center bg-white/70 text-[#10141c]">
                <Loader2 className="h-5 w-5 animate-spin" />
              </div>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}

function normalizeText(value: string) {
  return value
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[\u064B-\u065F]/g, "")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}

function significantWords(value: string) {
  return new Set(
    normalizeText(value)
      .split(/\s+/)
      .filter((word) => word.length >= 4)
      .slice(0, 120),
  );
}

function buildHighlightBoxes(
  pdfjs: PdfJsModule,
  items: TextItem[],
  viewport: PdfViewport,
  target: string,
  kind: "citation" | "search",
): HighlightBox[] {
  const targetWords = significantWords(target);
  const normalizedTarget = normalizeText(target);
  if (!targetWords.size && normalizedTarget.length < 3) return [];

  const boxes: HighlightBox[] = [];
  for (const item of items) {
    const text = item.str || "";
    const normalizedItem = normalizeText(text);
    if (!normalizedItem || !item.transform) continue;

    const exactish = normalizedItem.length > 3 && normalizedTarget.includes(normalizedItem);
    const overlap = normalizedItem
      .split(/\s+/)
      .filter((word) => targetWords.has(word)).length;
    const shouldHighlight = kind === "search" ? exactish || overlap > 0 : exactish || overlap >= 2;
    if (!shouldHighlight) continue;

    const tx = pdfjs.Util.transform(viewport.transform, item.transform);
    const fontHeight = Math.max(8, Math.hypot(tx[2], tx[3]) || item.height || 10);
    const width = Math.max(12, (item.width || text.length * fontHeight * 0.48) * viewport.width / viewport.width);
    boxes.push({
      left: tx[4],
      top: tx[5] - fontHeight,
      width,
      height: fontHeight * 1.15,
      kind,
    });
  }
  return boxes;
}
