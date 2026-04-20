FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY scanner ./scanner
COPY alembic.ini ./
COPY alembic ./alembic

RUN python -m pip install --upgrade pip && python -m pip install .

CMD ["uvicorn", "scanner.apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

