import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _ids(raw: str) -> set[int]:
    return {int(x) for x in raw.replace(" ", "").split(",") if x}


@dataclass(frozen=True)
class Config:
    telegram_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    claude_model: str = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
    check_interval_hours: float = float(os.getenv("CHECK_INTERVAL_HOURS", "6"))
    max_vacancies_per_run: int = int(os.getenv("MAX_VACANCIES_PER_RUN", "40"))
    db_path: str = os.getenv("DB_PATH", "jobbot.sqlite3")
    allowed_user_ids: set[int] = field(
        default_factory=lambda: _ids(os.getenv("ALLOWED_USER_IDS", ""))
    )


config = Config()
