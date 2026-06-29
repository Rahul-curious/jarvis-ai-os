const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

export type UserProfile = {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  is_admin: boolean;
  last_login_at: string | null;
  created_at: string;
};

export type AuthResponse = {
  user: UserProfile;
};

export type RegisterPayload = {
  full_name: string;
  email: string;
  password: string;
};

export type LoginPayload = {
  email: string;
  password: string;
};

export type MemoryType = 'short_term' | 'long_term' | 'user_preference' | 'project' | 'correction';

export type MemoryReference = {
  id: string;
  reference_type: string;
  reference_id: string | null;
  label: string | null;
  url: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type MemoryItem = {
  id: string;
  user_id: string;
  memory_type: MemoryType;
  category: string;
  content: string;
  importance_score: number;
  reinforcement_count: number;
  memory_score: number;
  source: string;
  expires_at: string | null;
  created_at: string;
  updated_at: string;
  last_accessed_at: string | null;
  references: MemoryReference[];
};

export type MemoryListResponse = {
  items: MemoryItem[];
  total: number;
  limit: number;
  offset: number;
};

export type MemoryReferencePayload = {
  reference_type: string;
  reference_id?: string | null;
  label?: string | null;
  url?: string | null;
  metadata?: Record<string, unknown>;
};

export type MemoryCreatePayload = {
  memory_type: MemoryType;
  category: string;
  content: string;
  importance_score: number;
  source: string;
  expires_at?: string | null;
  references?: MemoryReferencePayload[];
};

export type MemoryUpdatePayload = Partial<MemoryCreatePayload>;

export type MemorySearchPayload = {
  keyword?: string | null;
  category?: string | null;
  memory_type?: MemoryType | null;
  min_importance_score?: number | null;
  include_expired?: boolean;
  limit?: number;
  offset?: number;
};

export type MemoryReinforcePayload = {
  memory_id: string;
  amount?: number;
  reason?: string | null;
};

export type DocumentChunk = {
  id: string;
  document_id: string;
  chunk_index: number;
  content: string;
  char_count: number;
  content_hash: string;
  vector_id: string;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type KnowledgeDocument = {
  id: string;
  user_id: string;
  filename: string;
  content_type: string;
  file_size_bytes: number;
  checksum_sha256: string;
  status: string;
  chunk_count: number;
  text_length: number;
  embedding_model: string;
  vector_collection: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  chunks: DocumentChunk[];
};

export type DocumentListResponse = {
  items: KnowledgeDocument[];
  total: number;
  limit: number;
  offset: number;
};

export type RagSearchPayload = {
  query: string;
  top_k?: number;
  document_id?: string | null;
};

export type RagSearchResult = {
  document_id: string;
  document_filename: string;
  chunk_id: string;
  chunk_index: number;
  content: string;
  distance: number | null;
  citation: string;
  metadata: Record<string, unknown>;
};

export type RagSearchResponse = {
  query: string;
  results: RagSearchResult[];
};

export type RagCitation = {
  document_id: string;
  document_filename: string;
  chunk_id: string;
  chunk_index: number;
  citation: string;
};

export type RagQueryResponse = {
  question: string;
  answer: string;
  context: RagSearchResult[];
  citations: RagCitation[];
};

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
  }
}

export async function register(payload: RegisterPayload): Promise<AuthResponse> {
  return request<AuthResponse>('/api/v1/auth/register', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function login(payload: LoginPayload): Promise<AuthResponse> {
  return request<AuthResponse>('/api/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function logout(): Promise<void> {
  await request<{ detail: string }>('/api/v1/auth/logout', { method: 'POST' });
}

export async function getCurrentUser(): Promise<UserProfile> {
  return request<UserProfile>('/api/v1/users/me');
}

export async function listMemories(query: MemorySearchPayload = {}): Promise<MemoryListResponse> {
  const searchParams = new URLSearchParams();
  if (query.memory_type) {
    searchParams.set('memory_type', query.memory_type);
  }
  if (query.category) {
    searchParams.set('category', query.category);
  }
  if (query.include_expired) {
    searchParams.set('include_expired', 'true');
  }
  if (query.limit) {
    searchParams.set('limit', String(query.limit));
  }
  if (query.offset) {
    searchParams.set('offset', String(query.offset));
  }

  const suffix = searchParams.toString() ? `?${searchParams.toString()}` : '';
  return request<MemoryListResponse>(`/api/v1/memory${suffix}`);
}

export async function createMemory(payload: MemoryCreatePayload): Promise<MemoryItem> {
  return request<MemoryItem>('/api/v1/memory', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function getMemory(memoryId: string): Promise<MemoryItem> {
  return request<MemoryItem>(`/api/v1/memory/${memoryId}`);
}

export async function updateMemory(
  memoryId: string,
  payload: MemoryUpdatePayload,
): Promise<MemoryItem> {
  return request<MemoryItem>(`/api/v1/memory/${memoryId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export async function deleteMemory(memoryId: string): Promise<void> {
  await request<{ detail: string }>(`/api/v1/memory/${memoryId}`, { method: 'DELETE' });
}

export async function searchMemories(payload: MemorySearchPayload): Promise<MemoryListResponse> {
  return request<MemoryListResponse>('/api/v1/memory/search', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function reinforceMemory(payload: MemoryReinforcePayload): Promise<MemoryItem> {
  return request<MemoryItem>('/api/v1/memory/reinforce', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function uploadDocument(file: File): Promise<KnowledgeDocument> {
  const formData = new FormData();
  formData.append('file', file);
  return request<KnowledgeDocument>('/api/v1/documents/upload', {
    method: 'POST',
    body: formData,
  });
}

export async function listDocuments(limit = 50): Promise<DocumentListResponse> {
  return request<DocumentListResponse>(`/api/v1/documents?limit=${limit}`);
}

export async function getDocument(documentId: string): Promise<KnowledgeDocument> {
  return request<KnowledgeDocument>(`/api/v1/documents/${documentId}`);
}

export async function deleteDocument(documentId: string): Promise<void> {
  await request<{ detail: string }>(`/api/v1/documents/${documentId}`, { method: 'DELETE' });
}

export async function searchKnowledge(payload: RagSearchPayload): Promise<RagSearchResponse> {
  return request<RagSearchResponse>('/api/v1/rag/search', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function queryKnowledge(payload: RagSearchPayload): Promise<RagQueryResponse> {
  return request<RagQueryResponse>('/api/v1/rag/query', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers =
    init.body instanceof FormData
      ? init.headers
      : {
          'Content-Type': 'application/json',
          ...init.headers,
        };

  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    credentials: 'include',
    headers,
  });

  if (!response.ok) {
    const message = await readErrorMessage(response);
    throw new ApiError(message, response.status);
  }

  return response.json() as Promise<T>;
}

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string };
    return body.detail ?? 'Request failed';
  } catch {
    return 'Request failed';
  }
}
