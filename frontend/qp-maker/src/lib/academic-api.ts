/**
 * Academic Knowledge Intelligence Layer — API Client
 * TanStack Query hooks for all academic endpoints.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

export const API = import.meta.env.VITE_API_URL || "http://localhost:8000/api/v1";

export async function authFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const token = localStorage.getItem("access_token");
  const headers: HeadersInit = {
    ...(init?.headers ?? {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
  // Don't set Content-Type for FormData
  if (!(init?.body instanceof FormData)) {
    (headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  const res = await fetch(`${API}${url}`, { ...init, headers });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Request failed" }));
    const apiError = new Error(err.detail || "Request failed") as Error & { status?: number };
    apiError.status = res.status;
    throw apiError;
  }
  return res.json();
}

export async function authFetchBlob(url: string, init?: RequestInit): Promise<Blob> {
  const token = localStorage.getItem("access_token");
  const headers: HeadersInit = {
    ...(init?.headers ?? {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
  const res = await fetch(`${API}${url}`, { ...init, headers });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Request failed" }));
    const apiError = new Error(err.detail || "Request failed") as Error & { status?: number };
    apiError.status = res.status;
    throw apiError;
  }
  return res.blob();
}

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

export type DocumentType = "notes" | "question_bank" | "previous_paper" | "syllabus" | "lab_manual" | "ppt" | "other";
export type ProcessingStatus = "pending" | "extracting" | "chunking" | "embedding" | "completed" | "failed";
export type ChunkApprovalStatus = "auto_approved" | "pending_review" | "approved" | "rejected" | "edited";

export interface AcademicDocument {
  id: number;
  subject_id: number;
  uploaded_by: number;
  file_name: string;
  file_type: string;
  document_type: DocumentType;
  processing_status: ProcessingStatus;
  processing_error: string | null;
  page_count: number | null;
  total_chunks: number;
  created_at: string;
}

export interface DocumentChunkResponse {
  id: number;
  page: number;
  text: string;
  source_type: string;
  block_index: number;
}

export interface DocumentImageResponse {
  id: number;
  image_path: string;
  image_available?: boolean;
  source_page: number;
  keywords: string[];
  context_before: string;
  context_after: string;
  ai_caption: string;
  width: number | null;
  height: number | null;
}

export interface DocumentPreviewResponse {
  id: number;
  filename: string;
  parsed_text: string;
  chunks: DocumentChunkResponse[];
  images: DocumentImageResponse[];
}

export interface KnowledgeChunk {
  id: number;
  document_id: number;
  subject_id: number;
  chunk_text: string;
  chunk_summary: string | null;
  chunk_index: number;
  token_count: number;
  module_number: number | null;
  syllabus_unit: string | null;
  topic_name: string | null;
  bloom_level: string | null;
  co_mapping: string | null;
  page_number: number | null;
  confidence_score: number;
  approval_status: ChunkApprovalStatus;
  reviewed_by: number | null;
  review_notes: string | null;
  created_at: string;
}

export interface SubjectSyllabus {
  id: number;
  subject_id: number;
  syllabus_text: string | null;
  modules_json: Array<{ module: number; title: string; topics: string[] }> | null;
  co_json: Record<string, string> | null;
  rbt_rules: Record<string, string[]> | null;
  created_at: string;
}

export interface GenerationProfile {
  id: number;
  subject_id: number;
  use_notes: boolean;
  use_question_bank: boolean;
  use_previous_papers: boolean;
  use_syllabus: boolean;
  strict_vtu_mode: boolean;
  strict_syllabus_mode: boolean;
  creativity_level: number;
  created_at: string;
}

export interface TopicCoverageItem {
  module_number: number;
  topic_name: string;
  chunk_count: number;
  document_count: number;
  avg_confidence: number;
}

export interface TopicCoverage {
  subject_id: number;
  total_chunks: number;
  total_documents: number;
  coverage: TopicCoverageItem[];
  gaps: string[];
}

/* ------------------------------------------------------------------ */
/*  Documents                                                          */
/* ------------------------------------------------------------------ */

