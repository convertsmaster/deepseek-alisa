import os
import asyncio
from fastapi import FastAPI, Request
import aiohttp

app = FastAPI()

DEEPSEEK_API_URL = "https://api.deepseek.com/beta/chat/completions"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

sessions = {}

@app.post("/")
async def main(request: Request):
    body = await request.json()
    
    user_id = body.get("session", {}).get("user_id", "default")
    
    req = body.get("request", {})
    user_text = req.get("original_utterance") or req.get("command") or ""
    
    if user_id not in sessions:
        sessions[user_id] = [
            {
                "role": "system",
                "content": "Ты — Шерлок Холмс, знаменитый сыщик из Викторианской Англии. По умолчанию отвечай КРАТКО, по сути, максимум 3-4 предложения. ТОЛЬКО факты, без воды и лишних рассуждений. Если пользователь просит 'разверни', 'подробнее', 'расскажи детальнее' или 'объясни полностью' — тогда отвечай развернуто, детально, но без воды. Используй выражения: 'элементарно', 'замечательно', 'весьма интересно', 'дедукция'. Обращайся 'мой друг'. Будь самоуверенным, но не многословным."
            }
        ]
    
    if not user_text:
        return {
            "version": body.get("version", "1.0"),
            "session": body.get("session", {}),
            "response": {
                "end_session": False,
                "text": "Здравствуйте, мой друг! Я Шерлок Холмс. Чем могу быть полезен?"
            }
        }
    
    expand_keywords = ["разверни", "подробнее", "расскажи детальнее", "объясни полностью", "поподробней", "подробно"]
    is_expand_request = any(keyword in user_text.lower() for keyword in expand_keywords)
    max_tokens = 300 if is_expand_request else 80
    
    sessions[user_id].append({"role": "user", "content": user_text})
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                DEEPSEEK_API_URL,
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
                json={
                    "model": "deepseek-v4-pro",
                    "messages": sessions[user_id],
                    "max_tokens": max_tokens,
                    "temperature": 0.5
                },
                timeout=aiohttp.ClientTimeout(total=3.5)
            ) as resp:
                data = await resp.json()
                answer = data["choices"][0]["message"]["content"]
    
    except asyncio.TimeoutError:
        answer = "Мой друг, время не ждет! Задайте вопрос короче, и я отвечу незамедлительно."
    except Exception as e:
        print(f"Ошибка: {e}")
        answer = "Хм, мой друг, боюсь, я не расслышал. Не могли бы вы повторить?"
    
    sessions[user_id].append({"role": "assistant", "content": answer})
    
    if len(sessions[user_id]) > 12:
        sessions[user_id] = [sessions[user_id][0]] + sessions[user_id][-10:]
    
    return {
        "version": body.get("version", "1.0"),
        "session": body.get("session", {}),
        "response": {
            "end_session": False,
            "text": answer
        }
    }
