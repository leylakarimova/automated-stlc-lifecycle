import json
import sqlite3
import time

DEFAULT_SETTINGS = {
    "min_salary": None,          # минимальная зарплата в месяц
    "currency": "USD",
    "include_no_salary": True,   # присылать вакансии без указанной зарплаты
    "min_score": 70,             # минимальная оценка соответствия CV (0-100)
    "queries": [],               # поисковые запросы (по умолчанию берутся из CV)
    "hh_area": None,             # регион hh.ru (113 — Россия, 1 — Москва, 40 — Казахстан ...)
    "remote_only": False,
    "sources": ["hh.ru", "remotive", "remoteok", "arbeitnow"],
    "preferences": "",           # свободный текст: «только удалёнка», «без стартапов» ...
    "paused": False,
}


class Storage:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id INTEGER PRIMARY KEY,
                cv_text TEXT,
                cv_summary TEXT,
                settings TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS seen (
                chat_id INTEGER NOT NULL,
                vacancy_key TEXT NOT NULL,
                score INTEGER,
                sent INTEGER NOT NULL DEFAULT 0,
                ts REAL NOT NULL,
                PRIMARY KEY (chat_id, vacancy_key)
            );
        """)
        self.db.commit()

    def ensure_user(self, chat_id: int) -> None:
        self.db.execute("INSERT OR IGNORE INTO users(chat_id) VALUES (?)", (chat_id,))
        self.db.commit()

    def get_settings(self, chat_id: int) -> dict:
        self.ensure_user(chat_id)
        raw = self.db.execute("SELECT settings FROM users WHERE chat_id=?", (chat_id,)).fetchone()[0]
        return {**DEFAULT_SETTINGS, **json.loads(raw or "{}")}

    def update_settings(self, chat_id: int, **changes) -> dict:
        s = self.get_settings(chat_id)
        s.update(changes)
        self.db.execute("UPDATE users SET settings=? WHERE chat_id=?",
                        (json.dumps(s, ensure_ascii=False), chat_id))
        self.db.commit()
        return s

    def set_cv(self, chat_id: int, cv_text: str, cv_summary: str) -> None:
        self.ensure_user(chat_id)
        self.db.execute("UPDATE users SET cv_text=?, cv_summary=? WHERE chat_id=?",
                        (cv_text, cv_summary, chat_id))
        self.db.commit()

    def get_cv(self, chat_id: int) -> tuple[str | None, str | None]:
        row = self.db.execute("SELECT cv_text, cv_summary FROM users WHERE chat_id=?",
                              (chat_id,)).fetchone()
        return (row[0], row[1]) if row else (None, None)

    def active_users(self) -> list[int]:
        rows = self.db.execute("SELECT chat_id, settings FROM users WHERE cv_text IS NOT NULL")
        return [cid for cid, s in rows if not json.loads(s or "{}").get("paused")]

    def is_seen(self, chat_id: int, key: str) -> bool:
        return self.db.execute("SELECT 1 FROM seen WHERE chat_id=? AND vacancy_key=?",
                               (chat_id, key)).fetchone() is not None

    def mark_seen(self, chat_id: int, key: str, score: int | None = None, sent: bool = False):
        self.db.execute(
            "INSERT OR REPLACE INTO seen(chat_id, vacancy_key, score, sent, ts) VALUES (?,?,?,?,?)",
            (chat_id, key, score, int(sent), time.time()))
        self.db.commit()

    def forget_seen(self, chat_id: int) -> None:
        self.db.execute("DELETE FROM seen WHERE chat_id=?", (chat_id,))
        self.db.commit()
