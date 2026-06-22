# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Documentación fuente de verdad

`AGENTS.md` es el documento principal: contexto, reglas de arquitectura vigentes, modelos Ollama, datos sensibles y cierre de sesión. Léelo antes de trabajar. Otros: `PLANS.md` (roadmap), `HANDOFF.md` (última sesión), `MEMORIES.md` (aprendizajes), `PERFIL.md` (perfil candidato, en `.gitignore`, no regenerar sin confirmación), `src/db/schema.sql` (schema). Docs temáticas en `docs/`.

## Comandos

```bash
ruff check src/ && ruff format src/         # lint + formato (antes de terminar)
pytest tests/ -q                            # tests (0 regresiones antes de cerrar)
pytest tests/unit/test_evaluate.py::test_x -q   # un solo test

python -m src.pipeline.run                  # pipeline completo
python -m src.pipeline.run --skip-fetch     # solo evaluar pendientes
python -m src.pipeline.run --dry-run        # sin Telegram
python -m src.dashboard.server              # dashboard http://localhost:8080
python -m src.telegram.bot                  # bot feedback (long polling)
```

Setup: `pip install -e .` (paquete instalado) + `requirements*.txt`. Ejecutar siempre como módulo (`python -m ...`), nunca por ruta. Requiere Ollama local con `gemma4:e4b` y `qwen2.5:7b`.

## Arquitectura

Pipeline lineal sobre SQLite, orquestado por `src/pipeline/run.py`. Cada etapa es un módulo independiente que lee y escribe en la DB:

```
fetch → role_classifier → fetch_company → evaluate → send
scraper  gemma4 clasifica  qwen2.5 enriquece  score 0-100  Telegram
```

- **`src/db/`** — `sqlite3` raw, sin ORM. `schema.sql` única fuente del schema; conexiones con `contextlib.closing(get_connection())`.
- **`src/utils/`** — código compartido; no reimplementar helpers fuera de aquí (`candidate_profile.py`, `constants.py`, `ollama_client.py`).
- **`src/dashboard/`** — Flask SPA + REST que lanza/detiene el pipeline como subproceso con mutex sobre `search_runs.status`.

### Gotchas que rompen cosas

- **`match_score` es INTEGER 0–100 en DB** (`final_score` 0–1 × 100). La conversión vive solo en `evaluate.py::_build_evaluation_params()`; no añadas otras.
- **Imports**: es un paquete instalado (`pip install -e .`); usa imports del paquete. La regla del proyecto prohíbe `sys.path.insert`, pero quedan 3 usos heredados (`db/migrate.py`, `onboarding/keyword_generator.py`, `pipeline/feedback_processor.py`) — deuda conocida, no añadir más. Config sensible solo en `.env`.
- **`personal_concerns`**: no loguear/imprimir/incluir en errores; pasar íntegro a gemma4.
- Tests: fixtures de respuestas Ollama (JSON) en `tests/fixtures/ollama/`; nunca llamadas reales a Ollama ni requests HTTP en tests.
