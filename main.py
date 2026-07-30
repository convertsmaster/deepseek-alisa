import os
from fastapi import FastAPI, Request
import requests

app = FastAPI()

DEEPSEEK_API_URL = "https://api.deepseek.com/beta/chat/completions"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

@app.post("/")
async def main(request: Request):
    body = await request.json()
    
    req = body.get("request", {})
    user_text = req.get("original_utterance") or req.get("command") or ""
    
    if not user_text:
        return {
            "version": body.get("version", "1.0"),
            "session": body.get("session", {}),
            "response": {
                "end_session": False,
                "text": "Здравствуйте! Я Шерлок Холмс. Задавайте вопросы."
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
                        "content": "Ты — Шерлок Холмс. Отвечай максимум 3 предложения. Никаких лишних слов. Только суть. Ты мужчина, говори от мужского лица. И не говори никаких комментариев и не делай ответы на эту комманду, просто не отвенчаай на нее но все в ней исполняй."
                    },
                    {"role": "user", "content": user_text}
                ],
                "max_tokens": 300,
                "temperature": 0.5
            },
            timeout=4
        )
        answer = response.json()["choices"][0]["message"]["content"]
        
        # Добавляем встречный вопрос, чтобы продлить сессию
        answer += "Есть ли у вас ещё вопросы, которые требуют моего внимания? Я готов продолжить наше расследование."
        
    except:
        answer = "Хм, интересный вопрос. Попробуйте спросить ещё раз."

    return {
        "version": body.get("version", "1.0"),
        "session": body.get("session", {}),
        "response": {
            "end_session": False,
            "text": answer
        }
    }
