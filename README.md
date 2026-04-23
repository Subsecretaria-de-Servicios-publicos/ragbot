# 🤖 RAGBot System — Guía Completa de Implementación

## Arquitectura General

```
ragbot-system/
├── backend/                   # FastAPI + Python
│   ├── app/
│   │   ├── api/               # Endpoints REST
│   │   ├── core/              # Config, seguridad, JWT
│   │   ├── db/                # Sesión y base de datos
│   │   ├── models/            # Modelos SQLAlchemy
│   │   ├── schemas/           # Pydantic schemas
│   │   ├── services/          # Lógica RAG, embeddings, chat
│   │   └── utils/             # Helpers
│   ├── alembic/               # Migraciones DB
│   └── main.py
├── frontend/
│   ├── dashboard/             # Panel de administración (HTML/JS)
│   └── widget/                # Widget embebible
└── docs/
```

---

## PASO A PASO — IMPLEMENTACIÓN COMPLETA

### PASO 1: Requisitos del Sistema

```bash
# Sistema operativo: Ubuntu 22.04+ / macOS / Windows (WSL2)
# Python 3.11+
# PostgreSQL 15+ con extensión pgvector
# Node.js 18+ (para el dashboard si se usa bundler)
```

### PASO 2: Instalar PostgreSQL + pgvector

```bash
# Ubuntu
sudo apt update
sudo apt install postgresql postgresql-contrib

# Instalar pgvector
sudo apt install postgresql-server-dev-15
git clone https://github.com/pgvector/pgvector.git
cd pgvector && make && sudo make install

# Crear base de datos
sudo -u postgres psql
CREATE DATABASE ragbot_db;
CREATE USER ragbot_user WITH ENCRYPTED PASSWORD 'tu_password_seguro';
GRANT ALL PRIVILEGES ON DATABASE ragbot_db TO ragbot_user;
\c ragbot_db
CREATE EXTENSION vector;
\q
```

### PASO 3: Configurar Entorno Python

```bash
cd ragbot-system/backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

### PASO 4: Variables de Entorno

```bash
cp .env.example .env
# Editar .env con tus credenciales
```

### PASO 5: Ejecutar Migraciones con Alembic

```bash
cd backend
alembic upgrade head
```

### PASO 6: Crear Superusuario

```bash
python scripts/create_superuser.py
```

### PASO 7: Iniciar el Backend

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### PASO 8: Servir el Dashboard

```bash
# Opción simple: servidor estático
cd frontend/dashboard
python -m http.server 3000

# O con Nginx (producción)
# Ver nginx.conf en docs/
```

### PASO 9: Producción con Docker

```bash
docker-compose up -d
```

---

## Flujo RAG

```
PDF Upload → Text Extraction → Chunking → Embedding → pgvector Store
                                                              ↓
User Question → Embed Query → Vector Search → Context + Question → LLM → Response
```

## Modelos de IA Soportados

| Proveedor   | Modelos                          | Variable ENV         |
|-------------|----------------------------------|----------------------|
| OpenAI      | gpt-4o, gpt-4-turbo, gpt-3.5    | OPENAI_API_KEY       |
| Anthropic   | claude-3-5-sonnet, claude-3-haiku| ANTHROPIC_API_KEY    |
| Google      | gemini-1.5-pro, gemini-1.5-flash | GOOGLE_API_KEY       |
| Ollama      | llama3, mistral (local)          | OLLAMA_BASE_URL      |

## Niveles de Usuario

| Rol          | Permisos                                              |
|--------------|-------------------------------------------------------|
| superadmin   | Todo: usuarios, bots, docs, configuración             |
| admin        | Gestionar bots propios, documentos, ver conversaciones|
| operator     | Subir documentos, ver métricas                        |
| viewer       | Solo ver conversaciones y estadísticas                |
