# KnowTwin API — Dockerfile (forked from EcoDB api/Dockerfile, P1.1).
# Build context is the REPO ROOT (docker-compose `context: .`), so modules are
# copied as api/<module>.py. Explicit COPY list (invariant: a new module MUST be
# added here or the container won't have it).

FROM python:3.12-slim

# El repo apt.debian.org rechaza HTTP plano (Fastly 451) — pasar a HTTPS antes
# de cualquier apt-get update. python:3.12-slim YA trae ca-certificates.
RUN sed -i 's|http://deb\.debian\.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends curl ffmpeg gosu \
    && rm -rf /var/lib/apt/lists/*

# No correr como root. Crear usuario apiuser UID 1000.
RUN groupadd --system --gid 1000 apiuser \
    && useradd --system --uid 1000 --gid 1000 --no-create-home --shell /usr/sbin/nologin apiuser

WORKDIR /app

# HF cache para GLiNER/reranker. apiuser no tiene home (--no-create-home).
ENV HF_HOME=/app/.cache/huggingface
RUN mkdir -p /app/.cache/huggingface /app/media && chown -R apiuser:apiuser /app/.cache /app/media

# Layer separado para deps — cache friendly: requirements.txt cambia menos que el codigo.
COPY --chown=apiuser:apiuser api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-cache reranker model (GAMR — search.py) BEFORE copying app modules, so code
# edits don't invalidate this layer (one-time ~90MB fetch, cached thereafter).
# Revision must match RERANKER_REVISION at runtime (same SHA = same HF cache key).
RUN python -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2', revision='c5ee24cb16019beea0893ab7796b1df96625c6b8')" \
    && chown -R apiuser:apiuser /app/.cache

# Copia explicita de modulos del API (strip-list de EcoDB metacognition NO incluido:
# clusters/briefing/foresights/cases/skills/cells + migrate_3_0c + migrations omitidos).
COPY --chown=apiuser:apiuser \
    api/admin.py api/agents.py api/auth.py api/background.py api/bootstrap_first_apikey.py \
    api/cell_configs.py api/cell_templates.py api/cell_worker.py api/chunker.py api/claims.py \
    api/classifier.py api/coverage.py api/curator.py api/curator_post.py \
    api/crypto.py api/db.py api/deletion.py api/disputes.py api/documents.py api/dossier.py api/embeddings_client.py api/entity_normalization.py \
    api/events.py api/gliner_service.py api/graph.py api/interview_style.py api/interviewer.py api/interviews.py api/llm_provider.py api/main.py \
    api/memories.py api/onboarding.py api/org_settings.py api/pagination.py api/parsers.py \
    api/permissions.py api/projects.py api/providers.py api/rate_limit.py api/reranker.py \
    api/scoring.py api/search.py api/settings.py api/shared_models.py api/stats.py api/teams.py \
    api/telemetry.py api/telemetry_api.py api/twin.py api/users.py api/verifier.py api/worker.py api/workspaces.py \
    ./

COPY --chown=apiuser:apiuser api/tests/ ./tests/

COPY --chown=root:root api/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD curl --fail --silent http://localhost:8080/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--no-server-header"]
