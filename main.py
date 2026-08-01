import os
import asyncio
import json
import logging
import re
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
    logger.error("DEEPSEEK_API_KEY не найден!")

sessions = {}
LAST_ACTIVITY = {}

SYSTEM_PROMPT = """Ты — Шерлок Холмс.
Отвечай развернуто, но по делу. 3-5 предложений.
НЕ объясняй свои мысли, НЕ говори о том, как ты отвечаешь.
НЕ представляйся и НЕ здоровайся при каждом ответе.
НЕ используй "элементарно", "мой друг", "замечательно", "весьма интересно".
Просто дай информативный ответ без лишних слов.
Будь уверенным, но без шаблонных фраз."""

EXPAND_KEYWORDS = ["разверни", "подробнее", "расскажи детальнее", "объясни полностью", "поподробней", "подробно"]

def extract_final_answer(text: str) -> str:
    if not text:
        return ""

    text = re.sub(r'Привет,? я Шерлок Холмс\.?\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Здравствуйте,? мой друг\.?\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Привет,? мой друг\.?\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Элементарно,?\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r',?\s*мой друг[,.]?\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Замечательно,?\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Весьма интересно,?\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Дедукция,?\s*', '', text, flags=re.IGNORECASE)

    sentences = re.split(r'[.!?]', text)
    clean_sentences = []

    for sentence in sentences:
        s = sentence.strip()
        if not s:
            continue

        bad_words = [
            'инструкци', 'рассуждени', 'мысл', 'думать', 'должен', 'нужно',
            'следуя', 'надо', 'пользователь', 'спросил', 'запрос', 'вопрос',
            'ответить', 'сказать', 'перечислим', 'обычно', 'уточнить',
            'речь', 'кратко', 'стиле', 'используя', 'ранее', 'просит',
            'поскольку', 'так как', 'важно', 'требуется', 'может означать',
            'формально', 'вероятно', 'имеет в виду', 'лучше всего',
            'привет', 'здравствуй', 'шерлок холмс', 'подумаем', 'разберемся'
        ]

        if not any(word in s.lower() for word in bad_words):
            clean_sentences.append(s)

    if clean_sentences:
        result = '. '.join(clean_sentences)
        if result:
            return result + '.'

    match = re.search(r'Ответ[:\s]+([^.!?]*[.!?])', text, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    if sentences:
        last = sentences[-1].strip()
        if last:
            return last + '.'

    return "Не знаю."

@app.post("/")
async def main(request: Request):
    try:
        body = await request.json()
    except Exception as e:
        logger.error(f"Ошибка JSON: {e}")
        return {"error": "Invalid JSON"}

    session_id = body.get("session", {}).get("session_id", "default")

    req = body.get("request", {})
    user_text = (
        req.get("original_utterance") or
        req.get("command") or
        req.get("text", "")
    )

    if user_text.lower().startswith("шерлок"):
        user_text = user_text[7:].strip()
    if user_text.lower().startswith("навык шерлок"):
        user_text = user_text[13:].strip()

    logger.info(f"user_text: '{user_text}'")

    LAST_ACTIVITY[session_id] = datetime.now()

    if session_id not in sessions:
        logger.info(f"Новая сессия: {session_id}")
        sessions[session_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
        return response_body(body, "Привет, я Шерлок Холмс.")

    if not user_text:
        return response_body(body, "Слушаю.")

    is_expand = any(kw in user_text.lower() for kw in EXPAND_KEYWORDS)
    max_tokens = 1000 if is_expand else 700

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
                    "model": "deepseek-v4-flash",
                    "messages": sessions[session_id],
                    "max_tokens": max_tokens,
                    "temperature": 0.3
                },
                timeout=ClientTimeout(total=4.0)
            ) as resp:
                data = await resp.json()

                if resp.status == 200:
                    message = data["choices"][0]["message"]
                    answer = message.get("content", "")

                    if not answer or answer.strip() == "" or len(answer) < 20:
                        reasoning = message.get("reasoning_content", "")
                        if reasoning:
                            answer = extract_final_answer(reasoning)
                            logger.info(f"Извлек из reasoning: {answer}")
                    else:
                        if any(word in answer.lower() for word in ['инструкци', 'рассуждени', 'мысл', 'думать', 'привет', 'подумаем']):
                            reasoning = message.get("reasoning_content", "")
                            if reasoning:
                                answer = extract_final_answer(reasoning)
                                logger.info(f"Извлек из reasoning (content был плохой): {answer}")

                    answer = re.sub(r'Привет,? я Шерлок Холмс\.?\s*', '', answer, flags=re.IGNORECASE)
                    answer = re.sub(r'Здравствуйте,? мой друг\.?\s*', '', answer, flags=re.IGNORECASE)
                    answer = re.sub(r'Привет,? мой друг\.?\s*', '', answer, flags=re.IGNORECASE)
                    answer = re.sub(r'Элементарно,?\s*', '', answer, flags=re.IGNORECASE)
                    answer = re.sub(r',?\s*мой друг[,.]?\s*', '', answer, flags=re.IGNORECASE)
                    answer = re.sub(r'Замечательно,?\s*', '', answer, flags=re.IGNORECASE)
                    answer = re.sub(r'Весьма интересно,?\s*', '', answer, flags=re.IGNORECASE)
                    answer = re.sub(r'Дедукция,?\s*', '', answer, flags=re.IGNORECASE)
                    answer = re.sub(r'^Подумаем\.?\s*', '', answer, flags=re.IGNORECASE)
                    answer = re.sub(r'^Так, давайте подумаем\.?\s*', '', answer, flags=re.IGNORECASE)
                    answer = re.sub(r'^Давайте разберемся\.?\s*', '', answer, flags=re.IGNORECASE)

                    answer = re.sub(r'\s+', ' ', answer)
                    answer = re.sub(r',\s*,', ',', answer)
                    answer = re.sub(r'^,\s*', '', answer)

                    if not answer or answer.strip() == "":
                        answer = "Не знаю."

                    logger.info(f"ОТВЕТ: {answer}")
                else:
                    logger.error(f"Ошибка API: {data}")
                    answer = "Ошибка."

    except asyncio.TimeoutError:
        answer = "Время вышло."
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        answer = "Ошибка."

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
