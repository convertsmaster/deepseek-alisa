import os
import time
import asyncio
import logging
from contextlib import asynccontextmanager

import aiohttp
from fastapi import FastAPI, Request

# ===========================
# ЛОГИ
# ===========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)

# ===========================
# НАСТРОЙКИ
# ===========================

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

if not DEEPSEEK_API_KEY:
    raise RuntimeError("DEEPSEEK_API_KEY не найден.")

DEEPSEEK_API_URL = "https://api.deepseek.com/beta/chat/completions"

MODEL = "deepseek-v4-flash"

TIMEOUT = 4.2

MAX_HISTORY = 10

SESSION_LIFETIME = 3600

SYSTEM_PROMPT = (
    "Ты — Шерлок Холмс, знаменитый сыщик из Викторианской Англии. "
    "По умолчанию отвечай КРАТКО, максимум 3 предложения. "
    "Если пользователь просит подробно — отвечай подробно. "
    "Используй выражения 'элементарно', 'дедукция', "
    "'мой друг', но не злоупотребляй ими."
)

# ===========================
# ПАМЯТЬ
# ===========================

sessions = {}

# ===========================
# FASTAPI
# ===========================

@asynccontextmanager
async def lifespan(app: FastAPI):

    timeout = aiohttp.ClientTimeout(total=TIMEOUT)

    connector = aiohttp.TCPConnector(
        limit=100,
        limit_per_host=20,
        ttl_dns_cache=300
    )

    app.state.http = aiohttp.ClientSession(
        timeout=timeout,
        connector=connector,
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
    )

    logger.info("HTTP Client создан.")

    yield

    logger.info("Закрываем HTTP Client...")

    await app.state.http.close()


app = FastAPI(lifespan=lifespan)

# ===========================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ===========================

def cleanup_sessions():

    now = time.time()

    expired = [
        uid
        for uid, data in sessions.items()
        if now - data["last_seen"] > SESSION_LIFETIME
    ]

    for uid in expired:
        del sessions[uid]

    if expired:
        logger.info(f"Удалено старых сессий: {len(expired)}")


def get_session(user_id):

    if user_id not in sessions:

        sessions[user_id] = {
            "last_seen": time.time(),
            "messages": [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT
                }
            ]
        }

    sessions[user_id]["last_seen"] = time.time()

    return sessions[user_id]
@app.post("/")
async def main(request: Request):

    cleanup_sessions()

    body = await request.json()

    logger.info("Запрос от Алисы")

    session_data = body.get("session", {})

    # Используем user_id если есть, иначе application_id, иначе default
    user_id = (
        session_data.get("user", {}).get("user_id")
        or session_data.get("application", {}).get("application_id")
        or session_data.get("user_id")
        or "default"
    )

    req = body.get("request", {})

    user_text = (
        req.get("original_utterance")
        or req.get("command")
        or ""
    ).strip()

    logger.info(f"USER [{user_id}] -> {user_text}")

    # Первый запуск навыка
    if not user_text:

        return {
            "version": body.get("version", "1.0"),
            "session": session_data,
            "response": {
                "end_session": False,
                "text": "Здравствуйте, мой друг. Я Шерлок Холмс. Чем могу помочь?"
            }
        }

    dialog = get_session(user_id)

    expand = any(
        word in user_text.lower()
        for word in (
            "подробно",
            "разверни",
            "расскажи подробнее",
            "детальнее",
            "объясни полностью",
            "поподробнее",
        )
    )

    max_tokens = 220 if expand else 80

    dialog["messages"].append(
        {
            "role": "user",
            "content": user_text
        }
    )

    # Ограничиваем историю
    if len(dialog["messages"]) > MAX_HISTORY + 1:
        dialog["messages"] = (
            [dialog["messages"][0]]
            + dialog["messages"][-MAX_HISTORY:]
        )

    payload = {
        "model": MODEL,
        "messages": dialog["messages"],
        "temperature": 0.4,
        "max_tokens": max_tokens
    }

    started = time.perf_counter()

    try:

        async with app.state.http.post(
            DEEPSEEK_API_URL,
            json=payload
        ) as resp:

            elapsed = round(time.perf_counter() - started, 2)

            logger.info(f"DeepSeek status = {resp.status}")
            logger.info(f"Latency = {elapsed} sec")

            if resp.status != 200:

                error_text = await resp.text()

                logger.error(error_text)

                answer = (
                    "Мой друг, сейчас я не могу получить сведения. "
                    "Попробуйте немного позже."
                )

            else:

                data = await resp.json()

                logger.info("DeepSeek ответ получен")

                choices = data.get("choices")

                if not choices:

                    raise RuntimeError(
                        f"Пустой ответ DeepSeek: {data}"
                    )

                answer = choices[0]["message"]["content"].strip()

    except asyncio.TimeoutError:

        logger.warning("TIMEOUT")

        answer = (
            "Мой друг, расследование заняло слишком много времени. "
            "Попробуйте задать вопрос немного короче."
        )

    except Exception:

        logger.exception("Ошибка")

        answer = (
            "Хм... Похоже, произошла ошибка. "
            "Попробуйте повторить вопрос."
        )

    # Алисе длинные ответы не нужны
    answer = answer[:900]

    dialog["messages"].append(
        {
            "role": "assistant",
            "content": answer
        }
    )

    logger.info(f"BOT -> {answer}")

    return {
        "version": body.get("version", "1.0"),
        "session": session_data,
        "response": {
            "end_session": False,
            "text": answer
        }
    }
