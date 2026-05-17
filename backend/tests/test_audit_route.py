# -*- coding: utf-8 -*-
"""audit 라우트의 락 관리 / 필터 셀렉터 단위 테스트.

가장 중요한 회귀 방지:
- 두 요청이 동시에 들어와도 한쪽만 통과 (락 race condition #2).
- 빈 결과나 예외 시 락이 항상 해제되어 다음 요청이 받아들여짐.
- ``_select_targets`` 가 ids/status/failure_kinds/since/until 필터를 AND 결합.
"""

import asyncio
import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import Base, DownloadRequest, StatusEnum
from api.routes.audit import (
    AuditRequest,
    _select_targets,
    _audit_lock,
    start_audit,
)


@pytest.fixture()
def memory_db():
    """단위 테스트용 격리된 in-memory SQLite 세션 + 샘플 데이터."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    now = datetime.datetime(2026, 5, 1, 12, 0, 0)
    sample_rows = [
        DownloadRequest(
            url="https://1fichier.com/?a", status=StatusEnum.failed,
            failure_kind="dead", requested_at=now,
        ),
        DownloadRequest(
            url="https://1fichier.com/?b", status=StatusEnum.failed,
            failure_kind="cloudflare", requested_at=now + datetime.timedelta(days=1),
        ),
        DownloadRequest(
            url="https://1fichier.com/?c", status=StatusEnum.stopped,
            failure_kind=None, requested_at=now + datetime.timedelta(days=2),
        ),
        DownloadRequest(
            url="https://1fichier.com/?d", status=StatusEnum.done,
            failure_kind=None, requested_at=now + datetime.timedelta(days=3),
        ),
    ]
    for r in sample_rows:
        db.add(r)
    db.commit()
    yield db
    db.close()


@pytest.fixture(autouse=True)
def reset_audit_lock():
    """매 테스트 후 잠긴 락 해제 — 글로벌 싱글톤이라 누수되면 다음 테스트 깨짐."""
    yield
    if _audit_lock.locked():
        _audit_lock.release()


class TestSelectTargets:
    def test_default_filter_returns_failed_and_stopped(self, memory_db):
        # failed (a, b) + stopped (c) — done (d) 제외
        ids = _select_targets(AuditRequest(), memory_db)
        assert len(ids) == 3

    def test_ids_overrides_other_filters(self, memory_db):
        # status=done 인 d 만 id 지정 — 다른 status 필터 무시
        d = memory_db.query(DownloadRequest).filter_by(
            url="https://1fichier.com/?d"
        ).first()
        req = AuditRequest(ids=[d.id], status_filter=["failed"])
        assert _select_targets(req, memory_db) == [d.id]

    def test_failure_kinds_filter(self, memory_db):
        req = AuditRequest(failure_kinds=["dead"])
        ids = _select_targets(req, memory_db)
        # dead 만 매칭 — a 1개
        rows = memory_db.query(DownloadRequest).filter(
            DownloadRequest.id.in_(ids)
        ).all()
        assert all(r.failure_kind == "dead" for r in rows)
        assert len(rows) == 1

    def test_since_until_filter_narrows_period(self, memory_db):
        since = datetime.datetime(2026, 5, 2, 0, 0, 0)
        until = datetime.datetime(2026, 5, 3, 23, 59, 59)
        req = AuditRequest(since=since, until=until)
        ids = _select_targets(req, memory_db)
        # b (5/2), c (5/3) — done 인 d 제외, a (5/1) 도 제외
        rows = memory_db.query(DownloadRequest).filter(
            DownloadRequest.id.in_(ids)
        ).all()
        assert len(rows) == 2
        for r in rows:
            assert since <= r.requested_at <= until

    def test_only_with_failure_kind_excludes_null(self, memory_db):
        req = AuditRequest(only_with_failure_kind=True)
        ids = _select_targets(req, memory_db)
        rows = memory_db.query(DownloadRequest).filter(
            DownloadRequest.id.in_(ids)
        ).all()
        # c 는 failure_kind=NULL 이라 제외
        assert all(r.failure_kind is not None for r in rows)

    def test_failure_kinds_takes_precedence_over_only_with(self, memory_db):
        # failure_kinds 가 지정되면 only_with_failure_kind 무시 (이미 더 좁힘)
        req = AuditRequest(
            failure_kinds=["cloudflare"], only_with_failure_kind=False
        )
        ids = _select_targets(req, memory_db)
        rows = memory_db.query(DownloadRequest).filter(
            DownloadRequest.id.in_(ids)
        ).all()
        assert len(rows) == 1
        assert rows[0].failure_kind == "cloudflare"

    def test_limit_caps_result(self, memory_db):
        req = AuditRequest(limit=1)
        ids = _select_targets(req, memory_db)
        assert len(ids) == 1


class TestAuditLockRace:
    """결함 #2 회귀 방지 — 동시 요청 시 한 쪽만 통과해야 함.

    실제 백그라운드 태스크는 module-level ``SessionLocal`` 을 쓰므로 단위 테스트
    환경에서 곧장 크래시한다 (테이블 없음). 그래서 락을 수동으로 잡고/풀어서
    ``start_audit`` 의 게이팅 로직만 직접 검증.
    """

    @pytest.mark.asyncio
    async def test_locked_state_returns_409(self, memory_db):
        # 외부에서 락이 이미 잡혀있다고 가정
        await _audit_lock.acquire()
        try:
            with pytest.raises(HTTPException) as exc:
                await start_audit(AuditRequest(), memory_db)
            assert exc.value.status_code == 409
            assert exc.value.detail == "audit_already_running"
        finally:
            _audit_lock.release()

    @pytest.mark.asyncio
    async def test_no_targets_releases_lock(self):
        """대상 0건 응답 직후엔 락이 풀려있어야 다음 요청을 받을 수 있다."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        db.add(DownloadRequest(url="https://x", status=StatusEnum.done))
        db.commit()

        # 락이 안 잡힌 상태에서 시작 → 0건 → 락 즉시 해제
        first = await start_audit(AuditRequest(), db)
        assert first["started"] is False
        assert first["total"] == 0
        assert not _audit_lock.locked()

        # 다음 호출도 같은 결과로 통과 (락 누수 없음)
        second = await start_audit(AuditRequest(), db)
        assert second["started"] is False
        assert not _audit_lock.locked()
        db.close()
