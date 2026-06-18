import json
import re
from openai import AsyncOpenAI
from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, MODEL_NAME, SYSTEM_PROMPT

client = AsyncOpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url=OPENROUTER_BASE_URL,
    default_headers={
        "HTTP-Referer": "http://t.me/your_bot",
        "X-Title": "CookBot"
    }
)

def extract_json(text: str) -> dict | None:
    # Ищем ```json ... ```
    match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
    if match:
        text = match.group(1)
    else:
        # Ищем первый { и последний }
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1:
            text = text[start:end+1]
    try:
        # Иногда модель возвращает JSON с комментариями (//) – удаляем их
        text = re.sub(r'//.*', '', text)
        return json.loads(text)
    except json.JSONDecodeError:
        return None

async def get_recipe(products: str, extra_context: str = "") -> tuple[dict | None, str | None]:
    try:
        user_prompt = f"Продукты: {products}"
        if extra_context:
            user_prompt += f"\n{extra_context}"
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            max_tokens=800
        )
        content = response.choices[0].message.content
        recipe = extract_json(content)
        return recipe, content
    except Exception as e:
        error_str = str(e)
        if "429" in error_str:
            # Ошибка лимита запросов
            return None, "RATE_LIMIT"
        print(f"Ошибка AI: {type(e).__name__}: {e}")
        return None, None
