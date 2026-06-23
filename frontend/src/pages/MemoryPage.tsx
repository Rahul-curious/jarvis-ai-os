import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';

import {
  ApiError,
  createMemory,
  deleteMemory,
  getCurrentUser,
  getMemory,
  listMemories,
  logout,
  MemoryItem,
  MemoryType,
  reinforceMemory,
  searchMemories,
  updateMemory,
  UserProfile,
} from '../api/client';
import { RoutePath } from '../state/router';

type MemoryPageProps = {
  currentUser: UserProfile | null;
  navigate: (path: RoutePath) => void;
  onLogout: () => void;
  onUserLoaded: (user: UserProfile) => void;
};

type MemoryFormState = {
  memory_type: MemoryType;
  category: string;
  content: string;
  importance_score: string;
  source: string;
  expires_at: string;
};

const memoryTypes: Array<{ value: MemoryType; label: string }> = [
  { value: 'short_term', label: 'Short term' },
  { value: 'long_term', label: 'Long term' },
  { value: 'user_preference', label: 'User preference' },
  { value: 'project', label: 'Project' },
  { value: 'correction', label: 'Correction' },
];

const emptyForm: MemoryFormState = {
  memory_type: 'long_term',
  category: '',
  content: '',
  importance_score: '0.5',
  source: 'manual',
  expires_at: '',
};

