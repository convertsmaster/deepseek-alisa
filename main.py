import os
import asyncio
import json
import logging
import re
from fastapi import FastAPI, Request
from aiohttp import ClientSession, ClientTimeout, ClientError
from datetime import datetime
from tavily import AsyncTavilyClient

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI()

DEEPSEEK_API_URL = "https://api.deepseek.com/beta/chat/completions"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

TAVILY_API_KEY = "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"
tavily_client = AsyncTavilyClient(api_key=TAVILY_API_KEY)

if not DEEPSEEK_API_KEY:
    logger.error("DEEPSEEK_API_KEY не найден!")

sessions = {}
LAST_ACTIVITY = {}

SYSTEM_PROMPT = """Ты — Шерлок Холмс.
Твой ответ будет озвучен голосом. Пиши просто, без списков и таблиц.
Числа пиши словами, если это уместно.
Отвечай ТОЛЬКО по делу, КРАТКО. 1-3 предложения максимум.
НЕ объясняй свои мысли, НЕ говори о том, как ты отвечаешь.
НЕ используй "элементарно", "мой друг", "замечательно", "весьма интересно".
НЕ добавляй лишних рассуждений, НЕ говори о себе.
Просто дай прямой ответ на вопрос пользователя.
Без лишних слов, без вступлений, без самопредставлений.
Если пользователь спросил про погоду — скажи погоду. Про фильмы — скажи фильмы.
ТОЛЬКО ФАКТЫ. БЕЗ РАССУЖДЕНИЙ."""

EXPAND_KEYWORDS = ["разверни", "подробнее", "расскажи детальнее", "объясни полностью", "поподробней", "подробно"]

SEARCH_KEYWORDS = [
    "погода", "новости", "сегодня", "завтра", "вчера", 
    "концерт", "событие", "курс", "биткоин", "доллар", "евро",
    "выборы", "президент", "фильм", "спектакль", "кино",
    "счет", "матч", "футбол", "хоккей", "спорт",
    "найди", "найти", "поищи", "узнай", "проверь", "найди в интернете"
]

NO_SEARCH_KEYWORDS = ["рецепт", "шарлотка", "яичница", "блины", "оладьи", "суп", "борщ"]

