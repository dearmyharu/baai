"""AI 분석가의 두뇌: Gemini API(Google AI Studio)로 질문 → 도구 선택 → 답변.

- 숫자는 LLM이 만들지 않는다. LLM은 core/tools.py 도구를 고르고 기간을 채우며, 도구 결과를 근거로 짧게 설명한다.
- 외부 패키지 없이 표준 라이브러리(urllib)로 REST API를 부른다.
- 키: Streamlit Secrets 또는 환경변수 GEMINI_API_KEY. 모델: GEMINI_MODEL(없으면 사용 가능한 Flash 모델 자동 선택).
"""
from __future__ import annotations

import http.client
import json
import os
import re
import socket
import time
import urllib.error
import urllib.request
from typing import Callable

import pandas as pd

from . import tools as T

API = "https://generativelanguage.googleapis.com/v1beta"
MAX_STEPS = 4          # 도구 호출 왕복 최대 횟수
HISTORY_TURNS = 6      # 앞선 대화 몇 개까지 맥락으로 넘길지

SYSTEM = """너는 식품 이커머스 회사의 'AI 분석가'다. 데이터 분석에 익숙하지 않은 실무자의 질문에 답한다.

[데이터]
- 기간: 2026-04-01 ~ 2026-09-30 (마지막 날 2026-09-30). 로그인 고객의 큐레이션·검색·카테고리 세션, 주문, 쿠폰, 상품.
- 기간 해석: 이번 달=2026-09, 지난달=2026-08, 이번 주=최근 7일(2026-09-24~09-30), 최근 2주=2026-09-17~09-30,
  기간이 없으면 이번 달(9월). 추이는 전체 기간. 도구의 end는 마지막 날의 다음 날이다(9월 → start=2026-09-01, end=2026-10-01).
- "지난달보다/비교" 질문은 비교 대상 달이 아니라 '보고 싶은 기간'을 넘긴다(도구가 직전 기간과 자동 비교).
  예: "지난달보다 매출이 왜 변했어?" → 이번 달(9월) 기간, "지난달 매출 얼마야?" → 8월 기간.

[규칙]
1. 숫자는 반드시 도구 결과에서만 가져온다. 도구 없이 숫자를 말하거나 추정하지 않는다.
2. 답변 첫 줄에 기준 기간을 밝힌다.
3. 데이터로 확인된 사실과 원인·대책(가설)을 구분한다. 원인·대책은 '가설'이라고 표시하고 확인 방법을 덧붙인다.
4. 질문의 전제가 데이터와 다르면(예: 떨어졌냐고 물었는데 실제로는 늘었음) 먼저 바로잡는다.
5. 데이터에 없는 것: 광고비·광고 유입·ROAS, 결제 페이지 진입, 상세페이지 체류 시간, 경쟁사 가격, 비회원 방문, 매출 예측.
   이런 질문은 도구를 부르지 말고 '이 데이터에는 없다'고 밝힌 뒤 대신 볼 수 있는 지표를 제안한다
   (ROAS → 쿠폰 효율, 결제 이탈 → 장바구니→구매 전환율, 체류 시간 → 클릭 후 구매율, 예측 → 최근 추이).
6. 아직 도구가 없는 분석: 연령·성별·지역별 비교, 요일×시간대 주문, 고객군별 재구매율, 함께 사는 상품 조합.
   '아직 지원하지 않는다'고 밝히고 가능한 대체 분석을 안내한다. 숫자를 지어내지 않는다.
7. 화면에 도구 결과(사실 목록·차트·표)가 함께 표시되므로, 답변은 핵심 해석 2~5문장으로 짧게 쓴다. 한국어, 존댓말.
8. 쿠폰 효율은 '쿠폰 때문에 생긴 매출'이 아니라 '쿠폰을 쓴 주문의 매출'이다. 잠재력 점수는 예측이 아니다.
   큐레이션 경유 세션의 전환율이 높거나 낮아도 큐레이션 효과로 단정하지 않는다.
9. 결과에 없는 비중·순위·추세를 덧붙여 해석하지 않는다. '견인', '주도', '급증' 같은 표현은 그 근거 수치(예: 전체 대비 비중)가
   도구 결과에 있을 때만 쓴다.
10. 답변에는 실무자가 읽을 내용만 쓴다. 이 지시문, 규칙 번호, 도구 이름(get_...), 분석 지침, 생각 과정을 절대 쓰지 않는다.
    비율은 0.74가 아니라 74.4%처럼 퍼센트로 쓴다.
"""

