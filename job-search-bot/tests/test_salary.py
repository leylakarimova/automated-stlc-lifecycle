from jobbot import salary


def test_convert_and_aliases():
    assert salary.convert(100, "USD", "USD") == 100
    assert salary.normalize_currency("RUR") == "RUB"
    assert salary.convert(90, "RUR", "USD") == 1.0


def test_salary_ok_month():
    # 2000-3000 USD при ожиданиях 2500 — ок
    assert salary.salary_ok(2000, 3000, "USD", "month", 2500, "USD") is True
    # до 2000 при ожиданиях 3000 — нет
    assert salary.salary_ok(None, 2000, "USD", "month", 3000, "USD") is False
    # 10% допуск: 2300 при ожиданиях 2500 — ок
    assert salary.salary_ok(2300, None, "USD", "month", 2500, "USD") is True


def test_salary_year_and_unknown():
    # 60k USD в год = 5000/мес
    assert salary.salary_ok(None, 60000, "USD", "year", 4000, "USD") is True
    assert salary.salary_ok(None, None, None, None, 4000, "USD") is None
    assert salary.salary_ok(None, None, None, None, None, "USD") is True


def test_cross_currency():
    # 270 000 RUB/мес ≈ 3000 USD
    assert salary.salary_ok(200000, 270000, "RUR", "month", 2800, "USD") is True
    assert salary.salary_ok(100000, 150000, "RUR", "month", 2800, "USD") is False


def test_fmt():
    assert salary.fmt_salary(None, None, None, None) == "не указана"
    assert salary.fmt_salary(1000, 2000, "usd", "month") == "1 000–2 000 USD/мес"
