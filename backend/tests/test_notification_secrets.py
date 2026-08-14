# -*- coding: utf-8 -*-
"""알림 경로가 봇 토큰을 로그로 흘리지 않는지 확인한다.

텔레그램 API 는 봇 토큰을 URL 경로에 담는다(``/bot<token>/sendMessage``).
요청 URL 을 그대로 찍으면 알림 한 번마다 자격증명이 컨테이너 로그에 남고,
로그는 대개 아무나 본다. 실측: 다운로드 실패 알림 세 건에 토큰이 그대로
찍혀 있었다.
"""

import threading

import services.notification_service as ns


class _Resp:
    status_code = 200
    text = '{"ok":true,"result":{"message_id":1}}'


def test_봇_토큰이_로그에_찍히지_않는다(monkeypatch, capsys):
    token = "937742375:AAFCdHbX3QEjMz5Lfi45YeUojB-rujQ5PtY"
    monkeypatch.setattr(ns, "get_config", lambda: {
        "telegram_bot_token": token,
        "telegram_chat_id": "915733248",
        "telegram_notify_failure": True,
    })
    sent = {}

    def fake_post(url, json=None, timeout=None):
        sent["url"] = url
        return _Resp()

    monkeypatch.setattr(ns.requests, "post", fake_post)
    # 전송은 데몬 스레드에서 돈다. 출력까지 확인해야 하므로 그 자리에서 실행한다.
    monkeypatch.setattr(
        threading, "Thread",
        lambda target, daemon=None: type("_T", (), {"start": staticmethod(target)}),
    )

    ns.send_telegram_notification("game.rar", "failed", error="네트워크차단페이지")

    assert token in sent["url"], "토큰은 요청에는 그대로 들어가야 한다"
    assert token not in capsys.readouterr().out
