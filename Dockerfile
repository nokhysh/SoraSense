FROM python:3.12.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN addgroup --system sorasense \
    && adduser --system --ingroup sorasense sorasense

COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic

ARG PROJECT_INSTALL=.
RUN pip install --no-cache-dir "${PROJECT_INSTALL}"

USER sorasense

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
