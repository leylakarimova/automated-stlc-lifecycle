"""Telegram-бот: ищет вакансии, сравнивает с CV и присылает подходящие."""
import asyncio
import functools
import html
import logging

from telegram import LinkPreviewOptions, Update
from telegram.constants import ParseMode
from telegram.ext import (Application, CommandHandler, ContextTypes, MessageHandler,
                          filters)

from . import cv_parser, matcher, pipeline, salary
from .config import config
from .sources import ALL_SOURCES
from .storage import Storage

log = logging.getLogger(__name__)
storage = Storage(config.db_path)
_locks: dict[int, asyncio.Lock] = {}
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)

HELP = """<b>Я ищу вакансии под ваше CV и присылаю только подходящие.</b>

1. Пришлите CV файлом (PDF / DOCX / TXT) или текстом после /cv
2. Укажите ожидания по зарплате: <code>/salary 2500 USD</code>
3. Готово — я буду проверять сайты каждые {hours:g} ч. Запустить сразу: /search

<b>Настройки</b>
/salary 2500 USD — минимальная зарплата в месяц (<code>/salary off</code> — не учитывать)
/nosalary on|off — присылать ли вакансии без указанной зарплаты
/queries QA Engineer, Test Automation — поисковые запросы (по умолчанию из CV)
/prefs текст — пожелания: «только удалёнка, без gambling, английский ок»
/minscore 70 — минимальная оценка соответствия CV (0–100)
/remote on|off — только удалённая работа
/area 113 — регион hh.ru (113 Россия, 1 Москва, 2 СПб, 40 Казахстан, 9 Азербайджан, 0 — любой)
/sources — включить/выключить сайты
/settings — текущие настройки
/pause, /resume — остановить/возобновить автопоиск
/reset_seen — забыть уже просмотренные вакансии"""


def restricted(fn):
    @functools.wraps(fn)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id if update.effective_user else None
        if config.allowed_user_ids and uid not in config.allowed_user_ids:
            await update.effective_message.reply_text(
                f"Доступ закрыт. Ваш id: {uid} — добавьте его в ALLOWED_USER_IDS.")
            return
        return await fn(update, context)
    return wrapper


async def reply(update: Update, text: str):
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML,
                                              link_preview_options=NO_PREVIEW)


def settings_text(chat_id: int) -> str:
    s = storage.get_settings(chat_id)
    _, summary = storage.get_cv(chat_id)
    sal = f"{s['min_salary']:,.0f} {s['currency']}/мес".replace(",", " ") if s["min_salary"] else "не задана"
    return (
        f"<b>CV:</b> {html.escape(summary) if summary else 'не загружено'}\n\n"
        f"<b>Зарплата от:</b> {sal}\n"
        f"<b>Без зарплаты:</b> {'присылать' if s['include_no_salary'] else 'не присылать'}\n"
        f"<b>Запросы:</b> {html.escape(', '.join(s['queries'])) or '—'}\n"
        f"<b>Пожелания:</b> {html.escape(s['preferences']) or '—'}\n"
        f"<b>Мин. оценка:</b> {s['min_score']}\n"
        f"<b>Только удалёнка:</b> {'да' if s['remote_only'] else 'нет'}\n"
        f"<b>Регион hh.ru:</b> {s['hh_area'] or 'любой'}\n"
        f"<b>Сайты:</b> {', '.join(s['sources'])}\n"
        f"<b>Автопоиск:</b> {'на паузе' if s['paused'] else f'каждые {config.check_interval_hours:g} ч'}"
    )


# ---------- команды ----------

@restricted
async def cmd_start(update: Update, context):
    storage.ensure_user(update.effective_chat.id)
    await reply(update, HELP.format(hours=config.check_interval_hours))


@restricted
async def cmd_cv(update: Update, context):
    context.user_data["awaiting_cv"] = True
    await reply(update, "Пришлите CV файлом (PDF/DOCX/TXT) или вставьте текст следующим сообщением.")


async def _save_cv(update: Update, text: str):
    chat_id = update.effective_chat.id
    if len(text) < 200:
        await reply(update, "Текст CV слишком короткий — проверьте файл (сканы-картинки PDF я не читаю).")
        return
    await reply(update, "Читаю CV…")
    try:
        summary, queries = await matcher.analyze_cv(text)
    except Exception as e:
        log.exception("analyze_cv")
        await reply(update, f"Не удалось проанализировать CV: {html.escape(str(e))}")
        return
    storage.set_cv(chat_id, text, summary)
    storage.update_settings(chat_id, queries=queries)
    s = storage.get_settings(chat_id)
    msg = (f"✅ CV сохранено.\n\n<b>Как я вас понял:</b> {html.escape(summary)}\n\n"
           f"<b>Буду искать:</b> {html.escape(', '.join(queries))}\n"
           f"(изменить: /queries)\n\n")
    if not s["min_salary"]:
        msg += "Теперь укажите ожидания по зарплате, например <code>/salary 2500 USD</code>, затем /search"
    else:
        msg += "Запустить поиск сейчас: /search"
    await reply(update, msg)


