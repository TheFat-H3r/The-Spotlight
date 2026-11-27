import logging
import re
import threading
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def format_chat_id(phone_number: str) -> str:
    """
    Normalizes a phone number into WAHA's '<digits>@c.us' format.
    Assumes Mauritius (+230) if an 8-digit local mobile number is passed.
    """
    digits = re.sub(r"\D", "", str(phone_number or ""))
    if len(digits) == 8 and digits.startswith("5"):
        digits = f"230{digits}"
    return f"{digits}@c.us"


def send_whatsapp_message(phone_number: str, text: str) -> dict:
    if not phone_number:
        return {"ok": False, "error": "Missing recipient phone number"}

    url = f"{settings.WAHA_BASE_URL.rstrip('/')}/api/sendText"
    headers = {
        "Content-Type": "application/json",
        "X-Api-Key": settings.WAHA_API_KEY,
    }
    payload = {
        "session": settings.WAHA_SESSION,
        "chatId": format_chat_id(phone_number),
        "text": text,
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        if not response.ok:
            logger.error("WAHA error %s: %s", response.status_code, response.text)
            return {"ok": False, "status": response.status_code, "error": response.text}
        return {"ok": True, "data": response.json()}
    except requests.RequestException as exc:
        logger.exception("WAHA connection failed")
        return {"ok": False, "error": str(exc)}


def send_whatsapp_async(phone_number: str, text: str) -> None:
    """Fires send_whatsapp_message in a daemon thread so views return immediately."""
    thread = threading.Thread(
        target=send_whatsapp_message,
        args=(phone_number, text),
        daemon=True,
    )
    thread.start()