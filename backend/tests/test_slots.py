# -*- coding: utf-8 -*-
"""A queued download must not hold a database connection while it waits.

Under ``NullPool`` every held session is a real open file. A queue of 65 items
mostly *waiting* therefore spent its file descriptors on tasks that were doing
nothing, and one row (id 2369) died on
``sqlite3.OperationalError: unable to open database file`` during that run.
"""

import asyncio

import pytest

from core.slots import slot_without_session


class FakeSession:
    """Records when it was closed, so the ordering can be asserted."""

    def __init__(self, clock):
        self._clock = clock
        self.close_count = 0
        self.closed_at = None

    def close(self):
        self.close_count += 1
        self.closed_at = self._clock()


class Clock:
    """Monotonic tick counter — real time is too coarse and too flaky here."""

    def __init__(self):
        self.now = 0

    def tick(self):
        self.now += 1
        return self.now

    def __call__(self):
        return self.now


@pytest.mark.asyncio
async def test_the_session_is_closed_before_the_wait_begins():
    clock = Clock()
    db = FakeSession(clock)
    busy = asyncio.Semaphore(1)
    await busy.acquire()  # someone else holds the only slot

    acquired_at = []

    async def waiter():
        async with slot_without_session(db, busy):
            acquired_at.append(clock.tick())

    task = asyncio.create_task(waiter())
    await asyncio.sleep(0)  # let it reach the wait
    assert db.close_count == 1, "the session must be closed before parking"
    assert not acquired_at, "it should still be waiting"

    busy.release()
    await task

    assert db.closed_at < acquired_at[0]


@pytest.mark.asyncio
async def test_the_slot_is_released_on_the_way_out():
    db = FakeSession(Clock())
    semaphore = asyncio.Semaphore(1)

    async with slot_without_session(db, semaphore):
        assert semaphore._value == 0

    assert semaphore._value == 1


@pytest.mark.asyncio
async def test_the_slot_is_released_even_when_the_body_raises():
    db = FakeSession(Clock())
    semaphore = asyncio.Semaphore(1)

    with pytest.raises(RuntimeError):
        async with slot_without_session(db, semaphore):
            raise RuntimeError("download blew up")

    assert semaphore._value == 1, "a failed download must not leak its slot"


@pytest.mark.asyncio
async def test_semaphores_are_acquired_in_the_order_given():
    # The host queue must be taken before the global ceiling: a task waiting on
    # the ceiling then holds only its own host's slot and cannot block another
    # host from starting.
    db = FakeSession(Clock())
    host = asyncio.Semaphore(1)
    ceiling = asyncio.Semaphore(1)
    await ceiling.acquire()  # the global cap is full

    async def waiter():
        async with slot_without_session(db, host, ceiling):
            pass

    task = asyncio.create_task(waiter())
    await asyncio.sleep(0)

    assert host._value == 0, "the host slot is held while waiting on the ceiling"
    ceiling.release()
    await task
    assert host._value == 1


@pytest.mark.asyncio
async def test_no_semaphores_still_closes_the_session():
    db = FakeSession(Clock())
    async with slot_without_session(db):
        pass
    assert db.close_count == 1
