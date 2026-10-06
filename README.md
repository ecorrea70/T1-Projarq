# T1 - Projeto e Arquitetura de Software

## Executar

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
uvicorn app.main:app --reload
```

O healthcheck está disponível em `GET /health` e retorna `{"status":"ok"}`.

## Executar com Docker

```bash
docker compose up --build
```

A API ficará disponível em `http://localhost:8000`, com healthcheck em
`http://localhost:8000/health`.
