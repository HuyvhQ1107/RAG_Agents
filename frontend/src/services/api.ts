export interface GroupSummary {
  id: string;
  name: string;
  description?: string | null;
}

export interface UserProfile {
  id: string;
  username: string;
  display_name: string;
  email?: string | null;
  roles: string[];
  groups: GroupSummary[];
  must_change_password: boolean;
  preferred_language: "vi" | "en";
}

export interface DocumentScopeItem {
  id: string;
  title: string;
  effective_from?: string | null;
  expires_on?: string | null;
  language: string;
}

export interface CitationItem {
  marker: number;
  citation_id: string;
  document_id: string;
  document_title: string;
  version_number: number;
  section_path: string;
  page_start?: number | null;
  page_end?: number | null;
  effective_from?: string | null;
  snippet: string;
  full_content?: string;
}

export interface ClarificationOption {
  id: string;
  label: string;
}

export interface TurnItem {
  id: string;
  ordinal: number;
  question: string;
  kind:
    | "answer"
    | "clarification"
    | "refusal_not_found"
    | "refusal_unsupported"
    | "refusal_out_of_scope"
    | "partial_answer"
    | "error";
  answer_language: "vi" | "en";
  answer: string;
  clarification_options?: ClarificationOption[] | null;
  assumptions: string[];
  missing_parts: string[];
  limit_reached: boolean;
  latency_ms: number;
  citations: CitationItem[];
}

export interface ConversationDetail {
  id: string;
  title: string;
  scope_document_id?: string | null;
  scope_document_title?: string | null;
  pending_clarification_count: number;
  turns: TurnItem[];
}

export interface AdminUserItem {
  id: string;
  username: string;
  display_name: string;
  email?: string | null;
  roles: string[];
  status: string;
  must_change_password: boolean;
  groups: Array<{ id: string; name: string }>;
}

export interface AdminGroupItem {
  id: string;
  name: string;
  description?: string | null;
  deleted_at?: string | null;
  member_count?: number;
  document_count?: number;
}

export interface AdminDocumentItem {
  id: string;
  title: string;
  is_company_wide: boolean;
  effective_from?: string | null;
  expires_on?: string | null;
  current_version_id?: string | null;
  status: string;
  display_status: string;
  latest_error_code?: string | null;
  latest_error_detail?: string | null;
  is_orphaned: boolean;
  groups: Array<{ id: string; name: string }>;
  version_count: number;
}

export interface OpsMetricsSummary {
  total_turns: number;
  latency_p50_ms: number;
  latency_p95_ms: number;
  ttft_p50_ms: number;
  ttft_p95_ms: number;
  error_rate: number;
  not_found_rate: number;
  clarification_rate: number;
  limit_reached_rate: number;
  helpful_feedback_rate: number;
  total_feedback_count: number;
  total_cost_usd: number;
  daily_cost_usd: Record<string, number>;
}

export interface FeedbackQueueItem {
  id: string;
  turn_id: string;
  rating: string;
  comment?: string | null;
  masked_question: string;
  masked_answer: string;
  kind: string;
  created_at: string;
}

export class ApiClientError extends Error {
  status: number;
  code: string;
  traceId?: string;

  constructor(status: number, code: string, message: string, traceId?: string) {
    super(message);
    this.status = status;
    this.code = code;
    this.traceId = traceId;
  }
}

export async function apiRequest<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const headers = new Headers(options.headers || {});
  if (!(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const resp = await fetch(`/api/v1${path}`, {
    ...options,
    headers,
    credentials: "include",
  });

  if (resp.status === 204) {
    return undefined as T;
  }

  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const errObj = data?.error || {};
    throw new ApiClientError(
      resp.status,
      errObj.code || `http_${resp.status}`,
      errObj.message || resp.statusText,
      errObj.trace_id
    );
  }
  return data as T;
}

export const authApi = {
  login: (username: string, password: string) =>
    apiRequest<void>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  logout: () => apiRequest<void>("/auth/logout", { method: "POST" }),
  me: () => apiRequest<UserProfile>("/auth/me"),
  changePassword: (current_password: string, new_password: string) =>
    apiRequest<void>("/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password, new_password }),
    }),
};

export const getMe = authApi.me;
export const logout = authApi.logout;

export const listAdminUsers = () =>
  apiRequest<{ items: AdminUserItem[] }>("/admin/users");

export const createAdminUser = (payload: {
  username: string;
  display_name: string;
  email?: string;
  roles: string[];
  group_ids: string[];
}) =>
  apiRequest<{ user: AdminUserItem; temporary_password: string }>("/admin/users", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const updateAdminUser = (
  userId: string,
  payload: { status?: string; roles?: string[]; group_ids?: string[] }
) =>
  apiRequest<AdminUserItem>(`/admin/users/${userId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });

export const resetAdminUserPassword = (userId: string) =>
  apiRequest<{ temporary_password: string }>(`/admin/users/${userId}/reset-password`, {
    method: "POST",
  });

export const listAdminGroups = () =>
  apiRequest<{ items: AdminGroupItem[] }>("/admin/groups");

export const createAdminGroup = (payload: {
  name: string;
  description?: string;
}) =>
  apiRequest<AdminGroupItem>("/admin/groups", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const deleteAdminGroup = (groupId: string) =>
  apiRequest<{ id: string; deleted_at: string; orphaned_document_ids: string[] }>(
    `/admin/groups/${groupId}`,
    { method: "DELETE" }
  );

export const listAdminDocuments = () =>
  apiRequest<{ items: AdminDocumentItem[] }>("/admin/documents");

export const uploadAdminDocuments = (params: {
  files: File[];
  is_company_wide: boolean;
  group_ids: string[];
  effective_from?: string;
  expires_on?: string;
}) => {
  const form = new FormData();
  for (const f of params.files) {
    form.append("files", f);
  }
  form.append(
    "metadata",
    JSON.stringify({
      is_company_wide: params.is_company_wide,
      group_ids: params.group_ids,
      effective_from: params.effective_from || null,
      expires_on: params.expires_on || null,
    })
  );
  return apiRequest<{ items: Array<{ document_id: string; status: string }> }>(
    "/admin/documents",
    {
      method: "POST",
      body: form,
    }
  );
};

export const updateAdminDocument = (
  docId: string,
  payload: { is_company_wide?: boolean; group_ids?: string[] }
) =>
  apiRequest<AdminDocumentItem>(`/admin/documents/${docId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });

export const deleteAdminDocument = (docId: string) =>
  apiRequest<void>(`/admin/documents/${docId}`, { method: "DELETE" });

export const getOpsMetricsSummary = () =>
  apiRequest<OpsMetricsSummary>("/ops/metrics/summary");

export const listNegativeFeedback = () =>
  apiRequest<{ items: FeedbackQueueItem[] }>("/ops/feedback");

export const getOpsTurnTrace = (turnId: string) =>
  apiRequest<any>(`/ops/turns/${turnId}/trace`);
