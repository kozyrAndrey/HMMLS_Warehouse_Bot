import asyncio
import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import (
    LAMODA_CANCELLATION_EMAIL_TO,
    LAMODA_CANCELLATION_TIME,
    LAMODA_REMINDER_TIME,
    LAMODA_SYNC_INTERVAL_MINUTES,
)
from modules.employees.roles import has_any_role
from modules.lamoda_fbs.email_cancellations import (
    RETURNS,
    SHIPMENT,
    cancellation_email,
    count_outbound_orders,
    count_ready_returns,
    send_cancellation_email,
)
from modules.lamoda_fbs.services import get_client, sync_lamoda_statuses
from modules.lamoda_fbs.storage import (
    claim_cancellation_notice,
    finish_cancellation_notice,
    pending_counts,
)
from modules.payroll.google_sheets import get_employees
from modules.tasks.storage import get_warehouse_managers


logger = logging.getLogger(__name__)
MSK = ZoneInfo("Europe/Moscow")
CANCELLATION_DAYS = (0, 2, 4)  # Sunday, Tuesday, Thursday in python-telegram-bot.


async def lamoda_sync_job(context: ContextTypes.DEFAULT_TYPE):
    client = get_client()
    if not client.configured:
        return
    try:
        result = await sync_lamoda_statuses(client)
        logger.info("Lamoda sync complete: %s", result)
    except Exception:
        logger.exception("Lamoda periodic sync failed")


async def lamoda_marking_reminder_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        counts = pending_counts()
        withdrawal = counts.get("WAITING_WITHDRAWAL", 0)
        reintro = counts.get("WAITING_REINTRODUCTION", 0)
        expected = counts.get("RETURN_EXPECTED", 0)
        problems = counts.get("NEEDS_RECONCILIATION", 0)
        if not any((withdrawal, reintro, expected, problems)):
            return
        text = (
            "⚠️ Операции ЧЗ Lamoda\n\n"
            f"На вывод из оборота: {withdrawal}\n"
            f"На возврат в оборот: {reintro}\n"
            f"Ожидаются физически: {expected}\n"
            f"Проблемные операции: {problems}"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏷 Открыть операции ЧЗ", callback_data="lamoda:marking")],
            [InlineKeyboardButton("🛒 Lamoda FBS", callback_data="section:lamoda")],
        ])
        for manager in get_warehouse_managers():
            user_id = str(manager.get("telegram_user_id") or "").strip()
            if not user_id:
                continue
            try:
                await context.bot.send_message(chat_id=int(user_id), text=text, reply_markup=keyboard)
            except Exception:
                logger.exception("Could not send Lamoda reminder to manager_id=%s", user_id)
    except Exception:
        logger.exception("Lamoda marking reminder failed")


def _cancellation_managers():
    result = []
    seen = set()
    for employee in get_employees(include_inactive=False):
        user_id = str(employee.get("telegram_user_id") or "").strip()
        if not user_id or user_id in seen:
            continue
        if not has_any_role(employee, {"warehouse_manager", "brand_manager"}):
            continue
        seen.add(user_id)
        result.append(employee)
    return result


async def _notify_cancellation_managers(context, text):
    for manager in _cancellation_managers():
        try:
            await context.bot.send_message(
                chat_id=int(manager["telegram_user_id"]),
                text=text,
            )
        except Exception:
            logger.exception(
                "Could not send cancellation notification to manager_id=%s",
                manager.get("telegram_user_id"),
            )


def _service_label(service_type):
    return "отгрузки" if service_type == SHIPMENT else "возвратов"


