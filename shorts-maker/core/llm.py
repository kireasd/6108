"""내 컴퓨터에서 돌아가는 AI(Ollama)와 대화하기."""
import json
import re

import requests


class LLMError(Exception):
    pass


def ask_json(settings, prompt, system=None):
    """AI에게 질문하고 JSON 답을 받는다."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    try:
        res = requests.post(
            settings["ollama_url"].rstrip("/") + "/api/chat",
            json={
                "model": settings["ollama_model"],
                "messages": messages,
                "format": "json",
                "stream": False,
                "options": {"temperature": 0.7},
            },
            timeout=600,
        )
    except requests.ConnectionError:
        raise LLMError("Ollama(내 컴퓨터 AI)가 켜져 있지 않아요. Ollama를 실행한 뒤 다시 시도해 주세요.")
    if res.status_code == 404:
        raise LLMError(
            f"AI 모델 '{settings['ollama_model']}'이(가) 설치되어 있지 않아요. "
            f"install.bat을 다시 실행하거나 'ollama pull {settings['ollama_model']}'을 실행해 주세요."
        )
    res.raise_for_status()
    content = res.json()["message"]["content"]
    return parse_json(content)


def parse_json(text):
    try:
        return json.loads(text)
    except ValueError:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except ValueError:
                pass
    raise LLMError("AI 답변을 이해하지 못했어요. 한 번 더 시도해 주세요.")


def check(settings):
    """Ollama가 켜져 있고 모델이 있는지 확인. (ok, 메시지)"""
    try:
        res = requests.get(settings["ollama_url"].rstrip("/") + "/api/tags", timeout=5)
        names = [m["name"] for m in res.json().get("models", [])]
    except (requests.RequestException, ValueError):
        return False, "Ollama가 꺼져 있어요."
    model = settings["ollama_model"]
    if not any(n == model or n.split(":")[0] == model for n in names):
        return False, f"Ollama는 켜져 있지만 '{model}' 모델이 없어요."
    return True, f"Ollama 정상 ({model})"
