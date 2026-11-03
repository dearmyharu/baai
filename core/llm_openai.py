"""OpenAI(GPT) 연결: core/llm.py가 OPENAI_API_KEY를 쓸 때 부르는 부분.

질문 답변·Growth Lab 초안의 흐름(도구 고르기 → 실행 → 설명, 지어낸 숫자 차단)은 Gemini와 같고,
API 형식(Chat Completions, function calling, JSON schema 응답)만 다르다. 표준 라이브러리만 사용.
"""
from __future__ import annotations

import copy
import http.client
import json
import re
import socket
import time
import urllib.error
import urllib.request
from typing import Callable

from . import llm as L
from .llm import LLMError

API = "https://api.openai.com/v1"
_MODEL_CACHE: dict[str, str] = {}
_UNAVAILABLE: dict[str, set] = {}


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
    fixed = L._setting("OPENAI_MODEL")
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
    fixed = bool(L._setting("OPENAI_MODEL"))
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


def _messages(system: str, contents: list[dict]) -> list[dict]:
    """llm.py가 만든 대화(Gemini 형식 contents)를 Chat Completions 메시지로."""
    out = [{"role": "system", "content": system}]
    for c in contents:
        text = "".join(p.get("text", "") for p in c.get("parts", []))
        out.append({"role": "assistant" if c["role"] == "model" else "user", "content": text})
    return out


def tool_loop(key: str, system: str, contents: list[dict], run_tool: Callable[[str, dict], dict],
              model: str, steps: int) -> dict:
    """llm._tool_loop의 OpenAI판. 반환 형식 동일: {"text", "calls", "model"}"""
    tools = [{"type": "function", "function": {"name": d["name"], "description": d["description"],
                                               "parameters": d["parameters"]}} for d in L.function_declarations()]
    msgs = _messages(system, contents)
    body = {"messages": msgs, "tools": tools, "tool_choice": "auto"}
    calls, forced, usage = [], False, L.new_usage()
    for _ in range(steps + 1):
        d, model = _chat_any(key, model, body)
        L.add_usage(usage, d)
        msg = _message_of(d)
        tcs = msg.get("tool_calls") or []
        if not tcs:
            text = (msg.get("content") or "").strip()
            if not calls and not forced and L._NUM_RE.search(text):
                forced = True                          # 도구 없이 숫자 → 도구 호출을 강제해 다시 묻는다
                msgs.append({"role": "assistant", "content": text})
                msgs.append({"role": "user", "content": L.FORCE_TOOL_MSG})
                body["tool_choice"] = "required"
                continue
            if not calls and L._NUM_RE.search(text):
                text = "데이터 도구로 확인한 숫자가 없어 답할 수 없습니다. 질문을 조금 더 구체적으로 해 주세요."
            return {"text": L.clean(text), "calls": calls, "model": model, "usage": usage}
        body["tool_choice"] = "auto"
        msgs.append({"role": "assistant", "content": msg.get("content"), "tool_calls": tcs})
        for tc in tcs:
            fn = tc.get("function") or {}
            name = fn.get("name")
            try:
                params = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                params = {}
            entry = {"tool": name, "params": params}
            if name not in L.T.TOOLS:
                entry["error"] = f"없는 도구: {name}"
                payload = {"error": entry["error"]}
            else:
                try:
                    res = run_tool(name, params)
                    entry["result"] = res
                    payload = L.summarize(res)
                except (ValueError, TypeError, KeyError) as e:
                    entry["error"] = str(e)
                    payload = {"error": str(e)}
            calls.append(entry)
            msgs.append({"role": "tool", "tool_call_id": tc.get("id"),
                         "content": json.dumps(payload, ensure_ascii=False, default=str)})
    return {"text": "질문이 복잡해 여러 단계 분석이 필요합니다. 아래 결과를 참고해 주세요.", "calls": calls, "model": model,
            "usage": usage}


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


def json_call(key: str, model: str, system: str, prompt: str, schema: dict, name: str = "draft") -> tuple[str, str, dict]:
    """도구 없이 JSON schema 형식으로 답하게 한다. (JSON 문자열, 실제 쓴 모델, 토큰 사용량)"""
    body = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "response_format": {"type": "json_schema", "json_schema": {"name": name, "schema": _strict(schema), "strict": True}}}
    d, model = _chat_any(key, model, body)
    usage = L.new_usage()
    L.add_usage(usage, d)
    return (_message_of(d).get("content") or "").strip(), model, usage
