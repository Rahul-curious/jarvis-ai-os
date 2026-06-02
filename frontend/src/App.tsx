const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

const foundations = [
  'FastAPI control plane',
  'React + Vite TypeScript client',
  'PostgreSQL relational store',
  'ChromaDB vector store',
  'LangGraph agent scaffolding',
  'Docker Compose local stack',
];

export default function App() {
  return (
    <main className="app-shell">
      <section className="hero">
        <p className="eyebrow">Phase 1 Foundation</p>
        <h1>JARVIS AI OS</h1>
        <p className="lede">
          Enterprise-grade scaffolding for the hybrid assistant, memory, knowledge, and
          orchestration platform.
        </p>
      </section>

      <section className="foundation-panel" aria-label="Configured foundation">
        <h2>Configured Foundation</h2>
        <ul>
          {foundations.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </section>

      <footer>
        <span>Backend API</span>
        <code>{apiBaseUrl}</code>
      </footer>
    </main>
  );
}
