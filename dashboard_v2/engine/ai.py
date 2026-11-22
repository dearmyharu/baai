"""AI 호출: 질문 → 질의서 초안(JSON) 한 가지만. 도구 호출·답변 작성은 하지 않는다.

OpenAI(GPT) Chat Completions + JSON schema(strict). 표준 라이브러리만 사용.
키: Streamlit Secrets 또는 환경변수 OPENAI_API_KEY. 모델 고정: OPENAI_MODEL (없으면 쓸 수 있는 가장 가벼운 최신 모델).
"""
from __future__ import annotations

import copy
import http.client
import json
import os
import re
import socket
import time
import urllib.error
import urllib.request

API = "https://api.openai.com/v1"
_MODEL_CACHE: dict[str, str] = {}
_UNAVAILABLE: dict[str, set] = {}


class LLMError(Exception):
    """사용자에게 그대로 보여줄 수 있는 오류. code: HTTP 상태(없으면 0, 시간 초과는 -1), detail: 원문 일부."""

    def __init__(self, msg, code=0, detail=""):
        super().__init__(msg)
        self.code, self.detail = code, detail


def _setting(name: str) -> str:
    """Streamlit Secrets 또는 환경변수."""
    try:
        import streamlit as st
        v = st.secrets.get(name)
        if v:
            return str(v).strip()
    except Exception:  # noqa: BLE001  Secrets가 없는 실행 환경
        pass
    return (os.getenv(name) or "").strip()


def api_key() -> str | None:
    v = _setting("OPENAI_API_KEY")
    return v if v and "붙여넣기" not in v else None


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _message(detail: str) -> str:
    try:
        return json.loads(detail)["error"]["message"]
    except Exception:
        return detail[:200]


def _call(key: str, path: str, body: dict | None = None, timeout=90) -> dict:
    req = urllib.request.Request(
        f"{API}/{path}", data=None if body is None else json.dumps(body, ensure_ascii=False, default=str).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="GET" if body is None else "POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:800]
        if e.code == 401:
            raise LLMError("OpenAI API 키가 올바르지 않습니다. Secrets의 OPENAI_API_KEY를 확인해 주세요.", 401, detail) from e
        if e.code == 429 and "insufficient_quota" in detail:
            raise LLMError("OpenAI 계정에 쓸 수 있는 크레딧이 없습니다. platform.openai.com의 Billing에서 "
                           "결제 수단을 등록하거나 크레딧을 충전해 주세요.", 402, detail) from e
        if e.code == 429:
            raise LLMError("OpenAI API 사용량 한도에 걸렸습니다. 잠시 후 다시 시도해 주세요.", 429, detail) from e
        if e.code in (403, 404) and "model" in detail.lower():
            raise LLMError(f"이 키로 쓸 수 없는 모델입니다: {_message(detail)}", 404, detail) from e
        raise LLMError(f"OpenAI API 오류 {e.code}: {_message(detail)}", e.code, detail) from e
    except urllib.error.URLError as e:
        if isinstance(e.reason, (TimeoutError, socket.timeout)):
            raise LLMError("GPT 응답이 너무 오래 걸려 중단했습니다. 잠시 후 다시 질문해 주세요.", -1) from e
        raise LLMError(f"OpenAI API에 연결하지 못했습니다: {e.reason}") from e
    except (TimeoutError, socket.timeout) as e:
        raise LLMError("GPT 응답이 너무 오래 걸려 중단했습니다. 잠시 후 다시 질문해 주세요.", -1) from e
    except (http.client.HTTPException, ConnectionError, json.JSONDecodeError) as e:
        raise LLMError(f"OpenAI API 응답을 받지 못했습니다: {type(e).__name__}") from e


# ---------------------------------------------------------------------------
# 모델 고르기: 이 키로 쓸 수 있는 가장 가벼운 등급(nano → mini)의 최신 버전
# ---------------------------------------------------------------------------
_SKIP = ("audio", "realtime", "search", "transcribe", "tts", "image", "codex", "instruct", "oss", "deep-research",
         "chat-latest", "embedding", "moderation")


def text_models(key: str) -> list[str]:
    d = _call(key, "models")
    ids = [m["id"] for m in d.get("data", [])]
    return sorted(i for i in ids if i.startswith("gpt-") and not any(s in i for s in _SKIP))


def _version(n: str) -> float | None:
    v = re.findall(r"gpt-(\d+(?:\.\d+)?)", n)
    return float(v[0]) if v else None


def candidates(key: str) -> list[str]:
    gone = _UNAVAILABLE.get(key, set())
    names = [n for n in text_models(key) if n not in gone and (_version(n) or 0) >= 4.1]
    plain = [n for n in names if not re.search(r"-\d{4}-\d{2}-\d{2}$", n)] or names   # 날짜 붙은 고정판은 뒤로
    tier = lambda n: 0 if n.endswith("-nano") else 1 if n.endswith("-mini") else 2
    return sorted(plain, key=lambda n: (tier(n), -(_version(n) or 0), len(n)))


def pick_model(key: str) -> str:
    fixed = _setting("OPENAI_MODEL")
    if fixed:
        return fixed
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]
    c = candidates(key)
    if not c:
        raise LLMError("이 키로 쓸 수 있는 GPT 모델을 찾지 못했습니다.")
    _MODEL_CACHE[key] = c[0]
    return c[0]


