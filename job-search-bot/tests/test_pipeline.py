import asyncio

from jobbot import matcher, pipeline, sources
from jobbot.models import Vacancy
from jobbot.sources.base import matches_query, strip_html
from jobbot.storage import Storage


def _vac(i, **kw):
    return Vacancy(source="hh.ru", id=str(i), title=f"QA {i}", company="X",
                   url=f"https://hh.ru/vacancy/{i}", description="Selenium, Python", **kw)


def test_helpers():
    assert matches_query("Senior QA Automation Engineer", ["qa automation"])
    assert not matches_query("Backend Developer", ["qa automation"])
    assert strip_html("<p>a&amp;b</p><ul><li>x</li></ul>") == "a&b\n x"


def test_run_for_user(tmp_path, monkeypatch):
    st = Storage(str(tmp_path / "db.sqlite3"))
    st.set_cv(1, "CV " * 100, "QA engineer")
    st.update_settings(1, queries=["QA"], min_salary=2000, currency="USD",
                       include_no_salary=False, min_score=70)

    vacs = [
        _vac(1, salary_from=3000, salary_to=4000, salary_currency="USD"),  # подходит
        _vac(2, salary_from=500, salary_to=800, salary_currency="USD"),    # мало — без Claude
        _vac(3),                                                            # зарплату найдёт Claude
        _vac(4),                                                            # без зарплаты → не присылаем
        _vac(5, salary_from=3000, salary_currency="USD"),                   # низкий score
    ]

    async def fake_search(client, queries, settings, enabled):
        return list(vacs), {"remoteok": "timeout"}

    async def fake_enrich(client, v):
        return v

    calls = []

    async def fake_score(cv, prefs, v):
        calls.append(v.id)
        score = 40 if v.id == "5" else 90
        sal = (2500, None, "EUR", "month") if v.id == "3" else (None, None, None, None)
        return matcher.MatchResult(score, "ok", "", *sal)

    monkeypatch.setattr(sources, "search_all", fake_search)
    monkeypatch.setattr(sources, "enrich", fake_enrich)
    monkeypatch.setattr(matcher, "score_vacancy", fake_score)

    async def run():
        async with sources.make_client() as c:
            return await pipeline.run_for_user(st, 1, c)

    rep = asyncio.run(run())
    assert sorted(f.vacancy.id for f in rep.found) == ["1", "3"]
    assert "2" not in calls                      # отсеяна до вызова Claude
    assert rep.skipped_salary == 1
    assert rep.errors == {"remoteok": "timeout"}
    assert st.is_seen(1, "hh.ru:2") and st.is_seen(1, "hh.ru:4") and st.is_seen(1, "hh.ru:5")
    assert not st.is_seen(1, "hh.ru:1")          # отметится после успешной отправки

    # Повторный прогон: уже просмотренные не оцениваются заново
    calls.clear()
    asyncio.run(run())
    assert sorted(calls) == ["1", "3"]