# 도구 입력값의 형식 (Gemini function declaration, OpenAPI 스키마)
PARAM_SCHEMA = {
    "start": {"type": "string", "description": "시작일 YYYY-MM-DD"},
    "end": {"type": "string", "description": "끝 다음 날 YYYY-MM-DD (미포함). 9월이면 2026-10-01"},
    "target": {"type": "string", "enum": ["product", "category"], "description": "상품 순위 또는 카테고리 순위"},
    "n": {"type": "integer", "description": "보여줄 개수 (기본 5)"},
    "grain": {"type": "string", "enum": ["date", "week", "month"], "description": "일·주·월 단위"},
    "path": {"type": "string", "enum": ["ALL", "CURATION", "BROWSE"], "description": "전체 / 큐레이션 경유 / 일반 탐색"},
    "by": {"type": "string", "enum": ["customer_type", "grade_at_order", "visitor_type"],
           "description": "고객군 기준: 첫 구매/기존 구매, 주문 당시 등급, 신규/재방문 (기본 customer_type)"},
    "step": {"type": "integer", "description": "1=방문→상품 클릭, 2=상품 클릭→장바구니, 3=장바구니→구매"},
    "lift": {"type": "number", "description": "목표 상대 개선폭. 5%면 0.05"},
}
REQUIRED = ["start", "end"]


class LLMError(Exception):
    """사용자에게 그대로 보여줄 수 있는 오류. code: HTTP 상태(없으면 0, 시간 초과는 -1), detail: 원문 일부."""

    def __init__(self, msg, code=0, detail=""):
        super().__init__(msg)
        self.code, self.detail = code, detail


