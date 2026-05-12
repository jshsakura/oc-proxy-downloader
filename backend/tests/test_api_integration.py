# -*- coding: utf-8 -*-
import pytest
from fastapi.testclient import TestClient
from core.app_factory import create_app
from core.db import engine, SessionLocal
from core.models import Base

@pytest.fixture(scope="module")
def app():
    # 테스트용 앱 생성
    application = create_app()
    return application

@pytest.fixture(scope="module")
def client(app):
    return TestClient(app)

def test_api_root_or_frontend_serving(client):
    """루트 경로 접속 시 200 응답 확인 (SPA 특성상 index.html 혹은 JSON)"""
    response = client.get("/")
    assert response.status_code == 200

def test_api_locales(client):
    """다국어 API 작동 확인"""
    response = client.get("/api/locales/ko.json")
    if response.status_code == 200:
        data = response.json()
        assert "title" in data
    else:
        # 파일이 없을 수도 있으므로 (빌드 전) 404도 허용하되, 에러는 아니어야 함
        assert response.status_code in (200, 404)

def test_api_settings_get(client):
    """설정 조회 API 작동 확인"""
    response = client.get("/api/settings")
    assert response.status_code == 200
    data = response.json()
    assert "download_path" in data

def test_api_history_empty(client):
    """히스토리 API 작동 확인"""
    response = client.get("/api/history/")
    assert response.status_code == 200
    data = response.json()
    assert "history" in data
    assert isinstance(data["history"], list)