export function MemoryPage({
  currentUser,
  navigate,
  onLogout,
  onUserLoaded,
}: MemoryPageProps) {
  const [isLoadingProfile, setIsLoadingProfile] = useState(currentUser === null);
  const [isLoadingMemories, setIsLoadingMemories] = useState(false);
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [selectedMemory, setSelectedMemory] = useState<MemoryItem | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState<MemoryType | ''>('');
  const [includeExpired, setIncludeExpired] = useState(false);
  const [formState, setFormState] = useState<MemoryFormState>(emptyForm);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  const activeUser = currentUser;

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

  const loadMemories = useCallback(async () => {
    setIsLoadingMemories(true);
    setError(null);

    try {
      const hasSearchInput =
        searchTerm.trim() !== '' || categoryFilter.trim() !== '' || typeFilter !== '' || includeExpired;
      const response = hasSearchInput
        ? await searchMemories({
            keyword: searchTerm.trim() || null,
            category: categoryFilter.trim() || null,
            memory_type: typeFilter || null,
            include_expired: includeExpired,
            limit: 100,
          })
        : await listMemories({ limit: 100 });

      setMemories(response.items);
      setSelectedMemory((current) => {
        if (current === null) {
          return response.items[0] ?? null;
        }
        return response.items.find((item) => item.id === current.id) ?? response.items[0] ?? null;
      });
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Unable to load memories');
    } finally {
      setIsLoadingMemories(false);
    }
  }, [categoryFilter, includeExpired, searchTerm, typeFilter]);

  useEffect(() => {
    if (activeUser !== null) {
      void loadMemories();
    }
  }, [activeUser, loadMemories]);

  const categories = useMemo(
    () => Array.from(new Set(memories.map((memory) => memory.category))).sort(),
    [memories],
  );

  async function handleLogout() {
    await logout();
    onLogout();
    navigate('/login');
  }

  async function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await loadMemories();
  }

  async function handleSelectMemory(memoryId: string) {
    setError(null);
    try {
      const recalled = await getMemory(memoryId);
      setSelectedMemory(recalled);
      setMemories((items) => items.map((item) => (item.id === recalled.id ? recalled : item)));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Unable to recall memory');
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    setIsSaving(true);

    const importanceScore = Number(formState.importance_score);
    if (Number.isNaN(importanceScore)) {
      setFormError('Importance score must be a number between 0 and 1.');
      setIsSaving(false);
      return;
    }

    try {
      const payload = {
        memory_type: formState.memory_type,
        category: formState.category,
        content: formState.content,
        importance_score: importanceScore,
        source: formState.source,
        expires_at: formState.expires_at ? new Date(formState.expires_at).toISOString() : null,
      };

      const saved = editingId
        ? await updateMemory(editingId, payload)
        : await createMemory(payload);

      setSelectedMemory(saved);
      setFormState(emptyForm);
      setEditingId(null);
      await loadMemories();
    } catch (caught) {
      setFormError(caught instanceof ApiError ? caught.message : 'Unable to save memory');
    } finally {
      setIsSaving(false);
    }
  }

  function handleEdit(memory: MemoryItem) {
    setEditingId(memory.id);
    setFormState({
      memory_type: memory.memory_type,
      category: memory.category,
      content: memory.content,
      importance_score: String(memory.importance_score),
      source: memory.source,
      expires_at: memory.expires_at ? toDatetimeLocal(memory.expires_at) : '',
    });
  }

  async function handleDelete(memoryId: string) {
    setError(null);
    try {
      await deleteMemory(memoryId);
      setSelectedMemory(null);
      setEditingId((current) => (current === memoryId ? null : current));
      await loadMemories();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Unable to delete memory');
    }
  }

  async function handleReinforce(memoryId: string) {
    setError(null);
    try {
      const reinforced = await reinforceMemory({
        memory_id: memoryId,
        amount: 1,
        reason: 'Manually reinforced from memory dashboard',
      });
      setSelectedMemory(reinforced);
      setMemories((items) => items.map((item) => (item.id === reinforced.id ? reinforced : item)));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Unable to reinforce memory');
    }
  }

  if (isLoadingProfile) {
    return <p className="status-message">Loading memory access...</p>;
  }

  if (activeUser === null) {
    return null;
  }

  return (
    <section className="memory-dashboard" aria-labelledby="memory-title">
      <header className="memory-header">
        <div>
          <p className="eyebrow">Memory Engine</p>
          <h1 id="memory-title">JARVIS memory</h1>
          <p className="lede">
            Manage explicit, auditable memories for personalization and future retrieval workflows.
          </p>
        </div>
        <div className="dashboard-actions">
          <button className="secondary-button" onClick={() => navigate('/dashboard')} type="button">
            Dashboard
          </button>
          <button className="secondary-button" onClick={handleLogout} type="button">
            Log out
          </button>
        </div>
      </header>

      <form className="memory-filters" onSubmit={handleSearch}>
        <label>
          Search
          <input
            name="search"
            onChange={(event) => setSearchTerm(event.target.value)}
            placeholder="Keyword, source, or category"
            type="search"
            value={searchTerm}
          />
        </label>

        <label>
          Type
          <select
            name="memoryType"
            onChange={(event) => setTypeFilter(event.target.value as MemoryType | '')}
            value={typeFilter}
          >
            <option value="">All types</option>
            {memoryTypes.map((type) => (
              <option key={type.value} value={type.value}>
                {type.label}
              </option>
            ))}
          </select>
        </label>

        <label>
          Category
          <input
            list="memory-categories"
            name="category"
            onChange={(event) => setCategoryFilter(event.target.value)}
            placeholder="Any category"
            type="text"
            value={categoryFilter}
          />
          <datalist id="memory-categories">
            {categories.map((category) => (
              <option key={category} value={category} />
            ))}
          </datalist>
        </label>

        <label className="checkbox-label">
          <input
            checked={includeExpired}
            onChange={(event) => setIncludeExpired(event.target.checked)}
            type="checkbox"
          />
          Include expired
        </label>

        <button disabled={isLoadingMemories} type="submit">
          {isLoadingMemories ? 'Searching...' : 'Search memories'}
        </button>
      </form>

      {error ? <p className="form-error">{error}</p> : null}

      <div className="memory-layout">
        <section className="memory-panel" aria-label="Memory list">
          <div className="panel-heading">
            <h2>Stored memories</h2>
            <span>{memories.length} shown</span>
          </div>

          {memories.length === 0 ? (
            <p className="empty-state">No memories match the current filters.</p>
          ) : (
            <div className="memory-list">
              {memories.map((memory) => (
                <button
                  className={`memory-row ${selectedMemory?.id === memory.id ? 'is-selected' : ''}`}
                  key={memory.id}
                  onClick={() => void handleSelectMemory(memory.id)}
                  type="button"
                >
                  <span className="memory-row-meta">
                    <strong>{formatMemoryType(memory.memory_type)}</strong>
                    <span>{memory.category}</span>
                  </span>
                  <span>{memory.content}</span>
                  <span className="memory-score">Score {memory.memory_score.toFixed(2)}</span>
                </button>
              ))}
            </div>
          )}
        </section>

        <section className="memory-panel" aria-label="Memory details">
          <div className="panel-heading">
            <h2>Details</h2>
            {selectedMemory ? <span>{formatMemoryType(selectedMemory.memory_type)}</span> : null}
          </div>

          {selectedMemory ? (
            <div className="memory-detail">
              <p>{selectedMemory.content}</p>
              <dl className="memory-metrics">
                <div>
                  <dt>Category</dt>
                  <dd>{selectedMemory.category}</dd>
                </div>
                <div>
                  <dt>Importance</dt>
                  <dd>{selectedMemory.importance_score.toFixed(2)}</dd>
                </div>
                <div>
                  <dt>Reinforcement</dt>
                  <dd>{selectedMemory.reinforcement_count}</dd>
                </div>
                <div>
                  <dt>Last accessed</dt>
                  <dd>{formatDate(selectedMemory.last_accessed_at)}</dd>
                </div>
                <div>
                  <dt>Expires</dt>
                  <dd>{formatDate(selectedMemory.expires_at)}</dd>
                </div>
                <div>
                  <dt>Source</dt>
                  <dd>{selectedMemory.source}</dd>
                </div>
              </dl>
              <div className="dashboard-actions">
                <button onClick={() => handleEdit(selectedMemory)} type="button">
                  Edit
                </button>
                <button
                  className="secondary-button"
                  onClick={() => void handleReinforce(selectedMemory.id)}
                  type="button"
                >
                  Reinforce
                </button>
                <button
                  className="danger-button"
                  onClick={() => void handleDelete(selectedMemory.id)}
                  type="button"
                >
                  Delete
                </button>
              </div>
            </div>
          ) : (
            <p className="empty-state">Select a memory to inspect its lifecycle details.</p>
          )}
        </section>
      </div>

      <section className="memory-panel" aria-labelledby="memory-form-title">
        <div className="panel-heading">
          <h2 id="memory-form-title">{editingId ? 'Edit memory' : 'Create memory'}</h2>
          {editingId ? (
            <button
              className="text-button"
              onClick={() => {
                setEditingId(null);
                setFormState(emptyForm);
              }}
              type="button"
            >
              Cancel edit
            </button>
          ) : null}
        </div>

        <form className="memory-form" onSubmit={handleSubmit}>
          <label>
            Type
            <select
              name="formMemoryType"
              onChange={(event) =>
                setFormState((current) => ({
                  ...current,
                  memory_type: event.target.value as MemoryType,
                }))
              }
              value={formState.memory_type}
            >
              {memoryTypes.map((type) => (
                <option key={type.value} value={type.value}>
                  {type.label}
                </option>
              ))}
            </select>
          </label>

          <label>
            Category
            <input
              maxLength={120}
              name="formCategory"
              onChange={(event) =>
                setFormState((current) => ({ ...current, category: event.target.value }))
              }
              required
              type="text"
              value={formState.category}
            />
          </label>

          <label>
            Source
            <input
              maxLength={120}
              name="formSource"
              onChange={(event) =>
                setFormState((current) => ({ ...current, source: event.target.value }))
              }
              required
              type="text"
              value={formState.source}
            />
          </label>

          <label>
            Importance
            <input
              max="1"
              min="0"
              name="formImportance"
              onChange={(event) =>
                setFormState((current) => ({
                  ...current,
                  importance_score: event.target.value,
                }))
              }
              required
              step="0.05"
              type="number"
              value={formState.importance_score}
            />
          </label>

          <label>
            Expiration
            <input
              name="formExpiration"
              onChange={(event) =>
                setFormState((current) => ({ ...current, expires_at: event.target.value }))
              }
              type="datetime-local"
              value={formState.expires_at}
            />
          </label>

          <label className="memory-content-field">
            Content
            <textarea
              maxLength={20000}
              name="formContent"
              onChange={(event) =>
                setFormState((current) => ({ ...current, content: event.target.value }))
              }
              required
              rows={5}
              value={formState.content}
            />
          </label>

          {formError ? <p className="form-error">{formError}</p> : null}

          <button disabled={isSaving} type="submit">
            {isSaving ? 'Saving...' : editingId ? 'Save changes' : 'Create memory'}
          </button>
        </form>
      </section>
    </section>
  );
}

function formatMemoryType(memoryType: MemoryType): string {
  return memoryTypes.find((type) => type.value === memoryType)?.label ?? memoryType;
}

function formatDate(value: string | null): string {
  if (!value) {
    return 'None';
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

function toDatetimeLocal(value: string): string {
  const date = new Date(value);
  const offsetDate = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return offsetDate.toISOString().slice(0, 16);
}
