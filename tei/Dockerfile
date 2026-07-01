# EcoDB embeddings — Dockerfile (Tarea 1.8 plan maestro v3 §7)
# PyTorch + CUDA + bitsandbytes INT8 para Jina v4 multimodal.

FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

# El repo apt.debian.org rechaza HTTP plano (Fastly 451). Forzar HTTPS antes de
# cualquier apt-get update. La imagen base ya trae ca-certificates.
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i 's|http://deb\.debian\.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Usuario no-root para runtime. PyTorch cuda runtime base trae /opt/conda
# instalado como root, pero ejecutar como apiuser tras pip install.
RUN groupadd --system --gid 1000 apiuser \
    && useradd --system --uid 1000 --gid 1000 --no-create-home --shell /usr/sbin/nologin apiuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# El modelo se monta como volume desde host (~/.cache/huggingface) o se descarga
# al primer arranque del container. NO se incluye en la imagen para mantener
# el tamaño manejable (sin modelo: ~3 GB; con modelo Jina v4: ~10 GB).

COPY --chown=apiuser:apiuser server.py .

# El cache de HuggingFace requiere acceso de escritura. apiuser necesita poder
# leer/escribir en /home/apiuser/.cache o donde TRANSFORMERS_CACHE apunte.
# Por simplicidad usamos /tmp con permisos abiertos en runtime, o el volumen
# montado. En docker-compose se montará el volumen.
ENV HF_HOME=/cache/huggingface \
    TRANSFORMERS_CACHE=/cache/huggingface \
    HF_HUB_DISABLE_TELEMETRY=1 \
    TORCH_HOME=/cache/torch

RUN mkdir -p /cache/huggingface /cache/torch && chown -R apiuser:apiuser /cache

USER apiuser

EXPOSE 8090

HEALTHCHECK --interval=15s --timeout=10s --start-period=180s --retries=10 \
    CMD curl --fail --silent http://localhost:8090/health || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8090", "--no-server-header"]
