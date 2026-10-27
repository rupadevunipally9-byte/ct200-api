import os

import httpx
from dotenv import load_dotenv

load_dotenv()


class LLMError(Exception):
    """The AI could not be reached, or answered with an HTTP error."""


def model_name():
    return os.environ.get("LLM_MODEL", "openai/gpt-oss-120b")


def call_llm(messages):
    api_key = os.environ.get("LLM_API_KEY")
    if not api_key:
        raise LLMError("LLM_API_KEY is not set (put it in the .env file)")
    base_url = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    try:
        r = httpx.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model_name(),
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "messages": messages,
            },
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
        raise LLMError(f"LLM call failed: {e}") from e