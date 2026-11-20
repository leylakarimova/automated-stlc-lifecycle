"""remoteok.com — удалённые вакансии. API отдаёт свежую ленту, фильтруем сами."""
from ..models import Vacancy
from .base import Source, matches_query, strip_html


class RemoteOK(Source):
    name = "remoteok"

    async def search(self, queries, settings):
        r = await self.client.get("https://remoteok.com/api")
        r.raise_for_status()
        out = []
        for it in r.json():
            if not isinstance(it, dict) or "id" not in it or "position" not in it:
                continue  # первый элемент — юридическое уведомление
            tags = it.get("tags") or []
            if not matches_query(f"{it.get('position', '')} {' '.join(tags)}", queries):
                continue
            out.append(Vacancy(
                source=self.name,
                id=str(it["id"]),
                title=it.get("position", ""),
                company=it.get("company", ""),
                url=it.get("url") or f"https://remoteok.com/remote-jobs/{it['id']}",
                description=strip_html(it.get("description")),
                location=f"Remote ({it.get('location') or 'anywhere'})",
                salary_from=it.get("salary_min") or None,
                salary_to=it.get("salary_max") or None,
                salary_currency="USD" if (it.get("salary_min") or it.get("salary_max")) else None,
                salary_period="year",
                tags=tags,
            ))
        return out
