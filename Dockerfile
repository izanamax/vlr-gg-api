FROM python:3.13-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 VLRGG_PAGE_STORE=/app/data/pages.sqlite3

COPY pyproject.toml README.md LICENSE ./
COPY vlrgg ./vlrgg
RUN pip install --no-cache-dir . && useradd --create-home api && mkdir -p /app/data && chown api /app/data
USER api

EXPOSE 3001
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3001/v1/health')"
CMD ["python", "-m", "vlrgg"]
