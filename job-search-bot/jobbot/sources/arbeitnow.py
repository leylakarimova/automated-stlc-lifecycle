"""arbeitnow.com — вакансии в Европе (много в Германии), часть удалённые."""
from ..models import Vacancy
from .base import Source, matches_query, strip_html


class Arbeitnow(Source):
    name = "arbeitnow"
    pages = 3

    async def search(self, queries, settings):
        out = []
        for page in range(1, self.pages + 1):
            r = await self.client.get("https://www.arbeitnow.com/api/job-board-api",
                                      params={"page": page})
            r.raise_for_status()
            for it in r.json().get("data", []):
                tags = it.get("tags") or []
                if settings.get("remote_only") and not it.get("remote"):
                    continue
                if not matches_query(f"{it.get('title', '')} {' '.join(tags)}", queries):
                    continue
                out.append(Vacancy(
                    source=self.name,
                    id=str(it.get("slug")),
                    title=it.get("title", ""),
                    company=it.get("company_name", ""),
                    url=it.get("url", ""),
                    description=strip_html(it.get("description")),
                    location=("Remote, " if it.get("remote") else "") + (it.get("location") or ""),
                    tags=tags,
                ))
        return out
