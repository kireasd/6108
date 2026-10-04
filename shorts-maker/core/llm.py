"""AI와 대화하기. 내 컴퓨터 AI(Ollama)와 유료 AI(Claude, ChatGPT, Gemini) 중 골라 쓴다."""
import base64
import json
import re

import requests

PROVIDERS = {
    "local": "🏠 내 컴퓨터 AI (무료)",
    "claude": "💳 Claude (Anthropic)",
    "openai": "💳 ChatGPT (OpenAI)",
    "gemini": "💳 Gemini (Google)",
}
KEY_FIELDS = {"claude": "claude_key", "openai": "openai_key", "gemini": "gemini_key"}
MODEL_FIELDS = {"local": "ollama_model", "claude": "claude_model",
                "openai": "openai_model", "gemini": "gemini_model"}


class LLMError(Exception):
    pass


def ask_json(settings, prompt, system=None, images=None):
    """설정에서 고른 AI에게 질문하고 JSON 답을 받는다. images: 함께 보여줄 JPG 경로 목록."""
    provider = settings.get("provider", "local")
    if provider != "local" and not settings.get(KEY_FIELDS[provider], "").strip():
        raise LLMError(f"{PROVIDERS[provider]} 키(API 키)가 없어요. ⚙ 설정에서 키를 넣어 주세요.")
    ask = {"local": _ask_ollama, "claude": _ask_claude,
           "openai": _ask_openai, "gemini": _ask_gemini}[provider]
    return parse_json(ask(settings, prompt, system or "", [_b64(p) for p in images or []]))


def _b64(path):
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("ascii")


def _ask_ollama(settings, prompt, system, images):
    user = {"role": "user", "content": prompt}
    if images:
        user["images"] = images
    messages = [{"role": "system", "content": system}, user]
    try:
        res = requests.post(
            settings["ollama_url"].rstrip("/") + "/api/chat",
            json={"model": settings["ollama_model"], "messages": messages, "format": "json",
                  "stream": False, "options": {"temperature": 0.7}},
            timeout=600,
        )
    except requests.ConnectionError:
        raise LLMError("Ollama(내 컴퓨터 AI)가 켜져 있지 않아요. Ollama를 실행한 뒤 다시 시도해 주세요.")
    if res.status_code == 404:
        raise LLMError(
            f"AI 모델 '{settings['ollama_model']}'이(가) 설치되어 있지 않아요. "
            f"install.bat을 다시 실행해서 내 컴퓨터 AI를 설치해 주세요."
        )
    res.raise_for_status()
    return res.json()["message"]["content"]


def _ask_claude(settings, prompt, system, images):
    import anthropic
    client = anthropic.Anthropic(api_key=settings["claude_key"].strip())
    try:
        response = client.beta.messages.create(
            model=settings["claude_model"],
            max_tokens=16000,
            system=system + " JSON 외의 다른 글은 쓰지 않는다.",
            messages=[{"role": "user", "content": [
                *({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": d}}
                  for d in images),
                {"type": "text", "text": prompt},
            ]}],
            output_config={"effort": "medium"},
            # 안전 검사로 거절되면 다른 Claude 모델이 이어서 답하게 한다
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError:
        raise LLMError("Claude 키가 올바르지 않아요. ⚙ 설정에서 키를 다시 확인해 주세요.")
    except anthropic.PermissionDeniedError:
        raise LLMError("Claude 키에 권한이 없어요. Anthropic 콘솔에서 결제(크레딧)를 확인해 주세요.")
    except anthropic.NotFoundError:
        raise LLMError(f"Claude 모델 이름 '{settings['claude_model']}'을(를) 찾을 수 없어요.")
    except anthropic.RateLimitError:
        raise LLMError("Claude 사용량 한도에 걸렸어요. 잠시 뒤 다시 시도해 주세요.")
    except anthropic.APIConnectionError:
        raise LLMError("Claude에 연결하지 못했어요. 인터넷 연결을 확인해 주세요.")
    except anthropic.APIStatusError as e:
        raise LLMError(f"Claude 오류: {e.message}")
    if response.stop_reason == "refusal":
        raise LLMError("Claude가 이 주제로는 대본을 쓰지 않겠다고 했어요. 다른 주제로 시도해 주세요.")
    return "".join(b.text for b in response.content if b.type == "text")


def _ask_openai(settings, prompt, system, images):
    import openai
    client = openai.OpenAI(api_key=settings["openai_key"].strip())
    try:
        response = client.chat.completions.create(
            model=settings["openai_model"],
            messages=[{"role": "system", "content": system}, {"role": "user", "content": [
                *({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + d}} for d in images),
                {"type": "text", "text": prompt},
            ]}],
            response_format={"type": "json_object"},
        )
    except openai.AuthenticationError:
        raise LLMError("ChatGPT 키가 올바르지 않아요. ⚙ 설정에서 키를 다시 확인해 주세요.")
    except openai.RateLimitError:
        raise LLMError("ChatGPT 사용량 한도에 걸렸거나 크레딧이 없어요. OpenAI 결제 화면을 확인해 주세요.")
    except openai.APIConnectionError:
        raise LLMError("ChatGPT에 연결하지 못했어요. 인터넷 연결을 확인해 주세요.")
    except openai.APIStatusError as e:
        raise LLMError(f"ChatGPT 오류: {e.message}")
    return response.choices[0].message.content or ""


def _ask_gemini(settings, prompt, system, images):
    from google import genai
    from google.genai import errors, types
    client = genai.Client(api_key=settings["gemini_key"].strip())
    try:
        response = client.models.generate_content(
            model=settings["gemini_model"],
            contents=[*(types.Part.from_bytes(data=base64.b64decode(d), mime_type="image/jpeg")
                        for d in images), prompt],
            config=types.GenerateContentConfig(system_instruction=system,
                                               response_mime_type="application/json"),
        )
    except errors.ClientError as e:
        raise LLMError(f"Gemini 키나 모델 이름을 확인해 주세요. ({e.code})")
    except errors.APIError as e:
        raise LLMError(f"Gemini 오류: {e.message}")
    return response.text or ""


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
    """지금 고른 AI를 쓸 수 있는지 확인. (ok, 메시지)"""
    provider = settings.get("provider", "local")
    model = settings[MODEL_FIELDS[provider]]
    if provider != "local":
        if settings.get(KEY_FIELDS[provider], "").strip():
            return True, f"{PROVIDERS[provider]} 사용 ({model})"
        return False, f"{PROVIDERS[provider]}를 골랐지만 키가 없어요."
    try:
        res = requests.get(settings["ollama_url"].rstrip("/") + "/api/tags", timeout=5)
        names = [m["name"] for m in res.json().get("models", [])]
    except (requests.RequestException, ValueError):
        return False, "Ollama(내 컴퓨터 AI)가 꺼져 있거나 설치되지 않았어요."
    if not any(n == model or n.split(":")[0] == model for n in names):
        return False, f"Ollama는 켜져 있지만 '{model}' 모델이 없어요."
    return True, f"내 컴퓨터 AI 정상 ({model})"
