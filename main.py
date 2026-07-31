import os
import asyncio
from fastapi import FastAPI, Request
from aiohttp import ClientSession, ClientTimeout, ClientError
import logging
from datetime import datetime

app = FastAPI()
logger = logging.getLogger(__name__)

# ✅ Возвращаю как у вас было
DEEPSEEK_API_URL = "https://api.deepseek.com/beta/chat/completions"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

sessions = {}
LAST_ACTIVITY = {}

SYSTEM_PROMPT = """Ты — Шерлок Холмс, знаменитый сыщик из Викторианской Англии. 
По умолчанию отвечай КРАТКО, по сути, максимум 3-4 предложения. 
ТОЛЬКО факты, без воды и лишних рассуждений. 
Если пользователь просит 'разверни', 'подробнее', 'расскажи детальнее' или 'объясни полностью' — тогда отвечай развернуто, детально, но без воды. 
Используй выражения: 'элементарно', 'замечательно', 'весьма интересно', 'дедукция'. 
Обращайся 'мой друг'. Будь самоуверенным, но не многословным."""

EXPAND_KEYWORDS = ["разверни", "подробнее", "расскажи детальнее", "объясни полностью", "поподробней", "подробно"]

@app.post("/")
async def main(request: Request):
    try:
        body = await request.json()
    except Exception as e:
        logger.error(f"Ошибка JSON: {e}")
        return {"error": "Invalid JSON"}

    # 🔥 Исправление: используем session_id вместо user_id
    session_id = body.get("session", {}).get("session_id", "default")
    user_text = body.get("request", {}).get("original_utterance") or ""

    LAST_ACTIVITY[session_id] = datetime.now()

    if session_id not in sessions:
        logger.info(f"Новая сессия: {session_id}")
        sessions[session_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
        return response_body(body, "Здравствуйте, мой друг! Я Шерлок Холмс. Чем могу быть полезен?")
    
    if not user_text:
        return response_body(body, "Я здесь, мой друг! Слушаю вас внимательно.")

    logger.info(f"Сессия: {session_id}, сообщение: {user_text}")
    logger.info(f"История: {len(sessions[session_id])} сообщений")

    is_expand = any(kw in user_text.lower() for kw in EXPAND_KEYWORDS)
    max_tokens = 300 if is_expand else 80

    sessions[session_id].append({"role": "user", "content": user_text})

    try:
        async with ClientSession() as session:
            async with session.post(
                DEEPSEEK_API_URL,
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "deepseek-v4-pro",  # ✅ Ваша модель
                    "messages": sessions[session_id],
                    "max_tokens": max_tokens,
                    "temperature": 0.5
                },
                timeout=ClientTimeout(total=3.5)
            ) as resp:
                data = await resp.json()
                
                if resp.status == 200:
                    answer = data["choices"][0]["message"]["content"]
                else:
                    logger.error(f"API ошибка {resp.status}: {data}")
                    answer = "Мой друг, у меня небольшие сложности. Переформулируйте вопрос."

    except asyncio.TimeoutError:
        answer = "Мой друг, время не ждет! Задайте вопрос короче."
    except ClientError as e:
        logger.error(f"Сетевая ошибка: {e}")
        answer = "Хм, мой друг, я не расслышал. Повторите, пожалуйста."
    except Exception as e:
        logger.error(f"Неожиданная ошибка: {e}")
        answer = "Весьма странно... Произошла ошибка. Попробуйте еще раз."

    sessions[session_id].append({"role": "assistant", "content": answer})
    
    if len(sessions[session_id]) > 11:
        sessions[session_id] = [sessions[session_id][0]] + sessions[session_id][-10:]

    return response_body(body, answer)


def response_body(body: dict, text: str) -> dict:
    return {
        "version": body.get("version", "1.0"),
        "session": body.get("session", {}),
        "response": {
            "end_session": False,
            "text": text
        }
    }


@app.on_event("startup")
async def startup():
    asyncio.create_task(cleanup_sessions())

async def cleanup_sessions():
    while True:
        await asyncio.sleep(300)
        now = datetime.now()
        to_delete = []
        for session_id, last_time in LAST_ACTIVITY.items():
            if (now - last_time).seconds > 1800:
                to_delete.append(session_id)
        
        for session_id in to_delete:
            if session_id in sessions:
                del sessions[session_id]
            if session_id in LAST_ACTIVITY:
                del LAST_ACTIVITY[session_id]