def _next_model(key: str, failed: str) -> str | None:
    _UNAVAILABLE.setdefault(key, set()).add(failed)
    _MODEL_CACHE.pop(key, None)
    c = candidates(key)
    if c:
        _MODEL_CACHE[key] = c[0]
    return c[0] if c else None


# ---------------------------------------------------------------------------
# 호출
# ---------------------------------------------------------------------------
def _reasoning(model: str) -> str | None:
    """GPT-5 계열은 추론 단계를 낮춰 응답 시간을 줄인다(도구 고르기는 깊은 추론이 필요 없음)."""
    return "low" if (_version(model) or 0) >= 5 or re.match(r"o\d", model) else None


def _chat(key: str, model: str, body: dict) -> dict:
    body = {**body, "model": model}
    r = _reasoning(model)
    if r:
        body["reasoning_effort"] = r
    for attempt in range(3):
        try:
            return _call(key, "chat/completions", body)
        except LLMError as e:
            if e.code == 400 and "reasoning_effort" in body and "reasoning" in e.detail:
                body.pop("reasoning_effort")
                continue
            if e.code in (-1, 429) and attempt == 0:
                time.sleep(1 if e.code == -1 else 6)
                continue
            raise
    raise LLMError("GPT 응답을 받지 못했습니다. 잠시 후 다시 질문해 주세요.")


def _chat_any(key: str, model: str, body: dict) -> tuple[dict, str]:
    """모델이 거절되면(404) 다음 후보로 바꿔 다시 부른다. (응답, 실제 쓴 모델)"""
    fixed = bool(_setting("OPENAI_MODEL"))
    for _ in range(4):
        try:
            return _chat(key, model, body), model
        except LLMError as e:
            if e.code != 404:
                raise
            if fixed:
                raise LLMError(f"Secrets의 OPENAI_MODEL '{model}'은(는) 이 키로 쓸 수 없습니다. "
                               "AI 모델 칸의 목록에서 다른 모델로 바꾸거나 그 줄을 지워 자동 선택을 쓰세요.", 404) from e
            nxt = _next_model(key, model)
            if not nxt:
                raise LLMError("이 키로 쓸 수 있는 GPT 모델을 찾지 못했습니다.", 404) from e
            model = nxt
    raise LLMError("쓸 수 있는 GPT 모델을 찾지 못했습니다. 잠시 후 다시 시도해 주세요.")


def _message_of(d: dict) -> dict:
    ch = d.get("choices") or []
    if not ch:
        raise LLMError("GPT가 답하지 않았습니다 (응답 없음).")
    msg = ch[0].get("message") or {}
    if msg.get("refusal"):
        raise LLMError(f"GPT가 답하지 않았습니다 ({msg['refusal']}).")
    return msg


def _strict(schema: dict) -> dict:
    """JSON schema strict 모드 조건: 모든 object에 additionalProperties=false, 모든 속성 required."""
    s = copy.deepcopy(schema)

    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "object" and "properties" in n:
                n["additionalProperties"] = False
                n["required"] = list(n["properties"])
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    walk(s)
    return s



def json_call(key: str, system: str, prompt: str, schema: dict, name: str = "draft", model: str | None = None
              ) -> tuple[dict, str, dict]:
    """JSON schema 형식으로만 답하게 한다. (파싱한 dict, 실제 쓴 모델, 토큰 사용량)"""
    body = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "response_format": {"type": "json_schema", "json_schema": {"name": name, "schema": _strict(schema), "strict": True}}}
    d, used = _chat_any(key, model or pick_model(key), body)
    u = d.get("usage") or {}
    usage = {"input": u.get("prompt_tokens") or 0, "output": u.get("completion_tokens") or 0}
    text = (_message_of(d).get("content") or "").strip()
    try:
        return json.loads(text), used, usage
    except json.JSONDecodeError as e:
        raise LLMError("GPT 응답을 읽지 못했습니다. 다시 질문해 주세요.") from e