export function useDocumentPreview(documentId: number) {
  return useQuery({
    queryKey: ["document-preview", documentId],
    queryFn: () => authFetch<DocumentPreviewResponse>(`/academic/documents/${documentId}/preview`),
    enabled: !!documentId,
    retry: false,
  });
}

export function useAcademicDocuments(subjectId?: number, documentType?: string) {
  return useQuery({
    queryKey: ["academic-documents", subjectId, documentType],
    queryFn: () => {
      const p = new URLSearchParams();
      if (subjectId) p.set("subject_id", String(subjectId));
      if (documentType) p.set("document_type", documentType);
      return authFetch<{ documents: AcademicDocument[]; total: number }>(
        `/academic/documents?${p}`
      );
    },
    staleTime: 15_000,
    refetchInterval: (query) => {
      // Poll every 3 seconds if any document is not 'completed' or 'failed'
      const data = query.state.data;
      if (!data) return false;
      const hasPending = data.documents.some(
        (doc) => doc.processing_status !== "completed" && doc.processing_status !== "failed"
      );
      return hasPending ? 3000 : false;
    },
  });
}

export function useUploadAcademicDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      subjectId,
      file,
      documentType,
    }: {
      subjectId: number;
      file: File;
      documentType: DocumentType;
    }) => {
      const fd = new FormData();
      fd.append("subject_id", String(subjectId));
      fd.append("document_type", documentType);
      fd.append("file", file);
      return authFetch<AcademicDocument>("/academic/documents/upload", {
        method: "POST",
        body: fd,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["academic-documents"] });
      qc.invalidateQueries({ queryKey: ["academic-chunks"] });
      qc.invalidateQueries({ queryKey: ["topic-coverage"] });
    },
  });
}

