/**
 * Extended API hooks for QPGen v2 — Pedagogical Analysis, Templates, Rubric.
 *
 * Import alongside the core ai-api.ts hooks.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { GeneratedPaper, PaperQuestion } from "./ai-api";

const API_BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000/api/v1";

async function fetchWithAuth<T>(url: string, options?: RequestInit): Promise<T> {
  const token = localStorage.getItem("access_token");
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(token && { Authorization: `Bearer ${token}` }),
    ...options?.headers,
  };
  const response = await fetch(`${API_BASE_URL}${url}`, { ...options, headers });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Request failed" }));
    const apiError = new Error(error.detail || "Request failed") as Error & { status?: number };
    apiError.status = response.status;
    throw apiError;
  }
  return response.json();
}

/* ------------------------------------------------------------------ */
/* Pedagogical Analysis (Phase 1)                                      */
/* ------------------------------------------------------------------ */

export interface PedagogicalAnalysis {
  bloom_level: string;
  bloom_label: string;
  difficulty: string;
  difficulty_index: number;
  marks: number;
  time_estimate_min: number;
  cognitive_load: string;
  expected_answer_depth: string;
  question_family: string;
  is_numerical: boolean;
  solution_steps_estimate: number;
  marks_valid: boolean;
  marks_suggestion: number | null;
}

export interface PaperTimeAnalysis {
  total_estimated_min: number;
  exam_duration_min: number;
  time_surplus_min: number;
  is_balanced: boolean;
  per_question: Array<{
    index: number;
    bloom_level: string;
    marks: number;
    time_estimate_min: number;
    difficulty: string;
    cognitive_load: string;
  }>;
  warnings: string[];
}

export function useAnalyzeQuestion() {
  return useMutation<PedagogicalAnalysis, Error, { text: string; bloom_level?: string; marks?: number }>({
    mutationFn: async (params) =>
      fetchWithAuth<PedagogicalAnalysis>("/academic/pedagogical/analyze", {
        method: "POST",
        body: JSON.stringify(params),
      }),
  });
}

export function useAnalyzePaperTime() {
  return useMutation<PaperTimeAnalysis, Error, { questions: any[]; exam_duration_min: number }>({
    mutationFn: async (params) =>
      fetchWithAuth<PaperTimeAnalysis>("/academic/pedagogical/analyze-paper", {
        method: "POST",
        body: JSON.stringify(params),
      }),
  });
}

/* ------------------------------------------------------------------ */
/* Mark Strategies (Phase 1)                                           */
/* ------------------------------------------------------------------ */

export interface MarkStrategy {
  name: string;
  description: string;
  l1_l2_percent: number;
  l3_percent: number;
  l4_percent: number;
  l5_l6_percent: number;
}

export function useMarkStrategies() {
  return useQuery<MarkStrategy[]>({
    queryKey: ["mark-strategies"],
    queryFn: () => fetchWithAuth<MarkStrategy[]>("/academic/mark-strategies"),
    staleTime: 60000,
  });
}

/* ------------------------------------------------------------------ */
/* Institutional Templates (Phase 2)                                   */
/* ------------------------------------------------------------------ */

export interface TemplateSummary {
  template_id: string;
  template_name: string;
  is_preset: boolean;
  institution_name: string;
  header_layout: string;
}

export function useTemplates() {
  return useQuery<TemplateSummary[]>({
    queryKey: ["templates"],
    queryFn: () => fetchWithAuth<TemplateSummary[]>("/academic/templates"),
    staleTime: 60000,
  });
}

export function useTemplate(templateId?: string) {
  return useQuery<Record<string, any>>({
    queryKey: ["template", templateId],
    queryFn: () => fetchWithAuth<Record<string, any>>(`/academic/templates/${templateId}`),
    enabled: Boolean(templateId),
    staleTime: 60000,
  });
}

/* ------------------------------------------------------------------ */
/* Rubric Generation (Phase 4)                                         */
/* ------------------------------------------------------------------ */

export interface RubricStep {
  step_number: number;
  description: string;
  marks_allocated: number;
  partial_marking: string;
}

export interface QuestionRubric {
  question_index: number;
  question_text: string;
  total_marks: number;
  bloom_level: string;
  steps: RubricStep[];
  diagram_required: boolean;
  formula_required: boolean;
  key_terms: string[];
}

export interface PaperRubric {
  paper_title: string;
  total_marks: number;
  general_instructions: string;
  questions: QuestionRubric[];
}