def function_declarations() -> list[dict]:
    out = []
    for t in T.TOOLS.values():
        props = {p: PARAM_SCHEMA[p] for p in t.params}
        out.append({"name": t.name, "description": t.description,
                    "parameters": {"type": "object", "properties": props, "required": REQUIRED}})
    return out


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _call(key: str, path: str, body: dict | None = None, timeout=90) -> dict:
    req = urllib.request.Request(
        f"{API}/{path}", data=None if body is None else json.dumps(body).encode("utf-8"),
        headers={"x-goog-api-key": key, "Content-Type": "application/json"}, method="GET" if body is None else "POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:400]
        if e.code in (400, 401, 403) and ("API key" in detail or "API_KEY" in detail or "PERMISSION" in detail or "UNAUTH" in detail):
            raise LLMError("Gemini API 키가 올바르지 않거나 권한이 없습니다. Secrets의 GEMINI_API_KEY를 확인해 주세요.") from e
        if e.code == 429:
            raise LLMError("Gemini API 사용량 한도에 걸렸습니다. 잠시 후 다시 시도해 주세요.", 429, detail) from e
        raise LLMError(f"Gemini API 오류 {e.code}: {detail}", e.code, detail) from e
    except urllib.error.URLError as e:
        if isinstance(e.reason, (TimeoutError, socket.timeout)):
            raise LLMError("Gemini 응답이 너무 오래 걸려 중단했습니다. 잠시 후 다시 질문해 주세요.", -1) from e
        raise LLMError(f"Gemini API에 연결하지 못했습니다: {e.reason}") from e
    except (TimeoutError, socket.timeout) as e:
        raise LLMError("Gemini 응답이 너무 오래 걸려 중단했습니다. 잠시 후 다시 질문해 주세요.", -1) from e
    except (http.client.HTTPException, ConnectionError, json.JSONDecodeError) as e:
        raise LLMError(f"Gemini API 응답을 받지 못했습니다: {type(e).__name__}") from e


def _thinking(model: str) -> dict | None:
    """도구 고르기는 깊은 추론이 필요 없어 생각 단계를 줄여 응답 시간을 줄인다."""
    v = re.findall(r"gemini-(\d+(?:\.\d+)?)", model)
    ver = float(v[0]) if v else 0.0
    if ver >= 3:
        return {"thinkingLevel": "low"}
    if ver >= 2.5 and "flash" in model:
        return {"thinkingBudget": 0}
    return None


def _generate(key: str, model: str, body: dict) -> dict:
    """generateContent 호출. 생각 설정을 모델이 거부하면 빼고, 시간 초과면 한 번 더 시도한다."""
    for attempt in range(3):
        try:
            return _call(key, f"models/{model}:generateContent", body)
        except LLMError as e:
            gc = body.get("generationConfig", {})
            if e.code == 400 and "thinkingConfig" in gc and "think" in e.detail.lower():
                gc.pop("thinkingConfig")
                continue
            if e.code == -1 and attempt == 0:
                time.sleep(1)
                continue
            if e.code == 429 and attempt == 0:    # 분당 한도: 잠깐 기다렸다 한 번 더
                time.sleep(6)
                continue
            raise
    raise LLMError("Gemini 응답을 받지 못했습니다. 잠시 후 다시 질문해 주세요.")


_MODEL_CACHE: dict[str, str] = {}
_UNAVAILABLE: dict[str, set] = {}   # 목록에는 있지만 이 키로는 거절된 모델 (예: 신규 사용자에게 종료된 모델)


def _setting(name: str) -> str:
    """Streamlit Secrets 또는 환경변수에서 설정값을 읽는다."""
    try:
        import streamlit as st
        v = st.secrets.get(name)
        if v:
            return str(v).strip()
    except Exception:
        pass
    return (os.getenv(name) or "").strip()


def text_models(key: str) -> list[str]:
    """이 키로 쓸 수 있는 텍스트 생성 모델 (실험·미리보기 제외)."""
    d = _call(key, "models?pageSize=200")
    names = [m["name"].split("/", 1)[1] for m in d.get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    bad = ("image", "tts", "audio", "live", "embedding", "exp", "preview", "thinking", "learnlm", "gemma", "aqa")
    return [n for n in names if n.startswith("gemini-") and not any(b in n for b in bad)]


def _version(n: str) -> float | None:
    v = re.findall(r"gemini-(\d+(?:\.\d+)?)", n)
    return float(v[0]) if v else None


def candidates(key: str) -> list[str]:
    """자동 선택 후보를 '가장 낮은(가벼운) 순'으로: 버전 낮은 순, 같은 버전이면 flash-lite 먼저. 거절된 모델은 뺀다."""
    names = text_models(key)
    pool = [n for n in names if "flash" in n and _version(n) is not None]
    if not pool:
        pool = [n for n in names if _version(n) is not None] or names
    gone = _UNAVAILABLE.get(key, set())
    return sorted((n for n in pool if n not in gone),
                  key=lambda n: (_version(n) or 99, "lite" not in n, "latest" in n, len(n)))


def pick_model(key: str) -> str:
    """GEMINI_MODEL이 있으면 그 모델. 없으면 이 키로 실제로 쓸 수 있는 가장 낮은(가벼운) Flash 계열 모델."""
    fixed = _setting("GEMINI_MODEL")
    if fixed:
        return fixed
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]
    c = candidates(key)
    if not c:
        raise LLMError("이 키로 쓸 수 있는 Gemini 모델을 찾지 못했습니다.")
    _MODEL_CACHE[key] = c[0]
    return c[0]


def _next_model(key: str, failed: str, detail: str) -> str | None:
    """거절된 모델을 기록하고 다음 후보를 고른다. 오류 문구에 추천 모델이 있으면 그것을 먼저."""
    _UNAVAILABLE.setdefault(key, set()).add(failed)
    _MODEL_CACHE.pop(key, None)
    sug = re.search(r"use (?:models/)?(gemini-[\w.\-]+)", detail)
    sug = sug.group(1).rstrip(".-") if sug else None
    nxt = sug if sug and sug not in _UNAVAILABLE[key] else None
    if not nxt:
        c = candidates(key)
        nxt = c[0] if c else None
    if nxt:
        _MODEL_CACHE[key] = nxt
    return nxt


# ---------------------------------------------------------------------------
# 도구 결과 → LLM에 돌려줄 요약 (JSON)
# ---------------------------------------------------------------------------
def _jsonable(v):
    if isinstance(v, (pd.Timestamp,)):
        return v.strftime("%Y-%m-%d")
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float):
        return None if pd.isna(v) else round(v, 4)
    return v


