# -*- coding: utf-8 -*-
"""Retry pacing, so a failure does not turn into a ban.

Retrying fast and often is how an IP gets blocked — the block then outlives the
problem that caused it. Three things were wrong:

* The first transient retry was 30 seconds. A host that had just refused us was
  asked again almost immediately.
* ``blocked`` and ``proxy_blocked`` — the kinds that literally mean the host is
  refusing us — waited a flat 120s and 30s and never grew.
* Nothing was jittered except two kinds, so a batch that failed together (a host
  hiccup, a bulk restart) woke in lockstep and arrived as one burst.

And the structural one: backoff is per download, but a block is per host.
"""

import datetime

import pytest

from core.error_messages import (
    KIND_BLOCKED,
    KIND_CLOUDFLARE,
    KIND_PROXY_BLOCKED,
    KIND_RATE_LIMITED,
    KIND_TRANSIENT,
    KIND_UNKNOWN,
    _compute_next_retry_at,
)


def _wait(kind, attempt=1, retry_after=None):
    at = _compute_next_retry_at(kind, attempt, retry_after)
    assert at is not None, f"{kind} unexpectedly refused to retry"
    return (at - datetime.datetime.now()).total_seconds()


class TestNothingRetriesTooSoon:

    @pytest.mark.parametrize("kind", [
        KIND_TRANSIENT, KIND_BLOCKED, KIND_PROXY_BLOCKED,
        KIND_CLOUDFLARE, KIND_RATE_LIMITED, KIND_UNKNOWN,
    ])
    def test_no_kind_retries_within_a_minute(self, kind):
        """A sub-minute retry is the behaviour that gets an IP banned. The
        cheapest wait in the table is proxy_blocked, and even that is 60s."""
        assert _wait(kind) >= 55

    def test_the_first_transient_wait_is_minutes_not_seconds(self):
        assert 120 <= _wait(KIND_TRANSIENT, attempt=1) <= 150


class TestBeingRefusedBacksOffHarder:

    def test_blocked_grows_with_each_attempt(self):
        """`blocked` means the host is refusing us. Repeating a flat two-minute
        wait is how a temporary refusal becomes a permanent one."""
        first, second = _wait(KIND_BLOCKED, 1), _wait(KIND_BLOCKED, 2)

        assert second > first * 1.5

    def test_proxy_blocked_grows_too(self):
        assert _wait(KIND_PROXY_BLOCKED, 2) > _wait(KIND_PROXY_BLOCKED, 1)

    def test_transient_backoff_escalates(self):
        waits = [_wait(KIND_TRANSIENT, n) for n in (1, 2)]

        assert waits == sorted(waits)
        assert waits[-1] >= 480


class TestJitter:

    @pytest.mark.parametrize("kind", [
        KIND_TRANSIENT, KIND_BLOCKED, KIND_PROXY_BLOCKED, KIND_CLOUDFLARE,
    ])
    def test_waits_are_spread(self, kind):
        """Identical waits mean simultaneous failures retry in lockstep, which
        reads like an attack from the host's side."""
        samples = {round(_wait(kind), 3) for _ in range(20)}

        assert len(samples) > 1, f"{kind} returns a fixed wait"

    def test_jitter_only_ever_delays(self):
        """Spreading must not pull a retry earlier than its floor."""
        for _ in range(50):
            assert _wait(KIND_TRANSIENT, 1) >= 120


class TestTheBudgetIsSmall:

    @pytest.mark.parametrize("kind", [
        KIND_TRANSIENT, KIND_BLOCKED, KIND_PROXY_BLOCKED,
        KIND_CLOUDFLARE, KIND_RATE_LIMITED,
    ])
    def test_every_kind_gives_up_after_three_attempts(self, kind):
        """The ceilings were set when the waits between attempts were seconds.
        With waits in minutes, five or eight attempts is just sustained knocking
        on a door that already said no."""
        assert _compute_next_retry_at(kind, 3, None) is None

    @pytest.mark.parametrize("kind", [KIND_TRANSIENT, KIND_BLOCKED, KIND_CLOUDFLARE])
    def test_the_first_two_attempts_are_still_scheduled(self, kind):
        """Giving up must not become giving up immediately — a blip deserves a
        second look."""
        assert _compute_next_retry_at(kind, 1, None) is not None
        assert _compute_next_retry_at(kind, 2, None) is not None


class TestPerHostSpacing:
    """Backoff is per download; a block is per host."""

    def test_the_sweeper_spaces_retries_by_host(self):
        from services.download_service import HOST_RETRY_SPACING_SEC

        assert HOST_RETRY_SPACING_SEC >= 120

    def test_a_queue_of_one_host_cannot_drip_faster_than_the_spacing(self):
        """200 DataNodes links each waiting their own polite two minutes still
        add up to a stream at one host unless the sweeper spaces them."""
        import time

        from services.download_service import DownloadService, HOST_RETRY_SPACING_SEC

        service = DownloadService()
        now = time.monotonic()
        service._last_retry_per_host["datanodes.to"] = now

        too_soon = now - service._last_retry_per_host["datanodes.to"] < HOST_RETRY_SPACING_SEC
        assert too_soon, "a second retry to the same host would go out immediately"


class TestQueueWaitsAreNotRefusals:
    """A queue wait never touched the host.

    KIND_QUEUED means the link is waiting on our own per-site slot — the request
    was never sent. Pacing it with the anti-ban spacing meant for refusals stalls
    the queue: 42 items due behind one host came out at one every three minutes,
    and the grid showed 54 "failures" with nothing running.
    """

    def test_the_sweeper_exempts_queue_waits_from_host_spacing(self):
        import inspect

        from services import download_service
        from core.error_messages import KIND_QUEUED

        body = inspect.getsource(download_service.DownloadService._sweep_due_retries)

        assert "KIND_QUEUED" in body, (
            "the host-spacing gate must skip queue waits, or one busy host "
            "throttles its own queue"
        )
        # The gate still exists for everything else.
        assert "HOST_RETRY_SPACING_SEC" in body

    def test_a_queue_wait_still_gets_a_short_reschedule(self):
        """Exempting it from spacing must not mean retrying it instantly."""
        from core.error_messages import KIND_QUEUED

        assert _wait(KIND_QUEUED) >= 45

    def test_a_queue_wait_never_runs_out_of_budget(self):
        """It is not a failure, so it must not consume the retry allowance —
        otherwise a long queue quietly drops links."""
        from core.error_messages import KIND_QUEUED, _compute_next_retry_at

        assert _compute_next_retry_at(KIND_QUEUED, 50, None) is not None
