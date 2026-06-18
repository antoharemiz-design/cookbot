import json
import re
from openai import AsyncOpenAI
from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, MODEL_NAME, SYSTEM_PROMPT

print(f"DEBUG: OPENROUTER_API_KEY starts with: {OPENROUTER_API_KEY[:10] if OPENROUTER_API_KEY else 'None'}...")
client = AsyncOpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url=OPENROUTER_BASE_URL,
    default_headers={
        "HTTP-Referer": "http://t.me/your_bot",
        "X-Title": "CookBot"
    }
)

def extract_json(text: str) -> dict | None:
    # Ищем блок ```json ... ```
    match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
    if match:
        text = match.group(1)
    else:
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1:
            text = text[start:end+1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None

async def get_recipe(products: str, extra_context: str = "") -> dict | None:
    try:
        user_prompt = f"Продукты: {products}"
        if extra_context:
            user_prompt += f"\n{extra_context}"
        print(f"DEBUG: запрос к модели {MODEL_NAME} с промптом: {user_prompt}")
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=0.7,
            max_tokens=800
        )
        content = response.choices[0].message.content
        print(f"DEBUG: ответ от модели:\n{content}")

        recipe = extract_json(content)
        if recipe is None:
            print("DEBUG: не удалось распарсить JSON")
            return None

        required_keys = {"title", "ingredients", "steps"}
        if not required_keys.issubset(recipe.keys()):
            print("DEBUG: в ответе нет нужных ключей")
            return None
        return recipe

    except Exception as e:
        print(f"Ошибка AI: {type(e).__name__}: {e}")
        return None
