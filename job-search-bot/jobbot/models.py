from dataclasses import dataclass, field


@dataclass
class Vacancy:
    source: str            # "hh.ru", "remotive", ...
    id: str                # уникален в рамках source
    title: str
    company: str
    url: str
    description: str = ""
    location: str = ""
    # Зарплата, если сайт отдаёт её структурно. Иначе Claude попробует найти в тексте.
    salary_from: float | None = None
    salary_to: float | None = None
    salary_currency: str | None = None
    salary_period: str = "month"  # month | year | hour
    tags: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.source}:{self.id}"

    def has_salary(self) -> bool:
        return self.salary_from is not None or self.salary_to is not None
