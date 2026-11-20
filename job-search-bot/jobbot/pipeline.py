"""Один прогон поиска для пользователя: собрать вакансии → отфильтровать → оценить → вернуть подходящие."""
import asyncio
import logging
from dataclasses import dataclass, field

import httpx

from . import matcher, salary, sources
from .config import config
from .models import Vacancy
from .storage import Storage

log = logging.getLogger(__name__)


@dataclass
class Found:
    vacancy: Vacancy
    match: matcher.MatchResult
    salary_text: str
    salary_known: bool


@dataclass
class RunReport:
    found: list[Found] = field(default_factory=list)
    fetched: int = 0
    new: int = 0
    evaluated: int = 0
    skipped_salary: int = 0
    errors: dict[str, str] = field(default_factory=dict)


def _effective_salary(v: Vacancy, m: matcher.MatchResult | None):
    """Зарплата с сайта, а если её нет — найденная Claude в тексте."""
    if v.has_salary() and v.salary_currency:
        return v.salary_from, v.salary_to, v.salary_currency, v.salary_period
    if m and (m.salary_from is not None or m.salary_to is not None) and m.salary_currency:
        return m.salary_from, m.salary_to, m.salary_currency, m.salary_period or "month"
    return None, None, None, None


async def run_for_user(storage: Storage, chat_id: int,
                       http: httpx.AsyncClient | None = None) -> RunReport:
    report = RunReport()
    cv_text, _ = storage.get_cv(chat_id)
    if not cv_text:
        return report
    s = storage.get_settings(chat_id)
    if not s["queries"]:
        return report

    own_client = http is None
    http = http or sources.make_client()
    try:
        vacancies, report.errors = await sources.search_all(http, s["queries"], s, s["sources"])
        report.fetched = len(vacancies)

        uniq: dict[str, Vacancy] = {}
        for v in vacancies:
            if v.key not in uniq and not storage.is_seen(chat_id, v.key):
                uniq[v.key] = v
        report.new = len(uniq)

        # Дешёвый фильтр до вызова Claude: если сайт указал зарплату и она ниже ожиданий — пропускаем.
        candidates = []
        for v in uniq.values():
            if v.has_salary() and salary.salary_ok(
                v.salary_from, v.salary_to, v.salary_currency, v.salary_period,
                s["min_salary"], s["currency"]) is False:
                storage.mark_seen(chat_id, v.key)
                report.skipped_salary += 1
                continue
            candidates.append(v)

        # Ограничиваем расходы: остальные вакансии оценятся в следующий прогон.
        candidates = candidates[: config.max_vacancies_per_run]
        sem = asyncio.Semaphore(5)

        async def evaluate(v: Vacancy):
            async with sem:
                try:
                    v = await sources.enrich(http, v)
                    m = await matcher.score_vacancy(cv_text, s["preferences"], v)
                except Exception as e:
                    log.warning("Не удалось оценить %s: %s", v.key, e)
                    return None
            return v, m

        results = await asyncio.gather(*(evaluate(v) for v in candidates))
        for res in results:
            if res is None:
                continue
            v, m = res
            report.evaluated += 1
            sf, st, cur, per = _effective_salary(v, m)
            ok = salary.salary_ok(sf, st, cur, per, s["min_salary"], s["currency"])
            if ok is False:
                report.skipped_salary += 1
            elif ok is None and not s["include_no_salary"]:
                pass
            elif m.score >= s["min_score"]:
                report.found.append(Found(v, m, salary.fmt_salary(sf, st, cur, per), ok is not None))
                continue  # отметим как отправленную после успешной отправки
            storage.mark_seen(chat_id, v.key, m.score)

        report.found.sort(key=lambda f: f.match.score, reverse=True)
        return report
    finally:
        if own_client:
            await http.aclose()
