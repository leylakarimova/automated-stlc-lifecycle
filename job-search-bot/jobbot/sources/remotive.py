"""remotive.com — удалённые вакансии (бесплатный публичный API)."""
from ..models import Vacancy
from .base import Source, strip_html


class Remotive(Source):
    name = "remotive"

    async def search(self, queries, settings):
        out: dict[str, Vacancy] = {}
        for q in queries:
            r = await self.client.get("https://remotive.com/api/remote-jobs",
                                      params={"search": q, "limit": 50})
            r.raise_for_status()
            for it in r.json().get("jobs", []):
                desc = strip_html(it.get("description"))
                if it.get("salary"):
                    desc = f"Salary: {it['salary']}\n{desc}"
                out[str(it["id"])] = Vacancy(
                    source=self.name,
                    id=str(it["id"]),
                    title=it.get("title", ""),
                    company=it.get("company_name", ""),
                    url=it.get("url", ""),
                    description=desc,
                    location=f"Remote ({it.get('candidate_required_location') or 'anywhere'})",
                    tags=it.get("tags") or [],
                )
        return list(out.values())
