"""Loop-level pins for the ``overnight`` command's window semantics.

These exercise the market-clock loop in src/cli.py with a fake broker and
a real SessionStore (tmp sqlite).  They pin the 2026-11-13 reliability fix
after a week in which EVERY GitHub schedule event was delivered 2.5-7.5h
late (platform-wide scheduler degradation), which made the failure modes
below observable:

  1. a post-close run with a stale (previous-day) pending entry submits a
     resting market exit and logs it -- ``is_open`` is no longer required;
  2. a post-close run with nothing pending exits fast instead of sleeping
     into the job timeout (late delivery becomes a cheap visible no-op);
  3. a same-day overnight entry is NEVER exited by the same-day cycle
     (regression pin for the latent same-run instant-exit bug: the loop
     re-wakes 60s after the entry block while the market is still open,
     and without the ``entered_today`` gate the exit block sold the
     entries the same run had just submitted).

Offline only: patched clock/broker/settings, tmp session store.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import src.cli as cli
from src.store.session import SessionStore


class _LoopSlept(Exception):
    """Raised by the patched sleep to prove the loop reached a sleep."""


# All fake-clock timestamps are computed from REAL now so seconds_until()
# (left un-patched by design) always sees the intended positive gaps.
# Hardcoded dates age overnight and flip branch decisions (observed
# 2026-11-14: the "8h ahead" next_close became past and the window-far
# guard stopped firing).
_REAL_NOW = datetime.now(timezone.utc)
_FIXED_NOW = _REAL_NOW.replace(hour=20, minute=55, second=0, microsecond=0)
if _REAL_NOW.hour < 21:  # keep trade_date self-consistent, never in the future
    _FIXED_NOW = (_REAL_NOW - timedelta(days=1)).replace(
        hour=20, minute=55, second=0, microsecond=0)
_TODAY = _FIXED_NOW.date().isoformat()
_YESTERDAY = (_FIXED_NOW.date() - timedelta(days=1)).isoformat()


class _FakeBroker:
    def __init__(self, positions):
        self.positions = positions
        self.submitted = []

    def get_positions(self):
        return [dict(row) for row in self.positions]

    def submit_limit_orders(self, plans):
        for plan in plans:
            self.submitted.append(plan)
        return [{"status": "queued"}] * len(plans)


class _FakeSettings:
    watchlist = ["AAPL"]
    alpaca_api_key = "test-key"
    alpaca_secret_key = "test-secret"
    paper_only = True


def _seed(store: SessionStore, trade_date: str, ticker: str = "AAPL") -> None:
    store.log_action(
        trade_date=trade_date, ticker=ticker, side="buy",
        notional=1000.0, kind="overnight_entry",
    )


def _patch(monkeypatch, broker: _FakeBroker, store: SessionStore,
           clock: dict) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(cli, "AlpacaClient",
                        lambda key, secret, paper_only: broker)
    monkeypatch.setattr(cli, "_fetch_clock", lambda broker_: dict(clock))
    monkeypatch.setattr(cli, "SessionStore", lambda db_path: store)
    monkeypatch.setattr(cli, "_store",
                        lambda: SimpleNamespace(log_decision=lambda *a, **k: None))
    monkeypatch.setattr(cli, "_exit_reference_prices",
                        lambda tickers: {"AAPL": 250.0})
    monkeypatch.setattr(cli, "datetime",
                        SimpleNamespace(now=lambda tz=None: _FIXED_NOW))

    def _no_sleep(seconds):
        raise _LoopSlept(f"loop slept {seconds}s (patched)")

    monkeypatch.setattr(cli, "_sleep_with_chunks", _no_sleep)
    monkeypatch.setenv("OVERNIGHT_STATS_PATH", "does/not/exist.json")


def _actions_of_kind(store: SessionStore, kind: str) -> list:
    rows = []
    for day in (_YESTERDAY, _TODAY):
        rows.extend(a for a in store.actions_for_date(day)
                    if a.get("kind") == kind)
    return rows


_CLOSED_CLOCK = {
    "is_open": False,
    "next_open": (_REAL_NOW + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "next_close": (_REAL_NOW + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
}
_OPEN_CLOCK = {
    "is_open": True,
    "next_close": (_REAL_NOW + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "next_open": (_REAL_NOW + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
}
_FAR_OPEN_CLOCK = {
    "is_open": True,
    "next_close": (_REAL_NOW + timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "next_open": (_REAL_NOW + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
}


def test_postclose_stale_entry_exits_via_resting_order(tmp_path, monkeypatch, capsys):
    """Yesterday's entry + missed morning exit + post-close run -> resting
    market sell submitted and logged (``is_open`` not required)."""
    store = SessionStore(db_path=tmp_path / "decisions.sqlite3")
    _seed(store, _YESTERDAY)
    broker = _FakeBroker([{"symbol": "AAPL", "qty": "10"}])
    _patch(monkeypatch, broker, store, _CLOSED_CLOCK)

    with pytest.raises(_LoopSlept):
        cli.overnight(tickers="AAPL", max_names=5, entry_before_close_min=10,
                      exit_after_open_utc="13:35", submit=True, no_wait=False)

    assert len(broker.submitted) == 1
    order = broker.submitted[0]
    assert order.side == "sell"
    assert order.ticker == "AAPL"
    assert float(order.quantity) == pytest.approx(10.0)

    exits = _actions_of_kind(store, "overnight_exit")
    assert len(exits) == 1
    assert exits[0]["ticker"] == "AAPL"
    assert exits[0]["trade_date"] == _TODAY

    out = capsys.readouterr().out
    assert "overnight exit submitted: AAPL" in out


def test_postclose_noop_breaks_without_sleeping(tmp_path, monkeypatch, capsys):
    """Closed market, nothing held -> the run prints its reason and exits
    without a single sleep (cheap visible no-op, no timeout burn)."""
    store = SessionStore(db_path=tmp_path / "decisions.sqlite3")
    broker = _FakeBroker([])
    _patch(monkeypatch, broker, store, _CLOSED_CLOCK)

    cli.overnight(tickers="AAPL", max_names=5, entry_before_close_min=10,
                  exit_after_open_utc="13:35", submit=True, no_wait=False)
    # must return; a sleep raises _LoopSlept

    out = capsys.readouterr().out
    assert "post-close no-op" in out
    assert broker.submitted == []


def test_openmarket_nothing_pending_window_far_breaks(tmp_path, monkeypatch, capsys):
    """Open market, nothing held, entry window hours away -> cheap early
    exit instead of sleeping out the job timeout (no-op morning runs)."""
    store = SessionStore(db_path=tmp_path / "decisions.sqlite3")
    broker = _FakeBroker([])
    _patch(monkeypatch, broker, store, _FAR_OPEN_CLOCK)

    cli.overnight(tickers="AAPL", max_names=5, entry_before_close_min=10,
                  exit_after_open_utc="13:35", submit=True, no_wait=False)

    out = capsys.readouterr().out
    assert "entry window far" in out
    assert broker.submitted == []


def test_same_day_entry_never_same_run_exit(tmp_path, monkeypatch, capsys):
    """Regression pin: entries logged TODAY (evening primary) must not be
    sold by a same-day wake, even with the market open, exit window due,
    and positions held.  On the pre-fix code this test FAILS (the loop
    sold the entries minutes after buying them)."""
    store = SessionStore(db_path=tmp_path / "decisions.sqlite3")
    _seed(store, _TODAY)
    broker = _FakeBroker([{"symbol": "AAPL", "qty": "10"}])
    _patch(monkeypatch, broker, store, _OPEN_CLOCK)

    with pytest.raises(_LoopSlept):   # loop keeps sleeping; no fast exit
        cli.overnight(tickers="AAPL", max_names=5, entry_before_close_min=10,
                      exit_after_open_utc="13:35", submit=True, no_wait=False)

    assert broker.submitted == []
    assert _actions_of_kind(store, "overnight_exit") == []
