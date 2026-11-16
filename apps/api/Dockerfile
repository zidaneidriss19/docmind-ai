FROM python:3.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY apps/api/requirements.txt apps/api/requirements-ingestion.txt apps/api/requirements-worker.txt ./
RUN pip install --disable-pip-version-check -r requirements-worker.txt

RUN groupadd --gid 10001 docmind \
    && useradd --uid 10001 --gid docmind --create-home docmind \
    && install -d -o docmind -g docmind /var/lib/docmind/documents /var/lib/docmind/models

COPY apps/api/alembic.ini ./
COPY apps/api/app ./app
COPY apps/api/migrations ./migrations

USER docmind
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
