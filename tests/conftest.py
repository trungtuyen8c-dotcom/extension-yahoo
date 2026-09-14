from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("LIVE_ACTIONS_ENABLED", "false")
os.environ.setdefault("YAHOO_ADAPTER", "mock")

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.adapters.mock.adapter import MockYahooAdapter
from backend.db.models import Base


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    # SQLite bỏ qua foreign key theo mặc định — bật lên để test phát hiện
    # cùng lớp lỗi mà PostgreSQL thật sẽ chặn (vd preview_id không tồn tại).
    @event.listens_for(eng, "connect")
    def _enable_fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def db_session(engine):
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def mock_adapter():
    return MockYahooAdapter()


@pytest.fixture()
def app_client(engine, monkeypatch):
    """TestClient nối vào cùng engine sqlite in-memory qua StaticPool, và
    adapter mock dùng chung instance để test có thể seed listing."""
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    import backend.adapters.factory as factory_module
    import backend.api.deps as deps_module
    import backend.db.session as session_module

    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    monkeypatch.setattr(session_module, "SessionLocal", TestSessionLocal)

    def _get_db_override():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    # get_adapter() dùng lru_cache; xóa cache để mỗi test có adapter mock
    # riêng, rồi gọi một lần để lấy đúng instance mà các route sẽ dùng
    # (route module đã `from ... import get_adapter` nên phải dùng chung
    # instance đã cache, không thể monkeypatch tên đó ở từng module).
    factory_module.get_adapter.cache_clear()
    adapter = factory_module.get_adapter()
    assert isinstance(adapter, MockYahooAdapter)

    import backend.api.main as main_module

    main_module.app.dependency_overrides[deps_module.get_db] = _get_db_override

    client = TestClient(main_module.app)
    client.mock_adapter = adapter
    client.SessionLocal = TestSessionLocal
    yield client
    main_module.app.dependency_overrides.clear()
