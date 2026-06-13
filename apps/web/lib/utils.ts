import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function isArabic(text: string) {
  return /[\u0600-\u06FF]/.test(text);
}

export function formatArticle(article?: string | null) {
  return article ? `Article ${article}` : "Article N/A";
}

