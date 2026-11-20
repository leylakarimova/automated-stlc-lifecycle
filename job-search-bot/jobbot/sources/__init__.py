import asyncio
import logging

import httpx

from ..models import Vacancy
from .arbeitnow import Arbeitnow
from .base import USER_AGENT, Source
from .hh import HeadHunter
from .remoteok import RemoteOK
from .remotive import Remotive

log = logging.getLogger(__name__)

ALL_SOURCES: dict[str, type[Source]] = {
    s.name: s for s in (HeadHunter, Remotive, RemoteOK, Arbeitnow)
}


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=30, follow_redirects=True,
                             headers={"User-Agent": USER_AGENT})


async def search_all(client: httpx.AsyncClient, queries: list[str], settings: dict,
                     enabled: list[str]) -> tuple[list[Vacancy], dict[str, str]]:
    """Ищет на всех включённых сайтах параллельно. Возвращает вакансии и ошибки по сайтам."""
    sources = [ALL_SOURCES[n](client) for n in enabled if n in ALL_SOURCES]
    results = await asyncio.gather(*(s.search(queries, settings) for s in sources),
                                   return_exceptions=True)
    vacancies, errors = [], {}
    for s, res in zip(sources, results):
        if isinstance(res, Exception):
            log.warning("%s: ошибка поиска: %s", s.name, res)
            errors[s.name] = str(res)[:200]
        else:
            vacancies.extend(res)
    return vacancies, errors


async def enrich(client: httpx.AsyncClient, v: Vacancy) -> Vacancy:
    cls = ALL_SOURCES.get(v.source)
    return await cls(client).enrich(v) if cls else v
