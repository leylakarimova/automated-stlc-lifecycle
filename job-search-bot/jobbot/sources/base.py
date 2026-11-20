import html
import re

import httpx

from ..models import Vacancy

USER_AGENT = "JobSearchTelegramBot/1.0 (personal job alerts)"


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def matches_query(text: str, queries: list[str]) -> bool:
    """Подходит ли текст хотя бы под один запрос (все слова запроса должны встретиться)."""
    low = text.lower()
    for q in queries:
        words = [w for w in re.split(r"\W+", q.lower()) if len(w) > 1]
        if words and all(w in low for w in words):
            return True
    return False


class Source:
    name = "base"

    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def search(self, queries: list[str], settings: dict) -> list[Vacancy]:
        raise NotImplementedError

    async def enrich(self, v: Vacancy) -> Vacancy:
        """Догрузить полное описание (если источник отдаёт в поиске только кусок)."""
        return v
