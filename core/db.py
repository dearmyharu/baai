"""DB 연결 공통 엔진.

접속 정보는 아래 순서로 찾는다.
1. DATABASE_URL  (예: postgresql://user:pw@host:6543/postgres)
2. DB_USER / DB_PASSWORD / DB_HOST / DB_PORT / DB_NAME / DB_SSLMODE
값은 .env(로컬) 또는 Streamlit Cloud 의 Secrets(배포)에서 읽는다.
Streamlit Cloud 는 Secrets 의 최상위 값을 환경변수로도 넣어주므로 os.getenv 로 그대로 읽힌다.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_env():
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    for p in (ROOT / "dashboard" / ".env", ROOT / "dashboard_test" / ".env"):
        if p.exists():
            load_dotenv(p, override=False)
    _load_streamlit_secrets()


def _load_streamlit_secrets():
    """로컬에서 .streamlit/secrets.toml 을 쓰는 경우도 환경변수로 옮겨 둔다."""
    try:
        import streamlit as st
        for k, v in st.secrets.items():
            if isinstance(v, (str, int, float)) and k not in os.environ:
                os.environ[k] = str(v)
    except Exception:
        pass


def has_db_config() -> bool:
    load_env()
    return bool(os.getenv("DATABASE_URL") or (os.getenv("DB_HOST") and os.getenv("DB_USER")))


@lru_cache(maxsize=1)
def get_engine():
    load_env()
    from sqlalchemy import create_engine
    url = os.getenv("DATABASE_URL")
    if url:
        if url.startswith("postgres://"):
            url = "postgresql+psycopg2://" + url[len("postgres://"):]
        elif url.startswith("postgresql://"):
            url = "postgresql+psycopg2://" + url[len("postgresql://"):]
        kwargs = {}
        if url.startswith("postgresql"):
            kwargs["connect_args"] = {"sslmode": os.getenv("DB_SSLMODE", "require")}
        return create_engine(url, pool_pre_ping=True, **kwargs)
    from sqlalchemy.engine import URL
    url = URL.create(
        drivername="postgresql+psycopg2",
        username=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"), port=int(os.getenv("DB_PORT", "5432")),
        database=os.getenv("DB_NAME", "postgres"),
    )
    return create_engine(url, connect_args={"sslmode": os.getenv("DB_SSLMODE", "require")}, pool_pre_ping=True)
