import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core import app_factory


@pytest.mark.asyncio
async def test_ambiguous_legacy_blocks_are_relabelled_without_touching_real_blocks(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Session = sessionmaker(bind=engine)
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE download_requests (
                id INTEGER PRIMARY KEY,
                error TEXT,
                failure_kind VARCHAR,
                next_retry_at DATETIME
            )
        """))
        conn.execute(text("""
            INSERT INTO download_requests (id, error, failure_kind)
            VALUES
              (1, '다운로드 폼을 찾을 수 없음', 'blocked'),
              (2, '1fichier 차단: 일일 무료 다운로드 한도 초과', 'blocked'),
              (3, '다운로드 링크를 찾을 수 없음', 'blocked')
        """))

    db = Session()
    monkeypatch.setattr(app_factory, "get_db", lambda: iter([db]))
    await app_factory._run_migrations()

    rows = db.execute(text(
        "SELECT id, failure_kind, error FROM download_requests ORDER BY id"
    )).fetchall()
    assert {row.id: row.failure_kind for row in rows} == {
        1: "unknown", 2: "blocked", 3: "unknown"
    }
    assert "원인 미확인" in rows[0].error
    assert rows[1].error == "1fichier 차단: 일일 무료 다운로드 한도 초과"
    assert "원인 미확인" in rows[2].error
    db.close()
