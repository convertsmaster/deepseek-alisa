import os
from fastapi import FastAPI, Request
import requests

app = FastAPI()

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

@app.post("/")
async def main(request: Request):
    body = await request.json()
    user_text = body["request"]["original_utterance"]

    response = requests.post(
        DEEPSEEK_API_URL,
        headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
        json={
            "model": "deepseek-v4-flash",
            "messages": [
                {
                    "role": "system",
                    "content": "Ты — профессор Почемучкин. Отвечай коротко, чётко и по делу — максимум 1-2 предложения. Ты мужчина, говори от мужского лица. Никаких рассуждений вслух."
                },
                {"role": "user", "content": user_text}
            ],
            "max_tokens": 60,
            "temperature": 0.3
        }
    )
    answer = response.json()["choices"][0]["message"]["content"]

    return {
        "version": body["version"],
        "session": body["session"],
        "response": {
            "end_session": False,
            "text": answer
        }
    }
