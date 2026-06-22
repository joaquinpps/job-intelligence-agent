# AGENTS.md — Job Intelligence Agent

> Proyecto: job-intelligence-agent
> Candidato: Miguel Bohórquez Granados
> Stack: Python 3.14+, SQLite, Ollama, Telegram, cron

---

## CONTEXTO DEL PROYECTO

Sistema de inteligencia de carrera que extrae ofertas de trabajo de InfoJobs,
las evalúa contra el perfil del candidato usando un modelo local de Ollama,
enriquece empresas con otro modelo, y envía un resumen diario por Telegram.

**Fuente única de verdad del candidato:** `PERFIL.md` en la raíz.
**Leer SIEMPRE** antes de cualquier tarea de evaluación o análisis.

---

## ARQUITECTURA VIGENTE

> Estado post-auditoría 2026-06-15. Estas decisiones están en vigor — no cambiarlas sin ADR.

### Acceso a base de datos
- **`sqlite3` raw en todo el proyecto.** Sin ORM. Sin SQLAlchemy.
- `src/db/schema.sql` es la **única fuente de verdad del schema**. Nunca duplicar columnas en otros archivos.
- Conexiones siempre con `contextlib.closing(get_connection())` — nunca `conn.close()` manual.
- `src/db/migrate.py` parsea `schema.sql` directamente para detectar columnas faltantes.

### Imports y packaging
- **`pyproject.toml` + `pip install -e .`** — el proyecto es un paquete instalado.
- **Regla: sin `sys.path.insert` en módulos nuevos.** Quedan 3 usos heredados (`src/db/migrate.py`, `src/onboarding/keyword_generator.py`, `src/pipeline/feedback_processor.py`) — deuda conocida pendiente de eliminar; no añadir más.
- Dependencias de runtime: `requirements.txt`. Herramientas de desarrollo: `requirements-dev.txt`.

### Configuración
- **Todas las variables sensibles en `.env`.** Ningún valor hardcodeado en código.
- Variables obligatorias: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DB_PATH` (opcional, default `data/jobs.db`), `OLLAMA_BASE_URL` (opcional, default `http://localhost:11434`).
- `send.py` valida tokens al inicio — fallo rápido y explícito.

### Perfil del candidato
- `src/utils/candidate_profile.py` → `CandidateProfile` es la **única fuente de verdad del perfil**.
- `CandidateProfile.from_perfil(text)` / `from_perfil_path(path)` para construir desde `PERFIL.md`.
- Nunca reimplementar `load_skills_from_perfil()` u otros helpers en otros módulos.

### Constantes compartidas
- `src/utils/constants.py` — `MONTH_NAMES`, `month_from_name()`. Importar desde aquí, nunca redefinir.

### match_score
- Se almacena como `INTEGER 0–100` en DB (`final_score * 100`, redondeado).
- `evaluate.py` convierte float 0–1 → integer en `_build_evaluation_params()`.
- `send.py` compara contra umbral en escala 0–100 (ej. `>= 35`).
- El dashboard muestra el valor directamente como porcentaje. No hay conversión adicional.

### Tests
- 223 tests passing. Estructura: `tests/unit/`, `tests/integration/`, `tests/manual/`.
- Fixtures de respuestas Ollama (JSON) en `tests/fixtures/ollama/`. No hacer llamadas reales a Ollama ni requests HTTP en tests.
- Antes de cerrar sesión: `pytest tests/ -q` debe pasar con 0 regresiones.

### Deuda pendiente (no urgente)
- `uv lock` o `pip-compile --generate-hashes` para reproducibilidad con hashes.
- Si el proyecto crece a múltiples entornos: Alembic para migraciones versionadas.

---

## ÍNDICE DE DOCUMENTACIÓN

| Archivo | Descripción |
|---------|-------------|
| `HANDOFF.md` | Estado de sesión — LEER PRIMERO |
| `docs/SETUP.md` | Instalación, comandos, cron |
| `docs/PIPELINE.md` | Flujo completo fetch→classify→enrich→evaluate→send |
| `docs/DATABASE.md` | Tablas, reglas, schema SQL |
| `docs/RATING.md` | Sistema de puntuación técnico + HR |
| `docs/CONVENTIONS.md` | Estilo de código, fases de implementación |
| `docs/adr/` | Decisiones técnicas y de arquitectura (ADR clásico) — ver README interno |

