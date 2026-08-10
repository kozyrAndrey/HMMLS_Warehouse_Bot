import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from config import (
    LAMODA_CANCELLATION_EMAIL_TO,
    LAMODA_EMAIL_APP_PASSWORD,
    LAMODA_EMAIL_FROM,
    LAMODA_EMAIL_SMTP_HOST,
    LAMODA_EMAIL_SMTP_PORT,
    LAMODA_EMAIL_USERNAME,
)


SHIPMENT = "SHIPMENT"
RETURNS = "RETURNS"
OUTBOUND_ACTIVE_STATUSES = {
    "NEW",
    "NEW_TO_BE_CONFIRMED",
    "CONFIRMED",
    "CREATED",
    "PENDING",
    "READY_FOR_ASSEMBLY",
    "AWAITING_SHIPMENT",
    "READY_FOR_SHIPMENT",
}


def normalize_status(value):
    return re.sub(r"[^A-Z0-9]+", "_", str(value or "").strip().upper()).strip("_")


def count_outbound_orders(orders):
    return sum(
        normalize_status(order.get("status")) in OUTBOUND_ACTIVE_STATUSES
        for order in orders or []
    )


def count_ready_returns(return_items):
    return sum(
        normalize_status(item.get("status")) == "READY_TO_RETURN"
        for item in return_items or []
    )


def cancellation_email(service_type, service_date):
    date_text = service_date.strftime("%d.%m.%Y")
    if service_type == SHIPMENT:
        subject = f"Отмена забора отгрузки на {date_text}"
        reason = "отсутствием заказов для отгрузки"
        object_text = "подачу автомобиля для забора отгрузки"
    elif service_type == RETURNS:
        subject = f"Отмена забора возвратов на {date_text}"
        reason = "отсутствием товаров, готовых к возврату"
        object_text = "подачу автомобиля для забора возвратов"
    else:
        raise ValueError(f"Неизвестный тип отмены: {service_type}")

    body = (
        "Добрый день!\n\n"
        f"В связи с {reason} просим отменить {object_text} {date_text}.\n\n"
        "С уважением,\n"
        "HMMLS"
    )
    return subject, body


def email_recipients(value=LAMODA_CANCELLATION_EMAIL_TO):
    return [part.strip() for part in re.split(r"[;,]", str(value or "")) if part.strip()]


def validate_email_configuration():
    missing = []
    values = {
        "LAMODA_CANCELLATION_EMAIL_TO": email_recipients(),
        "LAMODA_EMAIL_FROM": LAMODA_EMAIL_FROM,
        "LAMODA_EMAIL_SMTP_HOST": LAMODA_EMAIL_SMTP_HOST,
        "LAMODA_EMAIL_USERNAME": LAMODA_EMAIL_USERNAME,
        "LAMODA_EMAIL_APP_PASSWORD": LAMODA_EMAIL_APP_PASSWORD,
    }
    for name, value in values.items():
        if not value:
            missing.append(name)
    if missing:
        raise RuntimeError("Не настроена почтовая отправка: " + ", ".join(missing))


def send_cancellation_email(service_type, service_date):
    validate_email_configuration()
    subject, body = cancellation_email(service_type, service_date)
    recipients = email_recipients()
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = LAMODA_EMAIL_FROM
    message["To"] = ", ".join(recipients)
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=LAMODA_EMAIL_FROM.rsplit("@", 1)[-1])
    message.set_content(body)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(
        LAMODA_EMAIL_SMTP_HOST,
        int(LAMODA_EMAIL_SMTP_PORT),
        timeout=30,
        context=context,
    ) as smtp:
        smtp.login(LAMODA_EMAIL_USERNAME, LAMODA_EMAIL_APP_PASSWORD)
        smtp.send_message(message, from_addr=LAMODA_EMAIL_FROM, to_addrs=recipients)
    return {"subject": subject, "recipients": recipients, "message_id": message["Message-ID"]}
