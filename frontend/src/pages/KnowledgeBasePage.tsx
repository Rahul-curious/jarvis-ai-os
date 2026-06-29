import { FormEvent, useCallback, useEffect, useState } from 'react';

import {
  ApiError,
  deleteDocument,
  getCurrentUser,
  getDocument,
  KnowledgeDocument,
  listDocuments,
  logout,
  queryKnowledge,
  RagQueryResponse,
  RagSearchResult,
  searchKnowledge,
  UserProfile,
} from '../api/client';
import { RoutePath } from '../state/router';

type KnowledgeBasePageProps = {
  currentUser: UserProfile | null;
  navigate: (path: RoutePath) => void;
  onLogout: () => void;
  onUserLoaded: (user: UserProfile) => void;
};

export function KnowledgeBasePage({
  currentUser,
  navigate,
  onLogout,
  onUserLoaded,
}: KnowledgeBasePageProps) {
  const [isLoadingProfile, setIsLoadingProfile] = useState(currentUser === null);
  const [isLoadingDocuments, setIsLoadingDocuments] = useState(false);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [selectedDocument, setSelectedDocument] = useState<KnowledgeDocument | null>(null);
  const [query, setQuery] = useState('');
  const [topK, setTopK] = useState('5');
  const [searchResults, setSearchResults] = useState<RagSearchResult[]>([]);
  const [queryResponse, setQueryResponse] = useState<RagQueryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSearching, setIsSearching] = useState(false);

  useEffect(() => {
    let isMounted = true;

    async function loadProfile() {
      try {
        const user = await getCurrentUser();
        if (isMounted) {
          onUserLoaded(user);
        }
      } catch {
        if (isMounted) {
          navigate('/login');
        }
      } finally {
        if (isMounted) {
          setIsLoadingProfile(false);
        }
      }
    }

    if (currentUser === null) {
      void loadProfile();
    }

    return () => {
      isMounted = false;
    };
  }, [currentUser, navigate, onUserLoaded]);

  const loadDocuments = useCallback(async () => {
    setIsLoadingDocuments(true);
    setError(null);
    try {
      const response = await listDocuments();
      setDocuments(response.items);
      setSelectedDocument((current) => {
        if (current === null) {
          return response.items[0] ?? null;
        }
        return response.items.find((document) => document.id === current.id) ?? response.items[0] ?? null;
      });
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Unable to load documents');
    } finally {
      setIsLoadingDocuments(false);
    }
  }, []);

  useEffect(() => {
    if (currentUser !== null) {
      void loadDocuments();
    }
  }, [currentUser, loadDocuments]);

  async function handleLogout() {
    await logout();
    onLogout();
    navigate('/login');
  }

  async function handleSelectDocument(documentId: string) {
    setError(null);
    try {
      const document = await getDocument(documentId);
      setSelectedDocument(document);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Unable to load document');
    }
  }

  async function handleDeleteDocument(documentId: string) {
    setError(null);
    try {
      await deleteDocument(documentId);
      setSelectedDocument(null);
      await loadDocuments();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Unable to delete document');
    }
  }

  async function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setIsSearching(true);
    setQueryResponse(null);

    try {
      const response = await searchKnowledge({
        query,
        top_k: Number(topK),
        document_id: selectedDocument?.id ?? null,
      });
      setSearchResults(response.results);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Unable to search knowledge');
    } finally {
      setIsSearching(false);
    }
  }

  async function handleQuery() {
    setError(null);
    setIsSearching(true);

    try {
      const response = await queryKnowledge({
        query,
        top_k: Number(topK),
        document_id: selectedDocument?.id ?? null,
      });
      setQueryResponse(response);
      setSearchResults(response.context);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Unable to query knowledge');
    } finally {
      setIsSearching(false);
    }
  }

  if (isLoadingProfile) {
    return <p className="status-message">Loading knowledge access...</p>;
  }

  if (currentUser === null) {
    return null;
  }

  return (
    <section className="memory-dashboard" aria-labelledby="knowledge-title">
      <header className="memory-header">
        <div>
          <p className="eyebrow">Knowledge Base</p>
          <h1 id="knowledge-title">Grounded retrieval</h1>
          <p className="lede">
            Upload documents, inspect chunks, and query context with citations from indexed knowledge.
          </p>
        </div>
        <div className="dashboard-actions">
          <button onClick={() => navigate('/knowledge/upload')} type="button">
            Upload document
          </button>
          <button className="secondary-button" onClick={() => navigate('/dashboard')} type="button">
            Dashboard
          </button>
          <button className="secondary-button" onClick={handleLogout} type="button">
            Log out
          </button>
        </div>
      </header>

      {error ? <p className="form-error">{error}</p> : null}

      <div className="memory-layout">
        <section className="memory-panel" aria-label="Document list">
          <div className="panel-heading">
            <h2>Documents</h2>
            <span>{isLoadingDocuments ? 'Loading' : `${documents.length} indexed`}</span>
          </div>

          {documents.length === 0 ? (
            <p className="empty-state">No documents are indexed yet.</p>
          ) : (
            <div className="memory-list">
              {documents.map((document) => (
                <button
                  className={`memory-row ${selectedDocument?.id === document.id ? 'is-selected' : ''}`}
                  key={document.id}
                  onClick={() => void handleSelectDocument(document.id)}
                  type="button"
                >
                  <span className="memory-row-meta">
                    <strong>{document.status}</strong>
                    <span>{document.chunk_count} chunks</span>
                  </span>
                  <span>{document.filename}</span>
                  <span className="memory-score">{formatFileSize(document.file_size_bytes)}</span>
                </button>
              ))}
            </div>
          )}
        </section>

        <section className="memory-panel" aria-label="Document chunks">
          <div className="panel-heading">
            <h2>Chunks</h2>
            {selectedDocument ? <span>{selectedDocument.filename}</span> : null}
          </div>

          {selectedDocument ? (
            <div className="chunk-list">
              <dl className="memory-metrics">
                <div>
                  <dt>Embedding</dt>
                  <dd>{selectedDocument.embedding_model}</dd>
                </div>
                <div>
                  <dt>Collection</dt>
                  <dd>{selectedDocument.vector_collection}</dd>
                </div>
                <div>
                  <dt>Characters</dt>
                  <dd>{selectedDocument.text_length}</dd>
                </div>
              </dl>

              <div className="dashboard-actions">
                <button
                  className="danger-button"
                  onClick={() => void handleDeleteDocument(selectedDocument.id)}
                  type="button"
                >
                  Delete document
                </button>
              </div>

              {selectedDocument.chunks.map((chunk) => (
                <article className="chunk-card" key={chunk.id}>
                  <span>Chunk {chunk.chunk_index + 1}</span>
                  <p>{chunk.content}</p>
                </article>
              ))}
            </div>
          ) : (
            <p className="empty-state">Select a document to inspect stored chunks.</p>
          )}
        </section>
      </div>

      <section className="memory-panel" aria-labelledby="rag-query-title">
        <div className="panel-heading">
          <h2 id="rag-query-title">Ask uploaded knowledge</h2>
          <span>{selectedDocument ? `Scoped to ${selectedDocument.filename}` : 'All documents'}</span>
        </div>

        <form className="knowledge-query-form" onSubmit={handleSearch}>
          <label>
            Question or search query
            <input
              onChange={(event) => setQuery(event.target.value)}
              required
              type="search"
              value={query}
            />
          </label>
          <label>
            Top K
            <input
              max="20"
              min="1"
              onChange={(event) => setTopK(event.target.value)}
              type="number"
              value={topK}
            />
          </label>
          <button disabled={isSearching} type="submit">
            {isSearching ? 'Searching...' : 'Search'}
          </button>
          <button
            className="secondary-button"
            disabled={isSearching || !query.trim()}
            onClick={() => void handleQuery()}
            type="button"
          >
            Query answer
          </button>
        </form>

        {queryResponse ? (
          <article className="rag-answer">
            <h3>Grounded answer</h3>
            <p>{queryResponse.answer}</p>
          </article>
        ) : null}

        <div className="chunk-list">
          {searchResults.map((result) => (
            <article className="chunk-card" key={result.chunk_id}>
              <span>
                {result.citation}
                {result.distance !== null ? ` · distance ${result.distance.toFixed(4)}` : ''}
              </span>
              <p>{result.content}</p>
            </article>
          ))}
        </div>
      </section>
    </section>
  );
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
