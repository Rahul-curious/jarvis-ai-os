# JARVIS Backend

FastAPI foundation for the JARVIS cloud control plane.

Phase 1 responsibilities:

- Provide the API gateway shell for versioned platform APIs.
- Centralize application settings, logging, and service wiring.
- Prepare PostgreSQL and ChromaDB integration boundaries.
- Expose a health endpoint for Docker and deployment checks.

Business logic for assistant orchestration, memory, RAG, governance, and agents is intentionally deferred.