---

## COMANDOS PRINCIPALES

```bash
# Pipeline completo
python src/pipeline/run.py

# Pipeline individual
python src/pipeline/fetch.py                  # Fetch ofertas
python src/pipeline/evaluate.py               # Evaluar ofertas (default 10)
python src/pipeline/evaluate.py --limit 0     # Evaluar todas las pendientes
python src/telegram/send.py --mode daily      # (Opcional, run.py ya ejecuta send automáticamente)

# Dashboard web (FLASK) — nueva interfaz principal
python src/dashboard/server.py                # Servir http://localhost:8080
python src/dashboard/server.py --port 9090    # Puerto personalizado

# Dashboard legacy (obsoleto, usar Flask)
python src/pipeline/generate_dashboard.py     # Generar reports/evaluations-v2.html

# Linter (siempre antes de terminar tarea)
ruff check src/ && ruff format src/
```

---

## MODELOS OLLAMA

| Modelo | Rol | Temperatura | Notas |
|--------|-----|-------------|-------|
| `gemma4:e4b` | Técnico (bloque A, 60pts) | 0.1 | Scores deterministas, JSON estructurado |
| `gemma4:e4b` | HR (bloque B, 40pts) | 0.0 | Veredicto + apply_signal deben ser consistentes |
| `qwen2.5:7b` | Enriquecimiento empresas | 0.0 | Solo usado por fetch_company.py, no por evaluate.py |

**Regla:** gemma4 nunca scores numéricos sin razonamiento.

**Temperatura HR = 0.0:** El veredicto y apply_signal (yes/no/maybe) son decisiones críticas
que deben ser deterministas. Mismo perfil + misma oferta = mismo veredicto.

Ver `docs/CONVENTIONS.md` para detalles de uso.

---

## PERFIL.md — REGLAS CRÍTICAS

- **Nunca regenerar** `PERFIL.md` automáticamente sin confirmación explícita
- **Leer siempre** al inicio de cada sesión que implique evaluación/búsqueda
- `personal_concerns`: texto libre, no estructurar, pasar íntegro a gemma4
- `Entorno preferido / a evitar`: contexto de priorización, no filtro de descarte

---

## DATOS SENSIBLES

- `personal_concerns`: no loguear, no imprimir, no incluir en errores
- Credenciales: siempre en variables de entorno, nunca en código
- `PERFIL.md` y `data/jobs.db`: añadir a .gitignore (ya hecho)

---

## ARCHIVOS DE LECTURA OBLIGATORIA

Al inicio de cada sesión, leer en orden:

1. `AGENTS.md` — contexto técnico y reglas
2. `PLANS.md` — estado actual del proyecto
3. `HANDOFF.md` — estado de sesión y próximo paso
4. `MEMORIES.md` — aprendizajes acumulados
5. `PERFIL.md` — perfil del candidato
6. `src/db/schema.sql` — fuente de verdad de la DB

---

## CIERRE DE SESIÓN

Al finalizar cualquier sesión de trabajo:

1. Actualizar `HANDOFF.md` con el estado actual
2. Actualizar `PLANS.md` y `MEMORIES.md` si aplica
3. ```bash
   git add -A
   git commit -m "descripción breve"
   git push
   ```

**Obligatorio.** No terminar sesión sin pushear.

---

## SISTEMA DE FEEDBACK (Telegram)

| Comando | Descripción |
|---------|-------------|
| `/f1 [texto]` | Feedback sobre oferta 1 |
| `/f2 [texto]` | Feedback sobre oferta 2 |
| `/f3 [texto]` | Feedback sobre oferta 3 |
| `/dia [texto]` | Estado emocional del día |

El feedback NO filtra ofertas. Es contexto psicológico para gemma4.

---

## AGENTES ESPECIALIZADOS

Disponible: `@pipeline` — agente especializado en el pipeline de ofertas.
Usa `.opencode/agents/pipeline.md` para contexto adicional.
