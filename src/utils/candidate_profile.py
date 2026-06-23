"""Perfil del candidato parseado desde PERFIL.md en un solo pass.

Uso:
    profile = CandidateProfile.from_perfil(perfil_text)
    # Acceder a campos parseados
    profile.skills_map        # {"python": "básico", ...}
    profile.employment_gap    # 3.7
    profile.experience_years  # 4.3
    profile.city              # "Jerez de la Frontera, Spain"
    # Acceder a secciones completas
    profile.excerpt(["Skills técnicas", "Personal concerns"])
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from src.utils.constants import month_from_name

log = logging.getLogger(__name__)


# Secciones de PERFIL.md y sus regex de extracción
# Ordenadas como aparecen en el documento
_SECTION_PATTERNS: list[tuple[str, str]] = [
    ("Skills técnicas", r"## Skills técnicas\s*\n(.*?)(?=\n## |\Z)"),
    ("Gap de empleo", r"## Gap de empleo\s*\n(.*?)(?=\n## |\Z)"),
    ("Educación", r"## Educación\s*\n(.*?)(?=\n## |\Z)"),
    ("Experiencia", r"## Experiencia\s*\n(.*?)(?=\n## |\Z)"),
    ("Idiomas", r"## Idiomas\s*\n(.*?)(?=\n## |\Z)"),
    ("Proyectos", r"## Proyectos\s*\n(.*?)(?=\n## |\Z)"),
    ("Preferencias laborales", r"## Preferencias laborales\s*\n(.*?)(?=\n## |\Z)"),
    ("Personal concerns", r"## Personal concerns\s*\n(.*?)(?=\n## |\Z)"),
    (
        "Entorno preferido / a evitar",
        r"## Entorno preferido / a evitar\s*\n(.*?)(?=\n## |\Z)",
    ),
]

# Patrón para extraer skills de una sección de skills técnicas
_SKILL_LINE_PATTERN = re.compile(r"- \*\*([^(]+)\((\w+)\)\*\*:?\s*(.+)?", re.IGNORECASE)

# Patrón para extraer gap
_GAP_PATTERN = re.compile(r"- \*\*Años:\*\*\s*([\d.]+)")

# Patrón para ubicación en ## Datos base
_LOCATION_PATTERN = re.compile(r"\*\*Ubicación actual:\*\*\s*(.+)", re.IGNORECASE)

# Patrón para fechas en sección Experiencia
_DURATION_PATTERN = re.compile(
    r"\*\*Duración:\*\*\s*(\w+)\s+(\d{4})\s*[–\-]\s*(\w+)\s+(\d{4})",
    re.IGNORECASE,
)


@dataclass
class CandidateProfile:
    skills_map: dict[str, str] = field(default_factory=dict)
    employment_gap: float | None = None
    experience_years: float = 0.0
    city: str = ""
    perfil_sections: dict[str, str] = field(default_factory=dict)
    raw_perfil: str = ""  # TODO: eliminar tras migrar todos los consumers

    @classmethod
    def from_perfil(cls, perfil: str) -> CandidateProfile:
        """Parse PERFIL.md en un solo pass."""
        sections = cls._parse_sections(perfil)
        skills = cls._parse_skills(sections)
        gap = cls._parse_gap(sections)
        city = cls._parse_location(perfil)
        exp_years = cls._parse_experience_years(sections, perfil)

        return cls(
            skills_map={s["name"]: s["level"] for s in skills},
            employment_gap=gap,
            experience_years=exp_years,
            city=city,
            perfil_sections=sections,
            raw_perfil=perfil,
        )

    @classmethod
    def from_perfil_path(cls, path: Path | str) -> CandidateProfile:
        """Carga PERFIL.md desde disco y lo parsea."""
        if isinstance(path, str):
            path = Path(path)
        text = path.read_text(encoding="utf-8")
        return cls.from_perfil(text)

    @staticmethod
    def _parse_sections(perfil: str) -> dict[str, str]:
        """Extrae todas las secciones en un solo pass."""
        sections: dict[str, str] = {}
        for name, pattern in _SECTION_PATTERNS:
            m = re.search(pattern, perfil, re.DOTALL | re.IGNORECASE)
            if m:
                sections[name] = m.group(1).strip()
        return sections

    @staticmethod
    def _parse_skills(sections: dict[str, str]) -> list[dict]:
        """Parsea skills desde secciones Skills técnicas + Educación."""
        skills: list[dict[str, str]] = []
        existing_names: set[str] = set()

        # Skills técnicas
        skills_block = sections.get("Skills técnicas")
        if skills_block:
            for line in skills_block.strip().split("\n"):
                line = line.strip()
                if not line.startswith("-"):
                    continue
                m = _SKILL_LINE_PATTERN.match(line)
                if m:
                    name = m.group(1).strip()
                    level = m.group(2).strip().lower()
                    evidence = m.group(3).strip() if m.group(3) else ""
                    skills.append({"name": name, "level": level, "evidence": evidence})
                    existing_names.add(name.lower())
                else:
                    clean = line.lstrip("- ").strip()
                    if clean and clean.lower() not in existing_names:
                        skills.append(
                            {
                                "name": clean,
                                "level": "básico",
                                "evidence": "sin información de nivel",
                            }
                        )
                        existing_names.add(clean.lower())

        # Educación como skills de dominio (nivel avanzado)
        edu_block = sections.get("Educación")
        if edu_block:
            for line in edu_block.strip().split("\n"):
                m = re.match(r"- \*\*([^*]+)\*\*", line.strip())
                if m:
                    title = m.group(1).strip()
                    if title.lower() not in existing_names:
                        skills.append(
                            {
                                "name": title,
                                "level": "avanzado",
                                "evidence": "formación académica",
                            }
                        )
                        existing_names.add(title.lower())

        return skills

    @staticmethod
    def _parse_gap(sections: dict[str, str]) -> float | None:
        """Parsea employment_gap desde sección Gap de empleo."""
        gap_block = sections.get("Gap de empleo")
        if not gap_block:
            return None
        m = _GAP_PATTERN.search(gap_block)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
        return None

    @staticmethod
    def _parse_location(perfil: str) -> str:
        """Parsea ubicación desde PERFIL.md completo (está en ## Datos base)."""
        m = _LOCATION_PATTERN.search(perfil)
        return m.group(1).strip() if m else ""

    @staticmethod
    def _parse_experience_years(sections: dict[str, str], perfil: str) -> float:
        """Parsea años de experiencia desde sección Experiencia.

        Fallback 1: mención explícita en el perfil completo.
        Fallback 2: span desde fechas en sección Experiencia.
        """
        # Fallback 1 — mención explícita en todo el perfil
        m = re.search(
            r"(?:años?.*experiencia|experiencia.*años?).*?([\d.]+)",
            perfil,
            re.IGNORECASE,
        )
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass

        # Fallback 2 — span desde duraciones en ## Experiencia
        exp_block = sections.get("Experiencia")
        if not exp_block:
            return 0.0

        dates = _DURATION_PATTERN.findall(exp_block)
        if not dates:
            return 0.0

        all_months: list[int] = []
        for sm, sy, em, ey in dates:
            sm_i = month_from_name(sm)
            em_i = month_from_name(em)
            if sm_i is not None and em_i is not None:
                all_months.append(int(sy) * 12 + sm_i)
                all_months.append(int(ey) * 12 + em_i)

        if not all_months:
            return 0.0

        span_months = max(all_months) - min(all_months)
        return round(span_months / 12, 1)

    def excerpt(self, section_names: list[str]) -> str:
        """Compone excerpt con las secciones indicadas.

        Omite secciones que no existen en el perfil (log DEBUG).
        """
        parts: list[str] = []
        for name in section_names:
            content = self.perfil_sections.get(name)
            if content is None:
                log.debug(
                    "Sección '%s' no encontrada en PERFIL.md, omitiendo",
                    name,
                )
                continue
            parts.append(f"## {name}\n{content}")
        return "\n\n".join(parts)