@restricted
async def on_document(update: Update, context):
    doc = update.message.document
    if doc.file_size and doc.file_size > 10 * 1024 * 1024:
        await reply(update, "Файл слишком большой (макс. 10 МБ).")
        return
    f = await doc.get_file()
    data = bytes(await f.download_as_bytearray())
    try:
        text = cv_parser.extract_text(data, doc.file_name or "cv.txt")
    except Exception as e:
        await reply(update, f"Не смог прочитать файл: {html.escape(str(e))}")
        return
    context.user_data["awaiting_cv"] = False
    await _save_cv(update, text)


@restricted
async def on_text(update: Update, context):
    text = update.message.text or ""
    if context.user_data.get("awaiting_cv") or len(text) > 800:
        context.user_data["awaiting_cv"] = False
        await _save_cv(update, text)
    else:
        await reply(update, "Не понял. Список команд: /start")


def parse_amount(raw: str) -> float:
    raw = raw.replace(" ", "").replace(",", ".").lower()
    mult = 1000 if raw.endswith(("k", "к")) else 1
    return float(raw.rstrip("kк")) * mult


@restricted
async def cmd_salary(update: Update, context):
    args = context.args
    chat_id = update.effective_chat.id
    if not args:
        await reply(update, "Пример: <code>/salary 2500 USD</code> (в месяц). Отключить: <code>/salary off</code>")
        return
    if args[0].lower() in ("off", "0", "нет"):
        storage.update_settings(chat_id, min_salary=None)
        await reply(update, "Зарплата больше не учитывается.")
        return
    try:
        amount = parse_amount(args[0])
    except ValueError:
        await reply(update, "Не понял сумму. Пример: <code>/salary 2500 USD</code>")
        return
    cur = salary.normalize_currency(args[1] if len(args) > 1 else storage.get_settings(chat_id)["currency"])
    if salary.convert(1, cur, "USD") is None:
        await reply(update, f"Не знаю валюту {html.escape(cur)}. Используйте ISO-код: USD, EUR, RUB, AZN, KZT…")
        return
    storage.update_settings(chat_id, min_salary=amount, currency=cur)
    await reply(update, f"Ок, ищу вакансии от {amount:,.0f} {cur}/мес.".replace(",", " ")
                + "\nВилки ниже на 10% тоже пропускаю — верх часто обсуждается.")


def _toggle(arg: list[str]) -> bool | None:
    if not arg:
        return None
    return {"on": True, "да": True, "yes": True, "off": False, "нет": False, "no": False}.get(arg[0].lower())


@restricted
async def cmd_nosalary(update: Update, context):
    v = _toggle(context.args)
    if v is None:
        await reply(update, "Использование: /nosalary on|off")
        return
    storage.update_settings(update.effective_chat.id, include_no_salary=v)
    await reply(update, "Вакансии без зарплаты: " + ("присылаю" if v else "не присылаю"))


@restricted
async def cmd_remote(update: Update, context):
    v = _toggle(context.args)
    if v is None:
        await reply(update, "Использование: /remote on|off")
        return
    storage.update_settings(update.effective_chat.id, remote_only=v)
    await reply(update, "Только удалёнка: " + ("да" if v else "нет"))


@restricted
async def cmd_queries(update: Update, context):
    raw = " ".join(context.args).strip()
    if not raw:
        s = storage.get_settings(update.effective_chat.id)
        await reply(update, "Текущие запросы: " + html.escape(", ".join(s["queries"]) or "—")
                    + "\nИзменить: <code>/queries QA Engineer, Test Automation</code>")
        return
    queries = [q.strip() for q in raw.split(",") if q.strip()][:10]
    storage.update_settings(update.effective_chat.id, queries=queries)
    await reply(update, "Запросы сохранены: " + html.escape(", ".join(queries)))


@restricted
async def cmd_prefs(update: Update, context):
    text = " ".join(context.args).strip()
    storage.update_settings(update.effective_chat.id, preferences=text)
    await reply(update, "Пожелания сохранены." if text else "Пожелания очищены.")


@restricted
async def cmd_minscore(update: Update, context):
    try:
        v = int(context.args[0])
        assert 0 <= v <= 100
    except Exception:
        await reply(update, "Использование: /minscore 70 (от 0 до 100)")
        return
    storage.update_settings(update.effective_chat.id, min_score=v)
    await reply(update, f"Минимальная оценка: {v}")


@restricted
async def cmd_area(update: Update, context):
    try:
        v = int(context.args[0])
    except Exception:
        await reply(update, "Использование: /area 113 (0 — любой регион)")
        return
    storage.update_settings(update.effective_chat.id, hh_area=v or None)
    await reply(update, f"Регион hh.ru: {v or 'любой'}")


@restricted
async def cmd_sources(update: Update, context):
    chat_id = update.effective_chat.id
    s = storage.get_settings(chat_id)
    enabled = list(s["sources"])
    for name in context.args:
        if name in ALL_SOURCES:
            if name in enabled:
                enabled.remove(name)
            else:
                enabled.append(name)
    if context.args:
        storage.update_settings(chat_id, sources=enabled)
    lines = [("✅ " if n in enabled else "❌ ") + n for n in ALL_SOURCES]
    await reply(update, "\n".join(lines) + "\n\nВкл/выкл: <code>/sources remoteok</code>")


