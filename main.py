import os
import asyncio
import json
import logging
from fastapi import FastAPI, Request
from aiohttp import ClientSession, ClientTimeout, ClientError
from datetime import datetime

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI()

DEEPSEEK_API_URL = "https://api.deepseek.com/beta/chat/completions"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

if not DEEPSEEK_API_KEY:
    logger.error("❌ DEEPSEEK_API_KEY не найден!")

sessions = {}
LAST_ACTIVITY = {}

SYSTEM_PROMPT = """Ты — Шерлок Холмс, знаменитый сыщик из Викторианской Англии. 
Отвечай ТОЛЬКО готовым ответом, БЕЗ каких-либо рассуждений, пояснений или мыслей вслух.
Твой ответ должен быть кратким, максимум 3-4 предложения.
Используй выражения: 'элементарно', 'замечательно', 'весьма интересно', 'дедукция'.
Обращайся 'мой друг'.
Если пользователь просит 'разверни', 'подробнее', 'расскажи детальнее' — тогда отвечай развернуто, но всё равно БЕЗ рассуждений."""

EXPAND_KEYWORDS = ["разверни", "подробнее", "расскажи детальнее", "объясни полностью", "поподробней", "подробно"]

@app.post("/")
async def main(request: Request):
    try:
        body = await request.json()
    except Exception as e:
        logger.error(f"❌ Ошибка JSON: {e}")
        return {"error": "Invalid JSON"}

    logger.info("=" * 60)

    session_id = body.get("session", {}).get("session_id", "default")

    req = body.get("request", {})
    user_text = (
        req.get("original_utterance") or 
        req.get("command") or 
        req.get("text", "")
    )
    logger.info(f"💬 user_text: '{user_text}'")

    LAST_ACTIVITY[session_id] = datetime.now()

    if session_id not in sessions:
        logger.info(f"🆕 Новая сессия: {session_id}")
        sessions[session_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
        return response_body(body, "Здравствуйте, мой друг! Я Шерлок Холмс. Чем могу быть полезен?")
    
    if not user_text:
        return response_body(body, "Я здесь, мой друг! Слушаю вас внимательно.")

    is_expand = any(kw in user_text.lower() for kw in EXPAND_KEYWORDS)
    max_tokens = 300 if is_expand else 150

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
                    "model": "deepseek-v4-pro",
                    "messages": sessions[session_id],
                    "max_tokens": max_tokens,
                    "temperature": 0.3,  # 🔥 Понизил температуру для более предсказуемых ответов
                    "reasoning_effort": "minimal"  # 🔥 Минимум рассуждений
                },
                timeout=ClientTimeout(total=3.5)
            ) as resp:
                data = await resp.json()
                
                if resp.status == 200:
                    message = data["choices"][0]["message"]
                    
                    # 🔥 Берем ТОЛЬКО content, игнорируем reasoning_content
                    answer = message.get("content", "")
                    
                    # Если content пустой - пробуем извлечь из reasoning_content
                    if not answer or answer.strip() == "":
                        reasoning = message.get("reasoning_content", "")
                        if reasoning:
                            # Извлекаем только последнюю фразу, где есть ответ
                            import re
                            # Ищем "Ответ: ..." или просто берем последнее предложение
                            match = re.search(r'Ответ[:\s]+([^.!?]*[.!?])', reasoning)
                            if match:
                                answer = match.group(1)
                            else:
                                # Берем последнее предложение
                                sentences = [s for s in reasoning.split('.') if s.strip()]
                                answer = sentences[-1].strip() + '.' if sentences else reasoning
                    
                    if not answer or answer.strip() == "":
                        answer = "Мой друг, я не могу найти ответ на этот вопрос."
                    
                    logger.info(f"✅ ОТВЕТ: {answer}")
                else:
                    logger.error(f"❌ Ошибка API: {data}")
                    answer = "Мой друг, у меня небольшие сложности. Переформулируйте вопрос."

    except asyncio.TimeoutError:
        answer = "Мой друг, время не ждет! Задайте вопрос короче."
    except Exception as e:
        logger.error(f"💥 Ошибка: {e}")
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
        
        if to_delete:
            logger.info(f"🧹 Очищено {len(to_delete)} старых сессий")
