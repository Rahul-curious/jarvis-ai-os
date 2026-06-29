import { FormEvent, useEffect, useState } from 'react';

import {
  ApiError,
  getCurrentUser,
  KnowledgeDocument,
  logout,
  uploadDocument,
  UserProfile,
} from '../api/client';
import { RoutePath } from '../state/router';

type UploadDocumentPageProps = {
  currentUser: UserProfile | null;
  navigate: (path: RoutePath) => void;
  onLogout: () => void;
  onUserLoaded: (user: UserProfile) => void;
};

export function UploadDocumentPage({
  currentUser,
  navigate,
  onLogout,
  onUserLoaded,
}: UploadDocumentPageProps) {
  const [isLoadingProfile, setIsLoadingProfile] = useState(currentUser === null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadedDocument, setUploadedDocument] = useState<KnowledgeDocument | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);

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

  async function handleLogout() {
    await logout();
    onLogout();
    navigate('/login');
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selectedFile === null) {
      setError('Choose a txt, md, or pdf file to upload.');
      return;
    }

    setError(null);
    setUploadedDocument(null);
    setIsUploading(true);

    try {
      const response = await uploadDocument(selectedFile);
      setUploadedDocument(response);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Unable to upload document');
    } finally {
      setIsUploading(false);
    }
  }

  if (isLoadingProfile) {
    return <p className="status-message">Loading upload access...</p>;
  }

  if (currentUser === null) {
    return null;
  }

  return (
    <section className="memory-dashboard" aria-labelledby="upload-title">
      <header className="memory-header">
        <div>
          <p className="eyebrow">Document Ingestion</p>
          <h1 id="upload-title">Upload knowledge</h1>
          <p className="lede">
            Add txt, markdown, or PDF files. JARVIS will parse, chunk, embed, and index them.
          </p>
        </div>
        <div className="dashboard-actions">
          <button className="secondary-button" onClick={() => navigate('/knowledge')} type="button">
            Knowledge base
          </button>
          <button className="secondary-button" onClick={handleLogout} type="button">
            Log out
          </button>
        </div>
      </header>

      <section className="memory-panel">
        <form className="upload-form" onSubmit={handleSubmit}>
          <label>
            Document
            <input
              accept=".txt,.md,.markdown,.pdf,text/plain,text/markdown,application/pdf"
              onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
              required
              type="file"
            />
          </label>
          <button disabled={isUploading} type="submit">
            {isUploading ? 'Indexing...' : 'Upload and index'}
          </button>
        </form>

        {error ? <p className="form-error">{error}</p> : null}

        {uploadedDocument ? (
          <article className="rag-answer">
            <h2>{uploadedDocument.filename}</h2>
            <p>
              Indexed {uploadedDocument.chunk_count} chunks into{' '}
              <code>{uploadedDocument.vector_collection}</code> using{' '}
              <code>{uploadedDocument.embedding_model}</code>.
            </p>
            <button onClick={() => navigate('/knowledge')} type="button">
              View knowledge base
            </button>
          </article>
        ) : null}
      </section>
    </section>
  );
}