@restricted
async def cmd_settings(update: Update, context):
    await reply(update, settings_text(update.effective_chat.id))


@restricted
async def cmd_pause(update: Update, context):
    storage.update_settings(update.effective_chat.id, paused=True)
    await reply(update, "Автопоиск на паузе. /resume — возобновить.")


@restricted
async def cmd_resume(update: Update, context):
    storage.update_settings(update.effective_chat.id, paused=False)
    await reply(update, "Автопоиск возобновлён.")


@restricted
async def cmd_reset_seen(update: Update, context):
    storage.forget_seen(update.effective_chat.id)
    await reply(update, "Список просмотренных вакансий очищен.")


@restricted
async def cmd_search(update: Update, context):
    chat_id = update.effective_chat.id
    cv, _ = storage.get_cv(chat_id)
    if not cv:
        await reply(update, "Сначала пришлите CV (/cv).")
        return
    await reply(update, "🔎 Ищу… это может занять пару минут.")
    await search_and_send(context.application, chat_id, verbose=True)


# ---------- поиск и отправка ----------

def format_found(f: pipeline.Found) -> str:
    v, m = f.vacancy, f.match
    sal_note = "" if f.salary_known else " ⚠️"
    text = (
        f"<b>{html.escape(v.title)}</b> — {html.escape(v.company)}\n"
        f"📍 {html.escape(v.location or '—')} · {html.escape(v.source)}\n"
        f"💰 {html.escape(f.salary_text)}{sal_note}\n"
        f"🎯 Соответствие: <b>{m.score}/100</b>\n"
        f"✅ {html.escape(m.reasons)}\n"
    )
    if m.missing:
        text += f"➖ Не хватает: {html.escape(m.missing)}\n"
    return text + f'<a href="{html.escape(v.url, quote=True)}">Открыть вакансию</a>'


async def search_and_send(app: Application, chat_id: int, verbose: bool = False):
    lock = _locks.setdefault(chat_id, asyncio.Lock())
    if lock.locked():
        if verbose:
            await app.bot.send_message(chat_id, "Поиск уже идёт, подождите.")
        return
    async with lock:
        try:
            report = await pipeline.run_for_user(storage, chat_id)
        except Exception as e:
            log.exception("search failed for %s", chat_id)
            if verbose:
                await app.bot.send_message(chat_id, f"Ошибка поиска: {e}")
            return
        for f in report.found:
            try:
                await app.bot.send_message(chat_id, format_found(f), parse_mode=ParseMode.HTML,
                                           link_preview_options=NO_PREVIEW)
                storage.mark_seen(chat_id, f.vacancy.key, f.match.score, sent=True)
            except Exception:
                log.exception("send failed")
            await asyncio.sleep(0.5)  # не упираемся в лимиты Telegram
        if verbose or report.errors:
            summary = (f"Готово. Найдено на сайтах: {report.fetched}, новых: {report.new}, "
                       f"оценено: {report.evaluated}, отсеяно по зарплате: {report.skipped_salary}, "
                       f"подходящих: {len(report.found)}.")
            if report.errors:
                summary += "\nНе ответили: " + ", ".join(report.errors)
            if report.new > report.evaluated + report.skipped_salary:
                summary += "\nОстальные новые вакансии оценю в следующий прогон."
            await app.bot.send_message(chat_id, summary)


async def scheduled_job(context: ContextTypes.DEFAULT_TYPE):
    for chat_id in storage.active_users():
        await search_and_send(context.application, chat_id)


async def refresh_rates_job(context: ContextTypes.DEFAULT_TYPE):
    await salary.refresh_rates()


async def post_init(app: Application):
    await salary.refresh_rates()
    app.job_queue.run_repeating(scheduled_job, interval=config.check_interval_hours * 3600, first=60)
    app.job_queue.run_repeating(refresh_rates_job, interval=24 * 3600, first=24 * 3600)


def build_app() -> Application:
    if not config.telegram_token:
        raise SystemExit("Не задан TELEGRAM_BOT_TOKEN (см. .env.example)")
    app = (Application.builder().token(config.telegram_token)
           .concurrent_updates(True).post_init(post_init).build())
    for name, fn in [
        ("start", cmd_start), ("help", cmd_start), ("cv", cmd_cv), ("salary", cmd_salary),
        ("nosalary", cmd_nosalary), ("remote", cmd_remote), ("queries", cmd_queries),
        ("prefs", cmd_prefs), ("minscore", cmd_minscore), ("area", cmd_area),
        ("sources", cmd_sources), ("settings", cmd_settings), ("pause", cmd_pause),
        ("resume", cmd_resume), ("reset_seen", cmd_reset_seen), ("search", cmd_search),
    ]:
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app


def main():
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    build_app().run_polling()


if __name__ == "__main__":
    main()
