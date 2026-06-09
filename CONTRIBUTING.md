# Contributing to SKV Network

## Quick Start
1. Fork the repository
2. Clone your fork
3. Run `docker-compose up`
4. Open https://skv.network

## Architecture
- **Backend:** FastAPI + PostgreSQL + Qdrant
- **AI:** TensorCube Neural Graph with Hebbian/STDP
- **Infrastructure:** Docker, Nginx

## Key Files
- `src/app/routers/` — API endpoints
- `src/app/tensor_cube.py` — Neural graph logic
- `src/app/v4_graph.py` — Graph storage
- `src/app/config.py` — Configuration (Pydantic Settings)

## Development Flow
1. Create a branch: `feature/your-feature`
2. Make changes
3. Run tests: `python -m pytest tests/`
4. Submit PR to `main`

## Code Style
- Python 3.11+
- Type hints where possible
- Docstrings for public functions
- Security: NEVER commit API keys or passwords

## Questions
Open an issue or contact denizchavdarov@icloud.com