export function useGenerateRubric() {
  return useMutation<PaperRubric, Error, { paper_title: string; questions: any[] }>({
    mutationFn: async (params) =>
      fetchWithAuth<PaperRubric>("/academic/rubric/generate", {
        method: "POST",
        body: JSON.stringify(params),
      }),
  });
}

/* ------------------------------------------------------------------ */
/* Paper Update (Phase 3 — inline editing save)                        */
/* ------------------------------------------------------------------ */

export function useUpdatePaper() {
  const queryClient = useQueryClient();
  return useMutation<GeneratedPaper, Error, {
    paperId: number;
    overrides: Record<string, string>;
    title?: string;
    questionUpdates?: Array<{
      id: number;
      text?: string;
      course_outcome?: string | null;
      bloom_level?: string | null;
      module_number?: number | null;
      attached_images?: PaperQuestion["attached_images"];
    }>;
  }>({
    mutationFn: async ({ paperId, overrides, title, questionUpdates }) =>
      fetchWithAuth<GeneratedPaper>(`/papers/${paperId}`, {
        method: "PUT",
        body: JSON.stringify({
          title,
          question_text_overrides: overrides,
          question_updates: questionUpdates || [],
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["papers"] });
    },
  });
}

/* ------------------------------------------------------------------ */
/* CO/PO Attainment (Phase 5)                                          */
/* ------------------------------------------------------------------ */

export interface COAttainment {
  co: string;
  total_marks: number;
  marks_in_paper: number;
  percentage: number;
  attainment_level: string;
  attainment_value: number;
  bloom_distribution: Record<string, number>;
  question_count: number;
}

export interface POAttainment {
  po: string;
  weighted_score: number;
  attainment_level: string;
  attainment_value: number;
  contributing_cos: string[];
}

export interface AttainmentReport {
  paper_title: string;
  total_marks: number;
  overall_co_attainment: number;
  overall_po_attainment: number;
  bloom_summary: Record<string, number>;
  warnings: string[];
  co_attainments: COAttainment[];
  po_attainments: POAttainment[];
}

export function useAnalyzeAttainment() {
  return useMutation<AttainmentReport, Error, { paper_title: string; total_marks: number; questions: any[] }>({
    mutationFn: async (params) =>
      fetchWithAuth<AttainmentReport>("/academic/attainment/analyze", {
        method: "POST",
        body: JSON.stringify(params),
      }),
  });
}

/* ------------------------------------------------------------------ */
/* Answer Key (Phase 4B)                                               */
/* ------------------------------------------------------------------ */

export interface AnswerKeyResponse {
  paper_title: string;
  total_marks: number;
  general_instructions: string;
  generation_mode: string;
  answers: Array<{
    question_index: number;
    question_text: string;
    marks: number;
    bloom_level: string;
    answer_quality: string;
    total_words: number;
    key_points: string[];
    source_context_preview: string;
    steps: Array<{
      step_number: number;
      content: string;
      marks: number;
      is_diagram: boolean;
      is_formula: boolean;
    }>;
  }>;
}

export function useGenerateAnswerKey() {
  return useMutation<AnswerKeyResponse, Error, { paper_title: string; questions: any[]; include_rubric?: boolean }>({
    mutationFn: async (params) =>
      fetchWithAuth<AnswerKeyResponse>("/academic/answer-key/generate", {
        method: "POST",
        body: JSON.stringify(params),
      }),
  });
}

/* ------------------------------------------------------------------ */
/* PDF Export (Phase 6B)                                                */
/* ------------------------------------------------------------------ */

async function fetchBlobWithAuth(url: string, body: any): Promise<Blob> {
  const token = localStorage.getItem("access_token");
  const response = await fetch(`${API_BASE_URL}${url}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token && { Authorization: `Bearer ${token}` }),
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Export failed" }));
    const apiError = new Error(error.detail || "Export failed") as Error & { status?: number };
    apiError.status = response.status;
    throw apiError;
  }
  return response.blob();
}

export function useExportPaperPdf() {
  return useMutation<Blob, Error, { questions: any[]; paper_meta: Record<string, any>; template_id?: string; co_descriptions?: Record<string, string> }>({
    mutationFn: (params) => fetchBlobWithAuth("/academic/export/pdf", params),
  });
}

export function useExportAnswerKeyPdf() {
  return useMutation<Blob, Error, { paper_title: string; questions: any[]; paper_meta: Record<string, any> }>({
    mutationFn: (params) => fetchBlobWithAuth("/academic/export/answer-key-pdf", params),
  });
}

export function useRegenerateSlot() {
  return useMutation<any, Error, { subject_id: number; marks: number; bloom_level: string; course_outcome: string; module_number: number; topic_name?: string; existing_questions?: string[] }>({
    mutationFn: async (params) =>
      fetchWithAuth<any>("/academic/regenerate-slot", {
        method: "POST",
        body: JSON.stringify(params),
      }),
  });
}

/* ------------------------------------------------------------------ */
/* Paper Variants (Phase 6A)                                           */
/* ------------------------------------------------------------------ */

export interface PaperVariant {
  variant_label: string;
  variant_id: string;
  questions: any[];
  seed: number;
  changes_from_original: string[];
}

export interface VariantSet {
  original_paper_title: string;
  total_marks: number;
  num_variants: number;
  variants: PaperVariant[];
}

export function useGenerateVariants() {
  return useMutation<VariantSet, Error, { paper_title: string; total_marks: number; questions: any[]; num_variants?: number }>({
    mutationFn: async (params) =>
      fetchWithAuth<VariantSet>("/academic/variants/generate", {
        method: "POST",
        body: JSON.stringify(params),
      }),
  });
}

/* ------------------------------------------------------------------ */
/* Batch Generation (Phase 6C)                                         */
/* ------------------------------------------------------------------ */

export interface BatchItemResult {
  index: number;
  subject_id: number;
  title: string;
  success: boolean;
  paper_id: number | null;
  question_count: number;
  variant_count: number;
  error: string | null;
  generation_time_ms: number;
}

export interface BatchResult {
  total_items: number;
  successful: number;
  failed: number;
  total_time_ms: number;
  items: BatchItemResult[];
}

export function useBatchGenerate() {
  return useMutation<BatchResult, Error, { items: any[] }>({
    mutationFn: async (params) =>
      fetchWithAuth<BatchResult>("/academic/batch/generate", {
        method: "POST",
        body: JSON.stringify(params),
      }),
  });
}

/* ------------------------------------------------------------------ */
/* Question Bank Analytics (Phase 6D-G)                                */
/* ------------------------------------------------------------------ */

export interface BloomHeatmapCell {
  module_number: number;
  bloom_level: string;
  count: number;
}

export interface OverlapMatch {
  question_id: number;
  text: string;
  compared_text: string;
  similarity: number;
  source: string;
}

export interface QBAnalytics {
  total_questions: number;
  verified_questions: number;
  pending_questions: number;
  previous_paper_questions: number;
  average_usage: number;
  freshness_buckets: Record<string, number>;
  bloom_heatmap: BloomHeatmapCell[];
  high_overlap_pairs: OverlapMatch[];
  most_used_questions: any[];
  stale_questions: any[];
}

export function useQBAnalytics(subjectId?: number) {
  return useQuery<QBAnalytics>({
    queryKey: ["qb-analytics", subjectId],
    queryFn: () => fetchWithAuth<QBAnalytics>(`/academic/qb-analytics/${subjectId}`),
    enabled: Boolean(subjectId),
    staleTime: 30000,
  });
}

export function useBloomHeatmap(subjectId?: number) {
  return useQuery<BloomHeatmapCell[]>({
    queryKey: ["bloom-heatmap", subjectId],
    queryFn: () => fetchWithAuth<BloomHeatmapCell[]>(`/academic/qb-analytics/${subjectId}/bloom-heatmap`),
    enabled: Boolean(subjectId),
    staleTime: 30000,
  });
}

export function useOverlapCheck() {
  return useMutation<{ threshold: number; matches: OverlapMatch[] }, Error, { subject_id?: number; questions: string[]; threshold?: number }>({
    mutationFn: async (params) =>
      fetchWithAuth<{ threshold: number; matches: OverlapMatch[] }>("/academic/qb-analytics/overlap-check", {
        method: "POST",
        body: JSON.stringify(params),
      }),
  });
}

/* ------------------------------------------------------------------ */
/* Template Mutations (Phase 2 — Settings Editor)                      */
/* ------------------------------------------------------------------ */

export function useSaveTemplate() {
  const queryClient = useQueryClient();
  return useMutation<Record<string, any>, Error, Record<string, any>>({
    mutationFn: async (template) =>
      fetchWithAuth<Record<string, any>>("/academic/templates", {
        method: "POST",
        body: JSON.stringify(template),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["templates"] });
    },
  });
}

export function useDeleteTemplate() {
  const queryClient = useQueryClient();
  return useMutation<{ deleted: boolean }, Error, string>({
    mutationFn: async (templateId) =>
      fetchWithAuth<{ deleted: boolean }>(`/academic/templates/${templateId}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["templates"] });
    },
  });
}