async def lamoda_cancellation_job(context: ContextTypes.DEFAULT_TYPE):
    service_date = datetime.now(MSK).date() + timedelta(days=1)
    client = get_client()
    try:
        orders = await client.list_orders(
            sellerId=client.seller_id,
            fulfillmentType="FBS",
        )
        return_items = await client.list_return_items(sellerId=client.seller_id)
    except Exception as error:
        logger.exception("Lamoda cancellation check failed")
        await _notify_cancellation_managers(
            context,
            "⚠️ Не удалось проверить отмену машин Lamoda на "
            f"{service_date.strftime('%d.%m.%Y')}. Письма не отправлены.\nОшибка: {error}",
        )
        return

    checks = (
        (SHIPMENT, count_outbound_orders(orders)),
        (RETURNS, count_ready_returns(return_items)),
    )
    for service_type, count in checks:
        if count:
            logger.info(
                "Lamoda cancellation skipped: service=%s date=%s count=%s",
                service_type,
                service_date,
                count,
            )
            continue

        subject, _ = cancellation_email(service_type, service_date)
        if not claim_cancellation_notice(
            service_type,
            service_date,
            LAMODA_CANCELLATION_EMAIL_TO,
            subject,
        ):
            logger.info(
                "Lamoda cancellation email already claimed: service=%s date=%s",
                service_type,
                service_date,
            )
            continue
        try:
            result = await asyncio.to_thread(
                send_cancellation_email,
                service_type,
                service_date,
            )
        except Exception as error:
            finish_cancellation_notice(
                service_type,
                service_date,
                "FAILED",
                error=str(error),
            )
            logger.exception(
                "Lamoda cancellation email failed: service=%s date=%s",
                service_type,
                service_date,
            )
            await _notify_cancellation_managers(
                context,
                f"⚠️ Не удалось отправить письмо об отмене забора {_service_label(service_type)} "
                f"на {service_date.strftime('%d.%m.%Y')}.\nОшибка: {error}",
            )
            continue

        finish_cancellation_notice(
            service_type,
            service_date,
            "SENT",
            message_id=result["message_id"],
        )
        await _notify_cancellation_managers(
            context,
            f"✅ Письмо об отмене забора {_service_label(service_type)} отправлено.\n"
            f"Дата машины: {service_date.strftime('%d.%m.%Y')}\n"
            f"Получатель: {', '.join(result['recipients'])}\n"
            f"Тема: {result['subject']}",
        )


def _reminder_time():
    try:
        hour_text, minute_text = str(LAMODA_REMINDER_TIME).split(":", 1)
        return time(hour=int(hour_text), minute=int(minute_text), tzinfo=MSK)
    except (TypeError, ValueError):
        logger.warning("Invalid LAMODA_REMINDER_TIME=%r; using 10:00", LAMODA_REMINDER_TIME)
        return time(hour=10, minute=0, tzinfo=MSK)


def _cancellation_time():
    try:
        hour_text, minute_text = str(LAMODA_CANCELLATION_TIME).split(":", 1)
        return time(hour=int(hour_text), minute=int(minute_text), tzinfo=MSK)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid LAMODA_CANCELLATION_TIME=%r; using 14:55",
            LAMODA_CANCELLATION_TIME,
        )
        return time(hour=14, minute=55, tzinfo=MSK)


def setup_lamoda_jobs(app):
    if not app.job_queue:
        logger.warning("JobQueue is unavailable; Lamoda jobs are disabled")
        return
    interval = max(int(LAMODA_SYNC_INTERVAL_MINUTES or 10), 1) * 60
    if not app.job_queue.get_jobs_by_name("lamoda_status_sync"):
        app.job_queue.run_repeating(
            lamoda_sync_job, interval=interval, first=30,
            name="lamoda_status_sync",
        )
    if not app.job_queue.get_jobs_by_name("lamoda_marking_reminder"):
        app.job_queue.run_daily(
            lamoda_marking_reminder_job, time=_reminder_time(),
            name="lamoda_marking_reminder",
        )
    if not app.job_queue.get_jobs_by_name("lamoda_cancellation_email"):
        app.job_queue.run_daily(
            lamoda_cancellation_job,
            time=_cancellation_time(),
            days=CANCELLATION_DAYS,
            name="lamoda_cancellation_email",
        )