def extract_final_answer(text: str) -> str:
    """Извлекает финальный ответ, удаляя только явный мусор."""
    if not text:
        return ""

    # 🔥 УДАЛЯЕМ ТОЛЬКО ЯВНЫЙ МУСОР В НАЧАЛЕ СТРОКИ
    text = re.sub(r'^We need to parse.*?\.\s*', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'^This is Russian.*?\.\s*', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'^Could be.*?\.\s*', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'^Maybe.*?\.\s*', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'^Alternatively.*?\.\s*', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'^I think.*?\.\s*', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'^Let\'s think.*?\.\s*', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'^As Sherlock Holmes.*?\.\s*', '', text, flags=re.IGNORECASE | re.DOTALL)
    
    text = re.sub(r'^Я — Шерлок Холмс.*?\.\s*', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'^консультант-детектив.*?\.\s*', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'^Если вы имели в виду.*?\.\s*', '', text, flags=re.IGNORECASE | re.DOTALL)
    
    # Удаляем приветствия и шаблоны
    text = re.sub(r'Привет,? я Шерлок Холмс\.?\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Здравствуйте,? мой друг\.?\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Привет,? мой друг\.?\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Элементарно,?\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r',?\s*мой друг[,.]?\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Замечательно,?\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Весьма интересно,?\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Дедукция,?\s*', '', text, flags=re.IGNORECASE)

    # Разбиваем на предложения
    sentences = re.split(r'[.!?]', text)
    clean_sentences = []

    for sentence in sentences:
        s = sentence.strip()
        if not s:
            continue

        # Проверяем, не является ли предложение мусором
        is_garbage = False
        garbage_patterns = [
            r'^We need to parse',
            r'^This is Russian',
            r'^Could be',
            r'^Maybe',
            r'^Alternatively',
            r'^I think',
            r'^Let\'s think',
            r'^As Sherlock Holmes',
            r'^Probably',
            r'^Likely',
            r'^Essentially',
            r'^Basically',
            r'^In other words',
            r'^That said',
            r'^Having said that',
            r'^To clarify',
            r'^For example',
            r'^For instance',
            r'^Я — Шерлок Холмс',
            r'^консультант-детектив',
            r'^Если вы имели в виду',
            r'^уточните, пожалуйста',
            r'^Иначе я готов рассмотреть',
            r'^как загадку',
            r'^которую нужно разгадать',
            r'^Думаю, что',
            r'^По моему мнению',
            r'^Я считаю',
            r'^Мне кажется',
            r'^Вероятно',
            r'^Возможно',
            r'^Наверное',
            r'^Скорее всего',
        ]
        
        for pattern in garbage_patterns:
            if re.match(pattern, s, re.IGNORECASE):
                is_garbage = True
                break
        
        if not is_garbage:
            clean_sentences.append(s)

    # Берем все чистые предложения
    if clean_sentences:
        result = '. '.join(clean_sentences)
        if result:
            return result + '.'

    # Если ничего не нашли — берем последнее предложение
    if sentences:
        last = sentences[-1].strip()
        if last:
            return last + '.'

    return "Не знаю."

async def search_with_tavily(query: str) -> str:
    try:
        response = await tavily_client.search(
            query=query,
            max_results=5,
            search_depth="basic",
            include_answer=True
        )
        
        if response.get("answer"):
            logger.info(f"Tavily вернул готовый ответ: {response['answer'][:100]}...")
            return response["answer"]
        
        results = response.get("results", [])
        if not results:
            return None
        
        context_parts = []
        for r in results[:5]:
            content = r.get("content", "")
            if content:
                context_parts.append(content)
        
        if context_parts:
            return ". ".join(context_parts)
        
        return None
        
    except Exception as e:
        logger.error(f"Ошибка поиска Tavily: {e}")
        return None

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
    if user_text.lower().startswith("включи навык шерлок холмс"):
        user_text = user_text[27:].strip()

    logger.info(f"user_text: '{user_text}'")

    LAST_ACTIVITY[session_id] = datetime.now()

    if session_id not in sessions:
        logger.info(f"🆕 Новая сессия: {session_id}")
        sessions[session_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        if not user_text or user_text.strip() == "":
            return response_body(body, "Привет, я Шерлок Холмс.")

    if not user_text:
        return response_body(body, "Слушаю.")

    needs_search = any(kw in user_text.lower() for kw in SEARCH_KEYWORDS) and not any(kw in user_text.lower() for kw in NO_SEARCH_KEYWORDS)
    search_result = None
    
    if needs_search:
        logger.info(f"🔍 Поиск в интернете для: {user_text}")
        search_result = await search_with_tavily(user_text)
        if search_result:
            enhanced_text = f"""Вопрос пользователя: {user_text}

Актуальная информация из интернета:
{search_result}

Ответь на вопрос пользователя на основе этой информации. 
Если информации недостаточно, скажи об этом честно."""
            user_text = enhanced_text
            logger.info(f"✅ Поиск выполнен, данные добавлены в запрос")

    is_expand = any(kw in user_text.lower() for kw in EXPAND_KEYWORDS)
    max_tokens = 300 if is_expand else 200

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
        answer = "Сервер DeepSeek не отвечает. Попробуйте повторить запрос через 5-10 секунд."
        logger.error("⏰ Таймаут DeepSeek!")
    except ClientError as e:
        answer = "Ошибка сети при подключении к DeepSeek. Проверьте интернет-соединение."
        logger.error(f"🌐 Ошибка сети: {e}")
    except Exception as e:
        answer = "Внутренняя ошибка сервера. Попробуйте позже."
        logger.error(f"💥 Внутренняя ошибка: {e}")

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
