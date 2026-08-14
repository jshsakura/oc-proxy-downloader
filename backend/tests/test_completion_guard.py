"""완료 처리 직전 검증 — 파일이 아닌 것을 done 으로 찍지 않는다.

호스터는 실패를 200 으로 돌려준다. 캡차, Cloudflare 챌린지, 미러 선택
페이지, 만료 안내가 전부 정상 응답으로 온다. 그걸 저장하고 done 으로
찍으면 사용자는 받은 줄 알고, 그 쓰레기가 압축 해제와 라이브러리 등록까지
그대로 흘러간다.

실측 사고: multiup.io 미러 목록 HTML 57,523 바이트가
"R-Type Tactics I-II Cosmos [01003A8019D74000][v0].part2.rar" 이름으로
done 처리됐다. 원인은 Content-Type 검사가 is_special_hoster_url() 로
게이팅돼 있어서 등록되지 않은 호스터가 통째로 빠져나간 것.
"""

import os
import tempfile

import pytest

from core.download_core import assert_downloaded_a_real_file


class _Req:
    def __init__(self, save_path="", total_size=0):
        self.save_path = save_path
        self.total_size = total_size


def _write(tmp_path, name, data: bytes):
    p = os.path.join(tmp_path, name)
    with open(p, "wb") as fh:
        fh.write(data)
    return p


def test_html_content_type_은_어느_호스터든_실패(tmp_path):
    # 예전에는 등록된 호스터일 때만 봤다. 이제 게이트가 없다.
    req = _Req(save_path=str(tmp_path / "nope.rar"))
    with pytest.raises(Exception, match="HTML/보안 확인 페이지"):
        assert_downloaded_a_real_file(req, 57523, "text/html; charset=utf-8")


def test_multiup_미러목록_페이지를_잡아낸다(tmp_path):
    # 실제 사고 재현: Content-Type 이 없어도 내용으로 잡아야 한다.
    body = (
        b'<!doctype html>\n<html lang="fr" class="has-top-menu">\n<head>\n'
        b"    <title>Telecharger ... - Upload mirroir - MultiUp.io</title>\n"
    )
    req = _Req(save_path=_write(str(tmp_path), "x.rar", body))
    with pytest.raises(Exception, match="HTML 페이지"):
        assert_downloaded_a_real_file(req, len(body), "")


@pytest.mark.parametrize(
    "body",
    [
        b"<html><body>captcha</body></html>",
        b"  \n  <!DOCTYPE HTML PUBLIC>",
        b"<?xml version='1.0'?><error/>",
        b"<head><meta http-equiv='refresh'></head>",
        b"<script>window.location='/login'</script>",
    ],
)
def test_각종_페이지_응답을_잡아낸다(tmp_path, body):
    req = _Req(save_path=_write(str(tmp_path), "x.rar", body))
    with pytest.raises(Exception):
        assert_downloaded_a_real_file(req, len(body), "")


def test_공유기_차단_안내_페이지는_그렇게_말한다(tmp_path):
    """호스터가 준 캡차와 내 공유기가 가로챈 차단 페이지는 조치가 다르다.
    실측: megaup 최종 노드가 이 179 바이트 페이지로 돌아왔다."""
    body = (
        b'<html>\n<head>\n<meta HTTP-EQUIV="REFRESH" content="0; '
        b'url=http://blocking.asus.hns.tm/?cat_id=75&domain=e7.megaupdownup.org">\n'
        b"</head>\n<body></body>\n</html>\n"
    )
    req = _Req(save_path=_write(str(tmp_path), "x.rar", body))
    with pytest.raises(Exception, match="네트워크차단페이지"):
        assert_downloaded_a_real_file(req, len(body), "")


def test_전송이_끊기면_실패(tmp_path):
    # Content-Length 를 받았는데 그보다 적게 받았으면 완료가 아니다.
    req = _Req(save_path=_write(str(tmp_path), "x.rar", b"Rar!\x1a\x07\x01\x00"), total_size=5_000_000_000)
    with pytest.raises(Exception, match="중간에 끊"):
        assert_downloaded_a_real_file(req, 1_234_567, "")


def test_정상_rar_은_통과(tmp_path):
    body = b"Rar!\x1a\x07\x01\x00" + b"\x00" * 512
    req = _Req(save_path=_write(str(tmp_path), "ok.rar", body), total_size=len(body))
    assert_downloaded_a_real_file(req, len(body), "application/octet-stream")


def test_정상_nsp_은_통과(tmp_path):
    body = b"PFS0" + b"\x00" * 4096
    req = _Req(save_path=_write(str(tmp_path), "ok.nsp", body), total_size=len(body))
    assert_downloaded_a_real_file(req, len(body), "binary/octet-stream")


def test_총크기를_모르면_크기검사는_건너뛴다(tmp_path):
    # Content-Length 를 안 주는 호스터가 있다. 그때까지 실패로 만들면 안 된다.
    body = b"Rar!\x1a\x07\x01\x00"
    req = _Req(save_path=_write(str(tmp_path), "ok.rar", body), total_size=0)
    assert_downloaded_a_real_file(req, len(body), "")


def test_파일이_없어도_예외로_죽지_않는다():
    # 경로가 비어있거나 사라진 경우 — 검사 자체가 터지면 안 된다.
    assert_downloaded_a_real_file(_Req(save_path=""), 100, "")
    assert_downloaded_a_real_file(_Req(save_path="/nonexistent/x.rar"), 100, "")


def test_HTML_이_본문_뒤쪽에_있으면_통과(tmp_path):
    # 바이너리 안에 우연히 <html 이 들어있을 수 있다. 선두만 본다.
    body = b"Rar!\x1a\x07\x01\x00" + b"\x00" * 300 + b"<html>not really</html>"
    req = _Req(save_path=_write(str(tmp_path), "ok.rar", body), total_size=len(body))
    assert_downloaded_a_real_file(req, len(body), "")