export function useDeleteAcademicDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      authFetch<{ deleted: boolean }>(`/academic/documents/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["academic-documents"] });
      qc.invalidateQueries({ queryKey: ["academic-chunks"] });
    },
  });
}

/* ------------------------------------------------------------------ */
/*  Knowledge Chunks                                                   */
/* ------------------------------------------------------------------ */

export function useKnowledgeChunks(opts?: {
  documentId?: number;
  subjectId?: number;
  moduleNumber?: number;
  approvalStatus?: string;
  limit?: number;
  offset?: number;
}) {
  return useQuery({
    queryKey: ["academic-chunks", opts],
    queryFn: () => {
      const p = new URLSearchParams();
      if (opts?.documentId) p.set("document_id", String(opts.documentId));
      if (opts?.subjectId) p.set("subject_id", String(opts.subjectId));
      if (opts?.moduleNumber) p.set("module_number", String(opts.moduleNumber));
      if (opts?.approvalStatus) p.set("approval_status", opts.approvalStatus);
      if (opts?.limit) p.set("limit", String(opts.limit));
      if (opts?.offset) p.set("offset", String(opts.offset));
      return authFetch<KnowledgeChunk[]>(`/academic/chunks?${p}`);
    },
    staleTime: 15_000,
  });
}

export function useSearchChunks(query: string, subjectId?: number, moduleNumber?: number) {
  return useQuery({
    queryKey: ["chunk-search", query, subjectId, moduleNumber],
    queryFn: () => {
      const p = new URLSearchParams({ query });
      if (subjectId) p.set("subject_id", String(subjectId));
      if (moduleNumber) p.set("module_number", String(moduleNumber));
      return authFetch<{ chunks: KnowledgeChunk[]; total: number; query: string }>(
        `/academic/chunks/search?${p}`
      );
    },
    enabled: query.length >= 2,
    staleTime: 30_000,
  });
}

export function useApproveChunk() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      chunkId,
      status,
      notes,
    }: {
      chunkId: number;
      status: ChunkApprovalStatus;
      notes?: string;
    }) =>
      authFetch<KnowledgeChunk>(`/academic/chunks/${chunkId}/approve`, {
        method: "PUT",
        body: JSON.stringify({ approval_status: status, review_notes: notes }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["academic-chunks"] }),
  });
}

export function useEditChunk() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ chunkId, ...data }: { chunkId: number } & Record<string, unknown>) =>
      authFetch<KnowledgeChunk>(`/academic/chunks/${chunkId}/edit`, {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["academic-chunks"] }),
  });
}

/* ------------------------------------------------------------------ */
/*  Syllabus                                                           */
/* ------------------------------------------------------------------ */

export function useSyllabus(subjectId: number) {
  return useQuery({
    queryKey: ["syllabus", subjectId],
    queryFn: () => authFetch<SubjectSyllabus>(`/academic/syllabus/${subjectId}`),
    enabled: !!subjectId,
    retry: false,
  });
}

export function useUpsertSyllabus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      subject_id: number;
      syllabus_text?: string;
      modules?: Array<{ module: number; title: string; topics: string[] }>;
      co_definitions?: Record<string, string>;
      rbt_rules?: Record<string, string[]>;
    }) =>
      authFetch<SubjectSyllabus>("/academic/syllabus", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: (_, vars) => qc.invalidateQueries({ queryKey: ["syllabus", vars.subject_id] }),
  });
}

/* ------------------------------------------------------------------ */
/*  Generation Profile                                                 */
/* ------------------------------------------------------------------ */

export function useGenerationProfile(subjectId: number) {
  return useQuery({
    queryKey: ["gen-profile", subjectId],
    queryFn: () => authFetch<GenerationProfile>(`/academic/profile/${subjectId}`),
    enabled: !!subjectId,
  });
}

export function useUpdateGenerationProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ subjectId, ...data }: { subjectId: number } & Record<string, unknown>) =>
      authFetch<GenerationProfile>(`/academic/profile/${subjectId}`, {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    onSuccess: (_, vars) => qc.invalidateQueries({ queryKey: ["gen-profile", vars.subjectId] }),
  });
}

/* ------------------------------------------------------------------ */
/*  Coverage Analytics                                                 */
/* ------------------------------------------------------------------ */

export function useTopicCoverage(subjectId: number) {
  return useQuery({
    queryKey: ["topic-coverage", subjectId],
    queryFn: () => authFetch<TopicCoverage>(`/academic/coverage/${subjectId}`),
    enabled: !!subjectId,
    staleTime: 30_000,
  });
}

/* ------------------------------------------------------------------ */
/*  RAG Generation (Phase 6)                                           */
/* ------------------------------------------------------------------ */

export interface RAGGenerationRequest {
  subject_id: number;
  num_questions?: number;
  marks_distribution?: Record<number, number>;
  bloom_levels?: string[];
  co_targets?: string[];
  question_types?: string[];
  module_filter?: number;
  additional_instructions?: string;
  creativity_override?: number;
  existing_question_texts?: string[];
}

export interface RAGGeneratedQuestion {
  text: string;
  marks: number;
  bloom_level: string;
  co_mapping: string;
  module_number: number | null;
  question_type: string;
  topic_name: string | null;
  source_chunk_ids: number[];
  source_documents: string[];
  confidence: number;
  is_valid: boolean;
  validation_errors: string[];
  validation_warnings: string[];
}

export interface RAGGenerationResponse {
  questions: RAGGeneratedQuestion[];
  retrieval_summary: {
    total_retrieved: number;
    sources_used?: string[];
    topics_covered?: string[];
    error?: string;
  };
  validation_summary: {
    total: number;
    valid: number;
    errors: number;
    warnings?: number;
  };
  generation_time: number;
  model_used: string;
  creativity_level: number;
  temperature: number;
}

export function useRAGGenerate() {
  return useMutation({
    mutationFn: (params: RAGGenerationRequest) =>
      authFetch<RAGGenerationResponse>("/academic/generate", {
        method: "POST",
        body: JSON.stringify(params),
      }),
  });
}
