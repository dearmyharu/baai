"""Growth Lab 저장소.

- DB 접속 정보가 있으면 DB 테이블 growth_lab_problems 에 저장한다 (팀 공유, 배포 환경).
- 없으면 dashboard/growth_lab/store.json 파일에 저장한다 (혼자 쓰는 로컬).
GROWTH_LAB_BACKEND=json|db 로 강제할 수 있다.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

STORE_PATH = Path(__file__).resolve().parents[1] / "growth_lab" / "store.json"
TABLE = "growth_lab_problems"
KST = ZoneInfo("Asia/Seoul")

STATUSES = ["문제 후보", "문제 정의", "가설 검토", "전략 선정", "실험 설계 완료", "보류"]

_cache = {"t": 0.0, "data": None}
CACHE_SEC = 2.0


def _now() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M")


def _clean(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return None if np.isnan(v) else float(v)
    if isinstance(v, float) and np.isnan(v):
        return None
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def current_author() -> str:
    try:
        import streamlit as st
        return (st.session_state.get("user_name") or "").strip() or "익명"
    except Exception:
        return "익명"


# ---------------------------------------------------------------------------
# 백엔드
# ---------------------------------------------------------------------------
def backend() -> str:
    from .db import has_db_config, load_env
    load_env()
    forced = os.getenv("GROWTH_LAB_BACKEND", "").lower()
    if forced in ("json", "db"):
        return forced
    return "db" if has_db_config() else "json"


_table_ready = False


def _engine():
    global _table_ready
    from sqlalchemy import text
    from .db import get_engine
    eng = get_engine()
    if not _table_ready:
        with eng.begin() as c:
            c.execute(text(f"""CREATE TABLE IF NOT EXISTS {TABLE} (
                id TEXT PRIMARY KEY, title TEXT, status TEXT, data TEXT,
                created_at TEXT, created_by TEXT, updated_at TEXT, updated_by TEXT)"""))
            # 예전에 이 PC 파일에 저장해 둔 내용이 있고 DB가 비어 있으면 한 번 옮겨 둔다
            empty = c.execute(text(f"SELECT COUNT(*) FROM {TABLE}")).scalar() == 0
            if empty and STORE_PATH.exists():
                try:
                    old = json.loads(STORE_PATH.read_text(encoding="utf-8")).get("problems", [])
                except json.JSONDecodeError:
                    old = []
                for p in old:
                    c.execute(text(f"""INSERT INTO {TABLE} (id, title, status, data, created_at, created_by, updated_at, updated_by)
                                       VALUES (:id, :title, :status, :data, :ca, :cb, :ua, :ub)"""),
                              {"id": p["id"], "title": p.get("title"), "status": p.get("status"),
                               "data": json.dumps(p, ensure_ascii=False), "ca": p.get("created_at"),
                               "cb": p.get("created_by", "익명"), "ua": p.get("updated_at", p.get("created_at")),
                               "ub": p.get("updated_by", "익명")})
        _table_ready = True
    return eng


def _invalidate():
    _cache["t"] = 0.0


def _read_all() -> list[dict]:
    if _cache["data"] is not None and time.time() - _cache["t"] < CACHE_SEC:
        return _cache["data"]
    if backend() == "db":
        from sqlalchemy import text
        with _engine().connect() as c:
            rows = c.execute(text(f"SELECT data FROM {TABLE} ORDER BY created_at")).fetchall()
        probs = [json.loads(r[0]) for r in rows]
    else:
        probs = []
        if STORE_PATH.exists():
            try:
                probs = json.loads(STORE_PATH.read_text(encoding="utf-8")).get("problems", [])
            except json.JSONDecodeError:
                probs = []
    _cache.update(t=time.time(), data=probs)
    return probs


def _write_json(probs: list[dict]):
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps({"problems": probs}, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STORE_PATH)


def _upsert(p: dict):
    p = _clean(p)
    if backend() == "db":
        from sqlalchemy import text
        params = {"id": p["id"], "title": p.get("title"), "status": p.get("status"),
                  "data": json.dumps(p, ensure_ascii=False), "created_at": p.get("created_at"),
                  "created_by": p.get("created_by"), "updated_at": p.get("updated_at"),
                  "updated_by": p.get("updated_by")}
        with _engine().begin() as c:
            n = c.execute(text(f"""UPDATE {TABLE} SET title=:title, status=:status, data=:data,
                                   updated_at=:updated_at, updated_by=:updated_by WHERE id=:id"""), params).rowcount
            if not n:
                c.execute(text(f"""INSERT INTO {TABLE} (id, title, status, data, created_at, created_by, updated_at, updated_by)
                                   VALUES (:id, :title, :status, :data, :created_at, :created_by, :updated_at, :updated_by)"""),
                          params)
    else:
        probs = [x for x in _read_all() if x["id"] != p["id"]] + [p]
        probs.sort(key=lambda x: x.get("created_at") or "")
        _write_json(probs)
    _invalidate()


# ---------------------------------------------------------------------------
# 공개 함수
# ---------------------------------------------------------------------------
def load() -> dict:
    return {"problems": list(_read_all())}


def get_problem(pid: str) -> dict | None:
    if backend() == "db":
        from sqlalchemy import text
        with _engine().connect() as c:
            r = c.execute(text(f"SELECT data FROM {TABLE} WHERE id=:id"), {"id": pid}).fetchone()
        return json.loads(r[0]) if r else None
    return next((p for p in _read_all() if p["id"] == pid), None)


def add_problem(candidate: dict, source_page: str, context: dict) -> str:
    pid = "PB-" + uuid.uuid4().hex[:6].upper()
    who, now = current_author(), _now()
    _upsert({
        "id": pid, "created_at": now, "created_by": who, "updated_at": now, "updated_by": who,
        "status": "문제 후보", "source_page": source_page,
        "title": candidate.get("title", "제목 없음"), "observed": candidate, "context": context,
        "definition": {}, "hypotheses": [], "strategies": [], "experiment": {}, "notes": "",
    })
    return pid


def update_problem(pid: str, **fields) -> None:
    p = get_problem(pid)          # 최신 상태를 다시 읽고 바뀐 칸만 덮어쓴다
    if p is None:
        return
    p.update(_clean(fields))
    p["updated_at"], p["updated_by"] = _now(), current_author()
    _upsert(p)


def delete_problem(pid: str) -> None:
    if backend() == "db":
        from sqlalchemy import text
        with _engine().begin() as c:
            c.execute(text(f"DELETE FROM {TABLE} WHERE id=:id"), {"id": pid})
    else:
        _write_json([p for p in _read_all() if p["id"] != pid])
    _invalidate()


def already_saved(title: str, context: dict) -> bool:
    ctx = _clean(context)
    return any(p["title"] == title and p.get("context") == ctx for p in _read_all())
