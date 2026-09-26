# syntax=docker/dockerfile:1

FROM python:3.12-slim

# Impede geração de .pyc e força logs sem buffer
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /api

# Argumento de build para o SDK do provedor LLM (default: google-genai)
ARG LLM_SDK=google-genai

# Instala dependências primeiro (aproveita cache do Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ -n "$LLM_SDK" ]; then pip install --no-cache-dir "$LLM_SDK"; fi

# Copia o código-fonte
COPY src/ ./src/

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "src"]
