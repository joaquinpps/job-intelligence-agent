"""
Extrae datos estructurados del CV.
Incluye skills con nivel y employment_gap_years.
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from src.utils.ollama_client import MODEL_HR, ollama_call

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def extract_text_from_pdf(pdf_path: str | Path) -> str:
    """Extrae todo el texto de un archivo PDF."""
    reader = PdfReader(str(pdf_path))
    parts: list[str] = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            parts.append(text)
    return "\n".join(parts)


def build_extraction_prompt(cv_text: str) -> str:
    """Construye el prompt para extraer datos completos del CV."""
    return f"""Eres un extractor de datos estructurados de CVs. Analiza el texto y responde UNICAMENTE con JSON válido.

CAMPOS A EXTRAER:
1. full_name: string (nombre completo)
2. location_current: string (ciudad/provincia actual)
3. skills_technical: lista de objetos {{"name": "skill", "level": "basico|intermedio|avanzado", "evidence": "frase justificativa"}}
   REGLAS DE NIVEL (MUY IMPORTANTE - seguir estrictamente):
   - **básico**: La skill viene de BOOTCAMP, CURSOS, PROYECTOS ACADÉMICOS, PROYECTOS DE APRENDIZAJE
     Si la evidencia menciona "Bootcamp", "proyecto", "Capstone", "curso", "formación" → básico
   - **intermedio**: La skill se usó en PROYECTOS REALES PARA CLIENTES PAGADOS (freelance, consultoría)
     Si la evidencia menciona "cliente", "freelance", "consultoría pagada" → intermedio
   - **avanzado**: La skill se usó en TRABAJO LABORAL FORMAL (contrato, payroll, empresa)
     Si la evidencia menciona "empresa", "trabajo", "contrato", "empleo" → avanzado
   - Si tienes dudas entre básico e intermedio → PON básico
   - Si tienes dudas entre intermedio y avanzado → PON intermedio

4. employment_gap_years: null (NO calcular, déjalo vacío)

5. education: lista de objetos {{"degree": string, "institution": string, "year": int|null}}
6. experience: lista de objetos {{"role": string, "company": string, "duration": string, "description": string}}
   IMPORTANTE: Solo incluir EXPERIENCIA LABORAL REAL (no proyectos académicos, bootcamps, prácticas no remuneradas)
7. languages: lista de strings
8. projects: lista de objetos {{"name": string, "description": string}}

Si falta un campo usa null o []. No incluyas texto adicional.

TEXTO DEL CV:
{cv_text[:12000]}"""


def is_academic_or_training(role: str) -> bool:
    """Detecta si un rol es académico/formación (no laboral real)."""
    if not role:
        return False
    role_lower = role.lower()
    academic_keywords = [
        "project",
        "capstone",
        "bootcamp",
        "thesis",
        "tfg",
        "tfm",
        "internship",
        "intern",
        "practica",
        "prácticas",
        "course",
        "training",
        "volunteer",
        "voluntario",
        "student",
        "estudiante",
    ]
    return any(kw in role_lower for kw in academic_keywords)


def parse_experience_dates(
    experience: list[dict],
) -> tuple[str | None, float | None, str | None]:
    """
    Infiere el gap de empleo desde las experiencias laborales reales.
    Excluye proyectos académicos, bootcamps, prácticas, etc.
    Returns: (ultimo_trabajo_fecha, gap_years, ultimo_trabajo_rol)
    """
    import re

    now = datetime.now()
    last_job_year = None
    last_job_month = None
    last_job_role = None

    # Mapeo de meses en inglés a número
    month_map = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
        "ene": 1,
        "abr": 4,
        "ago": 8,
        "dic": 12,
    }

    for exp in experience:
        role = exp.get("role", "")
        duration = exp.get("duration", "")

        # Skip academic/training experiences
        if is_academic_or_training(role):
            continue

        if not duration:
            continue

        # Buscar fecha fin (año y mes) en el duration string
        # Patrones: "Dec 2021 - Sep 2022", "2021 - 2022", "Nov 2019 - Apr 2021"

        # Buscar año (el último)
        years = re.findall(r"\b(20\d{2})\b", duration)
        if not years:
            continue

        year = int(years[-1])  # Tomar el último año (fecha fin)

        # Buscar mes (cerca del último año)
        month_match = re.search(r"(\w{3})\s+" + str(year) + r"$", duration, re.IGNORECASE)
        month = 9  # default: si no se parsea, asumir septiembre
        if month_match:
            month_str = month_match.group(1).lower()[:3]
            month = month_map.get(month_str, 9)

        # Tomar el trabajo más reciente (fecha fin más reciente)
        if (
            last_job_year is None
            or year > last_job_year
            or (year == last_job_year and month > last_job_month)
        ):
            last_job_year = year
            last_job_month = month
            last_job_role = role

    if last_job_year:
        # Calcular gap exacto: desde fecha fin hasta ahora
        # Mes actual - mes fin del trabajo
        months_gap = (now.year - last_job_year) * 12 + (now.month - last_job_month)
        gap_years = round(months_gap / 12, 1)
        return f"{last_job_year}", gap_years, last_job_role

    return None, None, None


def extract_cv_data(cv_path: str | Path) -> dict[str, Any]:
    """
    Extrae datos estructurados del CV.

    Returns:
        Diccionario con full_name, location_current, skills_technical,
        education, experience, languages, projects, employment_gap_years.
    """
    log.info("Extrayendo texto de %s", cv_path)
    cv_text = extract_text_from_pdf(cv_path)
    if not cv_text.strip():
        raise ValueError("No se pudo extraer texto del PDF")

    log.info("Extrayendo datos del perfil...")
    prompt = build_extraction_prompt(cv_text)
    result = ollama_call(
        model=MODEL_HR,
        prompt=prompt,
        expect_json=True,
        num_ctx=8192,  # el CV completo (~3k tokens) + respuesta JSON no cabe en el default 4096
    )

    if not isinstance(result, dict):
        log.warning("gemma4 no devolvió dict, creando estructura vacía")
        result = {}

    # Calcular employment_gap_years matemáticamente (excluyendo proyectos académicos)
    experience = result.get("experience", [])
    if experience:
        last_date, gap, last_role = parse_experience_dates(experience)
        if gap:
            result["employment_gap_years"] = gap
            result["_last_job_year"] = last_date
            result["_last_job_role"] = last_role

    return result


def main() -> None:
    """Prueba manual del extractor."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cv_path = Path("assets/cv.pdf")
    if not cv_path.exists():
        log.error("No se encontro %s", cv_path)
        sys.exit(1)
    try:
        data = extract_cv_data(cv_path)
        print(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception:
        log.exception("Error extrayendo CV")
        sys.exit(1)


if __name__ == "__main__":
    main()
