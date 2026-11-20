"""Перевод зарплат в одну валюту и сравнение с ожиданиями."""
import logging

import httpx

log = logging.getLogger(__name__)

# Сколько единиц валюты за 1 USD. Запасные значения, если курс не удалось скачать.
_RATES: dict[str, float] = {
    "USD": 1.0,
    "EUR": 0.92,
    "GBP": 0.79,
    "RUB": 90.0,
    "AZN": 1.7,
    "KZT": 500.0,
    "UAH": 41.0,
    "BYN": 3.3,
    "UZS": 12700.0,
    "GEL": 2.7,
    "KGS": 87.0,
    "TRY": 34.0,
    "PLN": 4.0,
    "CAD": 1.38,
    "AUD": 1.5,
    "CHF": 0.88,
}
_ALIASES = {"RUR": "RUB", "$": "USD", "€": "EUR", "£": "GBP", "₽": "RUB", "₼": "AZN", "₸": "KZT"}

# Во сколько раз умножить, чтобы получить месячную сумму
_PERIOD_TO_MONTH = {"month": 1.0, "year": 1 / 12, "hour": 168.0, "day": 21.0, "week": 4.33}


def normalize_currency(code: str | None) -> str | None:
    if not code:
        return None
    code = code.strip()
    code = _ALIASES.get(code, code).upper()
    return _ALIASES.get(code, code)


async def refresh_rates() -> None:
    """Пытается обновить курсы с открытого API. При ошибке остаются запасные."""
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get("https://open.er-api.com/v6/latest/USD")
            r.raise_for_status()
            rates = r.json().get("rates", {})
        if rates:
            _RATES.update({k.upper(): float(v) for k, v in rates.items()})
            log.info("Курсы валют обновлены (%d валют)", len(rates))
    except Exception as e:  # сеть недоступна — работаем на запасных курсах
        log.warning("Не удалось обновить курсы валют: %s", e)


def convert(amount: float, from_cur: str, to_cur: str) -> float | None:
    f, t = normalize_currency(from_cur), normalize_currency(to_cur)
    if f not in _RATES or t not in _RATES:
        return None
    return amount / _RATES[f] * _RATES[t]


def monthly_max(
    salary_from: float | None,
    salary_to: float | None,
    currency: str | None,
    period: str | None,
    target_currency: str,
) -> float | None:
    """Верхняя граница вилки в месяц в валюте пользователя (None если неизвестно)."""
    top = salary_to if salary_to is not None else salary_from
    if top is None or not currency:
        return None
    top *= _PERIOD_TO_MONTH.get((period or "month").lower(), 1.0)
    return convert(top, currency, target_currency)


def salary_ok(
    salary_from: float | None,
    salary_to: float | None,
    currency: str | None,
    period: str | None,
    min_salary: float | None,
    user_currency: str,
    tolerance: float = 0.1,
) -> bool | None:
    """True/False — подходит ли зарплата; None — зарплата неизвестна.

    tolerance: допускаем вилку чуть ниже ожиданий (по умолчанию на 10%),
    т.к. верх вилки часто обсуждается.
    """
    if not min_salary:
        return True
    top = monthly_max(salary_from, salary_to, currency, period, user_currency)
    if top is None:
        return None
    return top >= min_salary * (1 - tolerance)


def fmt_salary(salary_from, salary_to, currency, period) -> str:
    if salary_from is None and salary_to is None:
        return "не указана"
    cur = normalize_currency(currency) or ""
    per = {"month": "/мес", "year": "/год", "hour": "/час", "day": "/день", "week": "/нед"}.get(
        (period or "month").lower(), ""
    )
    def n(x):
        return f"{x:,.0f}".replace(",", " ")
    if salary_from is not None and salary_to is not None:
        return f"{n(salary_from)}–{n(salary_to)} {cur}{per}"
    if salary_from is not None:
        return f"от {n(salary_from)} {cur}{per}"
    return f"до {n(salary_to)} {cur}{per}"
