FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py .
RUN groupadd --gid 1001 nergroup \
    && useradd --system --uid 1000 --gid 1001 --no-create-home --shell /usr/sbin/nologin neruser
RUN mkdir -p /app/.cache/huggingface && chown -R neruser:nergroup /app/.cache
USER neruser
EXPOSE 8091
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8091"]
