"""hh.ru (а также hh.kz / hh.uz / hh.az — у них общий API api.hh.ru)."""
import logging

from ..models import Vacancy
from .base import Source, strip_html

log = logging.getLogger(__name__)
API = "https://api.hh.ru"


class HeadHunter(Source):
    name = "hh.ru"

    async def search(self, queries, settings):
        out: dict[str, Vacancy] = {}
        for q in queries:
            params = {
                "text": q,
                "per_page": 50,
                "period": 3,              # за последние 3 дня
                "order_by": "publication_time",
            }
            if settings.get("hh_area"):
                params["area"] = settings["hh_area"]
            if settings.get("remote_only"):
                params["schedule"] = "remote"
            r = await self.client.get(f"{API}/vacancies", params=params,
                                      headers={"HH-User-Agent": self.client.headers["User-Agent"]})
            r.raise_for_status()
            for it in r.json().get("items", []):
                sal = it.get("salary") or {}
                snippet = it.get("snippet") or {}
                out[str(it["id"])] = Vacancy(
                    source=self.name,
                    id=str(it["id"]),
                    title=it.get("name", ""),
                    company=(it.get("employer") or {}).get("name", ""),
                    url=it.get("alternate_url", ""),
                    description=strip_html(
                        f"{snippet.get('requirement') or ''}\n{snippet.get('responsibility') or ''}"
                    ),
                    location=(it.get("area") or {}).get("name", ""),
                    salary_from=sal.get("from"),
                    salary_to=sal.get("to"),
                    salary_currency=sal.get("currency"),
                )
        return list(out.values())

    async def enrich(self, v):
        try:
            r = await self.client.get(f"{API}/vacancies/{v.id}",
                                      headers={"HH-User-Agent": self.client.headers["User-Agent"]})
            r.raise_for_status()
            data = r.json()
            v.description = strip_html(data.get("description")) or v.description
            v.tags = [s["name"] for s in data.get("key_skills", [])]
        except Exception as e:
            log.warning("hh.ru: не удалось загрузить описание %s: %s", v.id, e)
        return v
