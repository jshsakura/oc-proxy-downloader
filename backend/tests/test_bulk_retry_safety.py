from datetime import datetime, timedelta
from types import SimpleNamespace

from api.routes.downloads import _one_retry_per_idle_host


def _request(id, host, when):
    return SimpleNamespace(
        id=id,
        original_url=f"https://{host}/file-{id}",
        url=None,
        requested_at=when,
    )


def test_bulk_retry_selects_one_per_idle_host():
    now = datetime.now()
    active = [_request(1, "1fichier.com", now)]
    candidates = [
        _request(2, "1fichier.com", now),
        _request(3, "datanodes.to", now + timedelta(seconds=1)),
        _request(4, "datanodes.to", now),
        _request(5, "other.example", now),
    ]

    assert [req.id for req in _one_retry_per_idle_host(candidates, active)] == [4, 5]
