import type { PaperImageAttachment, PaperQuestion } from "@/lib/ai-api";

export function stripDiagramPlaceholders(text: string | undefined | null): {
  text: string;
  placeholderPaths: string[];
} {
  const raw = String(text || "");
  const placeholderPaths = Array.from(
    raw.matchAll(/\[DIAGRAM:\s*(.*?)\]/gi),
    (match) => match[1]?.trim() || "",
  ).filter(Boolean);

  return {
    text: raw.replace(/\s*\[DIAGRAM:\s*.*?\]\s*/gi, " ").replace(/\s+/g, " ").trim(),
    placeholderPaths,
  };
}

export function getQuestionDisplayText(question: Pick<PaperQuestion, "text">): string {
  return stripDiagramPlaceholders(question.text).text;
}

export function getQuestionImages(
  question: Pick<PaperQuestion, "text" | "attached_images">,
): PaperImageAttachment[] {
  const directImages = [...(question.attached_images || [])];
  
  if (directImages.length === 0) {
    return [];
  }

  // Strict visual gating to prevent stale DB state from rendering placeholders.
  // Must match logic in backend _candidate_needs_diagram.
  const rawText = String(question.text || "").toLowerCase();
  
  const hasVisualCue = /based on the figure|in the figure|given figure|given circuit|given diagram|following figure|following diagram|shown in figure|shown below|referring to the figure/i.test(rawText);
  const hasDrawCue = /\b(draw|sketch|plot)\b/i.test(rawText) && /\b(diagram|graph|circuit|architecture)\b/i.test(rawText);
  const hasIllustrate = /\b(illustrate|explain)\b/i.test(rawText) && /\b(diagram|figure|graph|circuit|architecture)\b/i.test(rawText);

  if (!hasVisualCue && !hasDrawCue && !hasIllustrate) {
    return [];
  }

  return directImages;
}
