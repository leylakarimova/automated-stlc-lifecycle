"""Сравнение вакансий с CV через Claude API."""
import json
import logging
from dataclasses import dataclass

import anthropic

from .config import config
from .models import Vacancy

log = logging.getLogger(__name__)

_client: anthropic.AsyncAnthropic | None = None


def client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic()  # ключ берётся из ANTHROPIC_API_KEY
    return _client


def _nullable(t: str) -> dict:
    return {"anyOf": [{"type": t}, {"type": "null"}]}


CV_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "search_queries"],
    "properties": {
        "summary": {"type": "string"},
        "search_queries": {"type": "array", "items": {"type": "string"}},
    },
}

MATCH_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["score", "reasons", "missing", "salary_from", "salary_to",
                 "salary_currency", "salary_period"],
    "properties": {
        "score": {"type": "integer"},
        "reasons": {"type": "string"},
        "missing": {"type": "string"},
        "salary_from": _nullable("number"),
        "salary_to": _nullable("number"),
        "salary_currency": _nullable("string"),
        "salary_period": {"enum": ["month", "year", "hour", "day", "week", "unknown"]},
    },
}

CV_SYSTEM = """Ты помогаешь кандидату искать работу. Тебе дают текст резюме (CV).
Верни:
- summary: 3–5 предложений на русском: роль, уровень (junior/middle/senior/lead), годы опыта, ключевые навыки, языки.
- search_queries: 3–6 коротких поисковых запросов (2–3 слова каждый) для сайтов вакансий —
  названия должностей, на которые кандидат реально подходит. Пиши на английском
  (так их понимают и русскоязычные, и международные сайты); можно добавить 1–2 варианта на русском."""

MATCH_SYSTEM = """Ты — опытный рекрутер. Оцени, насколько кандидат подходит на вакансию.

Шкала score (0–100):
- 85–100: подходит почти по всем требованиям, уровень совпадает.
- 70–84: подходит по основным требованиям, есть небольшие пробелы, стоит откликаться.
- 50–69: частичное совпадение, серьёзные пробелы или другой уровень.
- 0–49: не подходит (другая профессия, сильно другой уровень, нет ключевых навыков, требования к локации/гражданству/языку, которые кандидат не выполняет).
Учитывай пожелания кандидата: если вакансия им явно противоречит, снижай оценку.
Зарплату в score НЕ учитывай — её проверяют отдельно.

reasons: 1–2 предложения на русском, почему подходит / не подходит.
missing: каких требований вакансии кандидату не хватает (кратко, на русском; пустая строка, если всё есть).
salary_*: если в тексте вакансии указана зарплата — извлеки её (числа как есть, валюта ISO-кодом, период).
Если зарплаты в тексте нет — null и salary_period = "unknown".

Резюме кандидата:
<cv>
{cv}
</cv>

Пожелания кандидата:
<preferences>
{prefs}
</preferences>"""


@dataclass
class MatchResult:
    score: int
    reasons: str
    missing: str
    salary_from: float | None
    salary_to: float | None
    salary_currency: str | None
    salary_period: str | None


async def _ask(system: list[dict], user: str, schema: dict, max_tokens: int = 4000) -> dict:
    resp = await client().beta.messages.create(
        model=config.claude_model,
        max_tokens=max_tokens,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",  # если модель откажет по policy — запрос повторит другая модель
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("Claude отказался обрабатывать запрос")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("Ответ Claude обрезан (max_tokens)")
    text = next((b.text for b in resp.content if b.type == "text"), None)
    if not text:
        raise RuntimeError("Пустой ответ Claude")
    return json.loads(text)


async def analyze_cv(cv_text: str) -> tuple[str, list[str]]:
    data = await _ask([{"type": "text", "text": CV_SYSTEM}], f"<cv>\n{cv_text}\n</cv>", CV_SCHEMA)
    queries = [q.strip() for q in data["search_queries"] if q.strip()][:6]
    return data["summary"].strip(), queries


def _vacancy_text(v: Vacancy) -> str:
    parts = [f"Должность: {v.title}", f"Компания: {v.company}", f"Локация: {v.location}"]
    if v.tags:
        parts.append("Навыки/теги: " + ", ".join(v.tags))
    if v.has_salary():
        parts.append(f"Зарплата (из данных сайта): {v.salary_from}–{v.salary_to} "
                     f"{v.salary_currency} за {v.salary_period}")
    parts.append("Описание:\n" + v.description[:12000])
    return "\n".join(parts)


async def score_vacancy(cv_text: str, preferences: str, v: Vacancy) -> MatchResult:
    # CV и пожелания одинаковы для всех вакансий пользователя — кладём их в system
    # и кэшируем, чтобы не платить за них полную цену при каждой оценке.
    system = [{
        "type": "text",
        "text": MATCH_SYSTEM.format(cv=cv_text, prefs=preferences or "не указаны"),
        "cache_control": {"type": "ephemeral"},
    }]
    d = await _ask(system, f"<vacancy>\n{_vacancy_text(v)}\n</vacancy>", MATCH_SCHEMA)
    period = d.get("salary_period")
    return MatchResult(
        score=max(0, min(100, int(d["score"]))),
        reasons=d.get("reasons", ""),
        missing=d.get("missing", ""),
        salary_from=d.get("salary_from"),
        salary_to=d.get("salary_to"),
        salary_currency=d.get("salary_currency"),
        salary_period=None if period == "unknown" else period,
    )
