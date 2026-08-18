from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class ProviderConfig:
    provider: str = "Demo"
    endpoint: str = ""
    model: str = ""
    api_key: str = ""


DEFAULTS = {
    "DeepSeek": ("https://api.deepseek.com/chat/completions", "deepseek-v4-flash"),
    "Qwen": ("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", "qwen-plus"),
    "OpenAI": ("https://api.openai.com/v1/chat/completions", "gpt-4.1-mini"),
    "Demo": ("", "demo"),
}


class ChatProvider:
    def __init__(self, config: ProviderConfig):
        self.config = config

    def complete(self, system: str, user: str, max_tokens: int = 8192, retries: int = 3) -> str:
        if self.config.provider == "Demo":
            raise RuntimeError("Demo responses are produced by the local demo pipeline.")
        if not self.config.api_key:
            raise ValueError(f"Enter a {self.config.provider} API key first.")
        payload = json.dumps({
            "model": self.config.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.35,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }, ensure_ascii=False).encode("utf-8")
        last_error: Exception | None = None
        retry_delays = (2, 5, 10)
        for attempt in range(retries + 1):
            request = urllib.request.Request(self.config.endpoint, data=payload, headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            })
            try:
                with urllib.request.urlopen(request, timeout=240) as response:
                    data = json.loads(response.read().decode("utf-8"))
                choice = data["choices"][0]
                content = choice["message"].get("content")
                if not content or not str(content).strip():
                    last_error = RuntimeError("The provider returned an empty response after automatic retries.")
                    if attempt >= retries:
                        raise last_error
                    time.sleep(retry_delays[min(attempt, len(retry_delays) - 1)])
                    continue
                if choice.get("finish_reason") == "length":
                    raise RuntimeError("The provider response was truncated because this request produced too much output.")
                return content
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:800]
                last_error = RuntimeError(f"API request failed ({exc.code}): {detail}")
                if exc.code not in (408, 429, 500, 502, 503, 504) or attempt >= retries:
                    raise last_error from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = RuntimeError(f"Could not reach the API: {exc}")
                if attempt >= retries:
                    raise last_error from exc
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                raise RuntimeError("The provider returned an unexpected response format.") from exc
            time.sleep(retry_delays[min(attempt, len(retry_delays) - 1)])
        raise last_error or RuntimeError("API request failed.")

    def test(self) -> str:
        text = self.complete("Return JSON only.", 'Return exactly {"status":"ok"}.', 64)
        return "Connection successful" if "ok" in text.lower() else "Connected, but received an unexpected test response"


def parse_json_response(text: str) -> dict:
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[1]
        clean = clean.rsplit("```", 1)[0]
    start, end = clean.find("{"), clean.rfind("}")
    if start < 0 or end < start:
        raise ValueError("The LLM response did not contain a JSON object.")
    return json.loads(clean[start:end + 1])
