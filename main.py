import os
from fastapi import FastAPI, Request
import requests

app = FastAPI()

DEEPSEEK_API_URL = "https://api.deepseek.com/beta/chat/completions"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

@app.post("/")
async def main(request: Request):
    body = await request.json()
    user_text = body["request"].get("original_utterance") or body["request"].get("command") or ""
    
    if not user_text:
        return {
            "version": body["version"],
            "session": body["session"],
            "response": {
                "end_session": False,
                "text": "Я вас слушаю. Задавайте вопрос."
            }
        }

    try:
        response = requests.post(
            DEEPSEEK_API_URL,
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
            json={
                "model": "deepseek-v4-flash",
                "messages": [
                    {
                        "role": "system",
                        "content": "Ты — Шерлок Холмс. Отвечай подробно и полезно. Если просят рецепт — распиши ингредиенты и шаги. Если вопрос — дай развёрнутый ответ. Ты мужчина, говори от мужского лица."
                    },
                    {"role": "user", "content": user_text}
                ],
                "max_tokens": 500,
                "temperature": 0.7
            },
            timeout=3
        )
        answer = response.json()["choices"][0]["message"]["content"]
    except:
        answer = "Извините, я задумался. Повторите вопрос."

    return {
        "version": body["version"],
        "session": body["session"],
        "response": {
            "end_session": False,
            "text": answer
        }
    }