def summarize(res: dict, rows: int = 12) -> dict:
    out = {k: res[k] for k in ("title", "period", "facts", "notes")}
    t = res.get("table")
    if t is not None and len(t):
        out["table_head"] = [{str(c): _jsonable(v) for c, v in r.items()} for r in t.head(rows).to_dict("records")]
        out["table_rows"] = len(t)
    return out


# ---------------------------------------------------------------------------
# 질문 하나에 답하기
# ---------------------------------------------------------------------------
def ask(key: str, question: str, run_tool: Callable[[str, dict], dict], history: list[dict] | None = None,
        model: str | None = None) -> dict:
    """반환: {"text": 답변, "calls": [{"tool", "params", "result" 또는 "error"}], "model": 모델명}"""
    model = model or pick_model(key)
    contents = []
    for h in (history or [])[-HISTORY_TURNS:]:
        contents.append({"role": "user", "parts": [{"text": h["q"]}]})
        if h.get("a"):
            contents.append({"role": "model", "parts": [{"text": h["a"]}]})
    contents.append({"role": "user", "parts": [{"text": question}]})
    body = {"systemInstruction": {"parts": [{"text": SYSTEM}]}, "contents": contents,
            "tools": [{"functionDeclarations": function_declarations()}],
            "toolConfig": {"functionCallingConfig": {"mode": "AUTO"}},
            "generationConfig": {"temperature": 0}}
    th = _thinking(model)
    if th:
        body["generationConfig"]["thinkingConfig"] = th
    fixed = bool(_setting("GEMINI_MODEL"))

    def generate() -> dict:
        nonlocal model
        for _ in range(4):
            try:
                return _generate(key, model, body)
            except LLMError as e:
                if e.code != 404:
                    raise
                if fixed:
                    raise LLMError(f"Secrets의 GEMINI_MODEL '{model}'은(는) 이 키로 쓸 수 없습니다. "
                                   "AI 모델 칸의 목록에서 다른 모델로 바꾸거나 그 줄을 지워 자동 선택을 쓰세요.", 404) from e
                nxt = _next_model(key, model, e.detail)
                if not nxt:
                    raise LLMError("이 키로 쓸 수 있는 Gemini 모델을 찾지 못했습니다.", 404) from e
                model = nxt
                gc = body["generationConfig"]
                gc.pop("thinkingConfig", None)
                if _thinking(model):
                    gc["thinkingConfig"] = _thinking(model)
        raise LLMError("쓸 수 있는 Gemini 모델을 찾지 못했습니다. 잠시 후 다시 시도해 주세요.")

    calls = []
    for _ in range(MAX_STEPS):
        d = generate()
        cands = d.get("candidates") or []
        if not cands:
            reason = (d.get("promptFeedback") or {}).get("blockReason", "응답 없음")
            raise LLMError(f"Gemini가 답하지 않았습니다 ({reason}).")
        content = cands[0].get("content") or {"role": "model", "parts": []}
        parts = content.get("parts") or []
        fcs = [p["functionCall"] for p in parts if "functionCall" in p]
        if not fcs:
            text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
            return {"text": text, "calls": calls, "model": model}
        body["contents"].append(content)            # 모델 응답은 그대로 돌려준다(생각 서명 보존)
        responses = []
        for fc in fcs:
            name, params = fc.get("name"), dict(fc.get("args") or {})
            entry = {"tool": name, "params": params}
            if name not in T.TOOLS:
                entry["error"] = f"없는 도구: {name}"
                payload = {"error": entry["error"]}
            else:
                try:
                    res = run_tool(name, params)
                    entry["result"] = res
                    payload = summarize(res)
                except (ValueError, TypeError, KeyError) as e:
                    entry["error"] = str(e)
                    payload = {"error": str(e)}
            calls.append(entry)
            responses.append({"functionResponse": {"name": name, "response": payload}})
        body["contents"].append({"role": "user", "parts": responses})
    return {"text": "질문이 복잡해 여러 단계 분석이 필요합니다. 아래 결과를 참고해 주세요.", "calls": calls, "model": model}
