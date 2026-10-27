FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SA_DB_PATH=/app/data/support.db
WORKDIR /app

COPY pyproject.toml README.md ./
COPY support_analytics ./support_analytics
COPY web ./web
RUN pip install --no-cache-dir -e . && mkdir -p data && python -m support_analytics sync \
    && useradd --create-home app && chown -R app /app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "support_analytics.api:app", "--host", "0.0.0.0", "--port", "8000"]
