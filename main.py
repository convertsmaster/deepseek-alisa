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

КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО:
- Объяснять свои мысли.
- Говорить о том, как ты отвечаешь.
- Использовать фразы "я думаю", "мне кажется", "возможно", "наверное".
- Добавлять лишние слова.

ТЫ ДОЛЖЕН:
- Отвечать ТОЛЬКО на вопрос пользователя.
- Давать краткий, полезный ответ (3-5 предложений).
- Использовать факты из поиска, если они есть.
- Говорить прямо и по делу.

ПРИМЕР ПРАВИЛЬНОГО ОТВЕТА:
Вопрос: "какие фильмы сегодня в бресте"
Ответ: "Сегодня в Бресте в кинотеатре Беларусь идут Зверополис 2 и Scar: Hell. Время сеансов уточняйте на сайте кинотеатра."

НЕЛЬЗЯ ОТВЕЧАТЬ ТАК:
"Я подумал, что пользователь спрашивает про фильмы. В Бресте сегодня идут..."
"""

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
    if not text:
        return ""

    garbage_patterns = [
        r'^.*?подумал.*?\.',
        r'^.*?решил.*?\.',
        r'^.*?сказал.*?\.',
        r'^.*?должен.*?\.',
        r'^.*?нужно.*?\.',
        r'^.*?можно.*?\.',
        r'^.*?кстати.*?\.',
        r'^.*?вообще.*?\.',
        r'^.*?наверное.*?\.',
        r'^.*?возможно.*?\.',
        r'^.*?вероятно.*?\.',
        r'^.*?мне кажется.*?\.',
        r'^.*?я думаю.*?\.',
        r'^.*?я считаю.*?\.',
        r'^.*?по моему.*?\.',
        r'^.*?по сути.*?\.',
        r'^.*?фактически.*?\.',
        r'^.*?то есть.*?\.',
        r'^.*?имеется в виду.*?\.',
        r'^.*?в принципе.*?\.',
        r'^.*?если честно.*?\.',
        r'^.*?собственно.*?\.',
        r'^.*?во-первых.*?\.',
        r'^.*?во-вторых.*?\.',
        r'^.*?в-третьих.*?\.',
        r'^.*?кроме того.*?\.',
        r'^.*?более того.*?\.',
        r'^.*?в связи с.*?\.',
        r'^.*?учитывая.*?\.',
        r'^.*?исходя из.*?\.',
        r'^.*?на основании.*?\.',
        r'^.*?следует.*?\.',
        r'^.*?можно сказать.*?\.',
        r'^.*?стоит отметить.*?\.',
        r'^.*?важно подчеркнуть.*?\.',
        r'^.*?следует отметить.*?\.',
        r'^.*?необходимо.*?\.',
        r'^.*?заметим.*?\.',
        r'^.*?отметим.*?\.',
        r'^.*?подчеркнем.*?\.',
        r'^.*?надо сказать.*?\.',
        r'^.*?хочу сказать.*?\.',
        r'^.*?давайте.*?\.',
        r'^.*?давай.*?\.',
        r'^.*?попробуем.*?\.',
        r'^.*?постараюсь.*?\.',
        r'^.*?постараемся.*?\.',
        r'^.*?буду краток.*?\.',
        r'^.*?короче.*?\.',
        r'^.*?вкратце.*?\.',
        r'^.*?если кратко.*?\.',
        r'^.*?в общем.*?\.',
        r'^.*?итак.*?\.',
        r'^.*?ну и.*?\.',
        r'^.*?ладно.*?\.',
        r'^.*?хорошо.*?\.',
        r'^.*?отлично.*?\.',
        r'^.*?прекрасно.*?\.',
        r'^.*?замечательно.*?\.',
        r'^.*?элементарно.*?\.',
        r'^.*?мой друг.*?\.',
        r'^.*?Шерлок Холмс.*?\.',
        r'^.*?консультант-детектив.*?\.',
        r'^.*?я отвечаю.*?\.',
        r'^.*?я здесь.*?\.',
        r'^.*?слушаю.*?\.',
        r'^.*?внимательно.*?\.',
        r'^.*?готов.*?\.',
        r'^.*?рад.*?\.',
        r'^.*?спасибо.*?\.',
        r'^.*?пожалуйста.*?\.',
        r'^.*?обращайтесь.*?\.',
        r'^.*?надеюсь.*?\.',
        r'^.*?желаю.*?\.',
        r'^.*?удачи.*?\.',
        r'^.*?всего.*?\.',
        r'^.*?до свидания.*?\.',
        r'^.*?пока.*?\.',
        r'^.*?до встречи.*?\.',
        r'^.*?навык.*?\.',
        r'^.*?алиса.*?\.',
        r'^.*?яндекс.*?\.',
        r'^.*?дипсик.*?\.',
        r'^.*?депсик.*?\.',
        r'^.*?deepseek.*?\.',
    ]
    
    for pattern in garbage_patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.DOTALL)

    sentences = re.split(r'[.!?]', text)
    useful_sentences = []
    
    for sentence in sentences:
        s = sentence.strip()
        if not s:
            continue
        
        if len(s) < 20:
            continue
        
        bad_markers = [
            'думаю', 'считаю', 'кажется', 'возможно', 'наверное',
            'вероятно', 'подумал', 'решил', 'сказал', 'должен',
            'нужно', 'можно', 'кстати', 'вообще', 'по сути',
            'фактически', 'то есть', 'имеется в виду', 'в принципе',
            'если честно', 'собственно', 'во-первых', 'во-вторых',
            'кроме того', 'более того', 'в связи с', 'учитывая',
            'исходя из', 'на основании', 'следует', 'можно сказать',
            'стоит отметить', 'важно подчеркнуть', 'следует отметить',
            'необходимо', 'заметим', 'отметим', 'подчеркнем',
            'надо сказать', 'хочу сказать', 'давайте', 'давай',
            'попробуем', 'постараюсь', 'постараемся', 'буду краток',
            'короче', 'вкратце', 'если кратко', 'в общем', 'итак',
            'ну и', 'ладно', 'хорошо', 'отлично', 'прекрасно',
            'замечательно', 'элементарно', 'мой друг', 'Шерлок Холмс',
            'консультант-детектив', 'я отвечаю', 'я здесь', 'слушаю',
            'внимательно', 'готов', 'рад', 'спасибо', 'пожалуйста',
            'обращайтесь', 'надеюсь', 'желаю', 'удачи', 'всего',
            'до свидания', 'пока', 'до встречи', 'навык', 'алиса',
            'яндекс', 'дипсик', 'депсик', 'deepseek'
        ]
        
        is_bad = any(marker in s.lower() for marker in bad_markers)
        if not is_bad:
            useful_sentences.append(s)
    
    if useful_sentences:
        return useful_sentences[0] + '.'

    if sentences:
        last = sentences[-1].strip()
        if last and len(last) > 10:
            return last + '.'

    return "Не знаю."

async def search_with_tavily(query: str) -> str:
    try:
        response = await tavily_client.search(
            query=query,
            max_results=3,  # 🔥 ТЕПЕРЬ 3 ВЫДАЧИ (было 5)
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
        for r in results[:3]:  # 🔥 ТОЖЕ БЕРЁМ ТОЛЬКО 3
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
    max_tokens = 500 if is_expand else 350

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
                    "temperature": 0.3,
                    "thinking": {"type": "disabled"}
                },
                timeout=ClientTimeout(total=4.5)
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
                            answer = "Сервер занят. Попробуйте повторить запрос через 5-10 секунд."
                            logger.warning("⚠️ DeepSeek вернул пустой content и пустой reasoning_content")
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
