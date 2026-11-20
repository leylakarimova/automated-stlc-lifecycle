import asyncio

import httpx

from jobbot.sources import search_all


def test_parsers_with_mock_http():
    def handler(req: httpx.Request):
        h = req.url.host
        if h == "api.hh.ru":
            assert req.headers["HH-User-Agent"]
            return httpx.Response(200, json={"items": [{
                "id": "77", "name": "QA Engineer", "alternate_url": "https://hh.ru/vacancy/77",
                "employer": {"name": "Acme"}, "area": {"name": "Баку"},
                "salary": {"from": 3000, "to": None, "currency": "AZN"},
                "snippet": {"requirement": "<highlighttext>QA</highlighttext> 3+ years",
                            "responsibility": "Testing"}}]})
        if h == "remotive.com":
            return httpx.Response(200, json={"jobs": [{
                "id": 5, "title": "QA Lead", "company_name": "R", "url": "u",
                "description": "<p>hi</p>", "salary": "$80k", "candidate_required_location": "EU"}]})
        if h == "remoteok.com":
            return httpx.Response(200, json=[{"legal": "x"}, {
                "id": 9, "position": "QA Automation", "company": "O", "tags": ["qa"],
                "description": "d", "salary_min": 60000, "salary_max": 90000},
                {"id": 10, "position": "Designer", "tags": []}])
        if h == "www.arbeitnow.com":
            return httpx.Response(200, json={"data": [{
                "slug": "qa-1", "title": "QA Engineer", "company_name": "A", "url": "u",
                "description": "d", "remote": True, "location": "Berlin", "tags": []}]})
        return httpx.Response(404)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                     headers={"User-Agent": "t"}) as c:
            return await search_all(c, ["QA"], {}, ["hh.ru", "remotive", "remoteok", "arbeitnow"])

    vacs, errors = asyncio.run(run())
    assert errors == {}
    by = {v.source: v for v in vacs}
    assert set(by) == {"hh.ru", "remotive", "remoteok", "arbeitnow"}
    assert by["hh.ru"].salary_currency == "AZN" and "3+ years" in by["hh.ru"].description
    assert by["remoteok"].salary_period == "year" and by["remoteok"].salary_to == 90000
    assert "Salary: $80k" in by["remotive"].description
    assert len([v for v in vacs if v.source == "remoteok"]) == 1
