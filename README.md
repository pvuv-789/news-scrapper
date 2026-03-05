# E-Paper News Aggregation & Visualization System

> Automated daily news scraping, NLP processing, and visualization platform — targeting **Daily Thanthi E-Paper**.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Presentation Layer   Vue 3 + Vite + TailwindCSS        │
├─────────────────────────────────────────────────────────┤
│  Controller Layer     FastAPI routes (Pydantic schemas) │
├─────────────────────────────────────────────────────────┤
│  Service Layer        Scraper · Summarizer · Dedup      │
├─────────────────────────────────────────────────────────┤
│  Data Access Layer    SQLAlchemy Repositories           │
├─────────────────────────────────────────────────────────┤
│  Database Layer       PostgreSQL + pg_trgm              │
└─────────────────────────────────────────────────────────┘
```

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Vue 3 · Vite · TailwindCSS · Pinia |
| Backend | Python 3.11 · FastAPI · SQLAlchemy (async) |
| Scraping | Playwright · BeautifulSoup4 |
| Task Queue | Celery + Redis |
| Database | PostgreSQL 16 |
| Package Mgr | `uv` (Python) · `npm` (Frontend) |

---

## 🚀 Quick Start

### Prerequisites
- [Docker Desktop](https://www.docker.com/products/docker-desktop)
- [uv](https://github.com/astral-sh/uv) — `pip install uv`
- Node.js 20+

### 1. Environment Setup

```bash
cp .env.example .env
# Edit .env with your values
```

### 2. Run with Docker Compose (Recommended)

```bash
docker-compose up --build
```

| Service | URL |
|---|---|
| Frontend | http://localhost:5173 |
| Backend API | http://localhost:8000 |
| API Docs (Swagger) | http://localhost:8000/docs |

### 3. Local Development (without Docker)

**Backend:**
```bash
cd backend
uv sync
uv run alembic upgrade head           # Run DB migrations
uv run uvicorn main:app --reload      # Start API server
uv run celery -A services.celery_app worker --loglevel=info  # Start worker
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

---

## 📁 Directory Structure

```
/
├── /docs               # BRD, Architecture, API specs
├── /tests
│   ├── /backend        # Pytest tests
│   └── /frontend       # Vue Test Utils
├── /frontend           # Vue 3 + Vite app
│   └── /src
│       ├── /components # ArticleCard, FilterBar, NavBar
│       ├── /views      # HomeView, EditionView
│       ├── /stores     # Pinia (articles, filters)
│       └── /services   # Axios API service
├── /backend            # FastAPI application
│   ├── /api            # Route controllers
│   ├── /core           # Config, DB, DI
│   ├── /models         # SQLAlchemy + Pydantic
│   ├── /repositories   # Data Access Layer
│   ├── /services       # Business logic
│   └── /scraper        # Playwright scrapers
├── pyproject.toml
├── docker-compose.yml
└── .env.example
```

---

## 🧪 Testing

```bash
# Backend
cd backend && uv run pytest ../tests/backend/ -v

# Frontend
cd frontend && npm run test
```

---

## 📜 License

MIT — Scraping of metadata and summaries only. All content ownership belongs to Daily Thanthi. Users are redirected to original source for full articles.
