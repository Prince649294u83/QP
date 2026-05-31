import { useMutation, useQuery } from "@tanstack/react-query";

const API_BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000/api/v1";

let authTokenGetter: () => string | null = () => localStorage.getItem("access_token");

export function setAuthTokenGetter(getter: () => string | null) {
  authTokenGetter = getter;
}

function buildUrl(path: string, params?: Record<string, unknown>) {
  const url = new URL(`${API_BASE_URL}${path}`);
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") {
      return;
    }
    url.searchParams.set(key, String(value));
  });
  return url.toString();
}

async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
  params?: Record<string, unknown>,
): Promise<T> {
  const token = authTokenGetter();
  const headers: HeadersInit = {
    ...(options.headers || {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };

  if (!(options.body instanceof FormData) && options.body !== undefined) {
    (headers as Record<string, string>)["Content-Type"] = "application/json";
  }

  const response = await fetch(buildUrl(path, params), { ...options, headers });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Request failed" }));
    const apiError = new Error(error.detail || "Request failed") as Error & { status?: number; response?: any };
    apiError.status = response.status;
    apiError.response = { status: response.status, data: error };
    throw apiError;
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

function mutationOptions(options?: any) {
  return options?.mutation || {};
}

export function useLoginApiV1AuthLoginPost(options?: any): any {
  return useMutation({
    mutationFn: ({ data }: { data: { email: string; password: string } }) =>
      apiFetch("/auth/login", { method: "POST", body: JSON.stringify(data) }),
    ...mutationOptions(options),
  });
}

export function useSubjectsApiV1SubjectsGet(options?: any): any {
  return useQuery<any[]>({
    queryKey: ["subjects"],
    queryFn: () => apiFetch<any[]>("/subjects"),
    staleTime: 60_000,
    ...(options?.query || {}),
  });
}

export function getListPapersApiV1PapersGetQueryKey() {
  return ["papers"] as const;
}

export function useListPapersApiV1PapersGet(options?: any): any {
  return useQuery<any[]>({
    queryKey: getListPapersApiV1PapersGetQueryKey(),
    queryFn: () => apiFetch<any[]>("/papers"),
    staleTime: 30_000,
    ...(options?.query || {}),
  });
}

export function useRemovePaperApiV1PapersPaperIdDelete(options?: any): any {
  return useMutation({
    mutationFn: ({ paperId }: { paperId: number }) =>
      apiFetch(`/papers/${paperId}`, { method: "DELETE" }),
    ...mutationOptions(options),
  });
}

export function getListQuestionsApiV1QuestionsGetQueryKey() {
  return ["questions"] as const;
}

export function useListQuestionsApiV1QuestionsGet(params?: Record<string, unknown>, options?: any): any {
  return useQuery<any[]>({
    queryKey: [...getListQuestionsApiV1QuestionsGetQueryKey(), params || {}],
    queryFn: () => apiFetch<any[]>("/questions", {}, params),
    staleTime: 30_000,
    ...(options?.query || {}),
  });
}

export function useAddQuestionApiV1QuestionsPost(options?: any): any {
  return useMutation({
    mutationFn: ({ data }: { data: Record<string, unknown> }) =>
      apiFetch("/questions", { method: "POST", body: JSON.stringify(data) }),
    ...mutationOptions(options),
  });
}

export function useRemoveQuestionApiV1QuestionsQuestionIdDelete(options?: any): any {
  return useMutation({
    mutationFn: (questionId: number | { questionId: number }) => {
      const id = typeof questionId === "number" ? questionId : questionId.questionId;
      return apiFetch(`/questions/${id}`, { method: "DELETE" });
    },
    ...mutationOptions(options),
  });
}

export function getPendingReviewsApiV1ReviewsPendingGetQueryKey() {
  return ["pending-reviews"] as const;
}

export function usePendingReviewsApiV1ReviewsPendingGet(options?: any): any {
  return useQuery<any[]>({
    queryKey: getPendingReviewsApiV1ReviewsPendingGetQueryKey(),
    queryFn: () => apiFetch<any[]>("/reviews/pending"),
    staleTime: 30_000,
    ...(options?.query || {}),
  });
}

export function useTakeReviewActionApiV1ReviewsPaperIdActionPost(options?: any): any {
  return useMutation({
    mutationFn: ({ paperId, data }: { paperId: number; data: Record<string, unknown> }) =>
      apiFetch(`/reviews/${paperId}/action`, { method: "POST", body: JSON.stringify(data) }),
    ...mutationOptions(options),
  });
}
