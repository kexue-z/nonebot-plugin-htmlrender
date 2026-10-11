"""Tests for terminal state save/restore."""

from __future__ import annotations

import os
import pty
import termios

import pytest

from nonebot_plugin_htmlrender import terminal


@pytest.fixture(autouse=True)
def _reset_state():
    """Keep the module-level snapshot holder isolated between tests."""
    yield
    terminal._state.saved = None


def _raise_termios_error(_fd: int) -> None:
    raise termios.error("boom")


def test_snapshot_skips_non_tty(monkeypatch):
    monkeypatch.setattr(os, "isatty", lambda _fd: False)
    assert terminal._take_snapshot() is None


def test_snapshot_reads_tty_settings():
    master, slave = pty.openpty()
    try:
        assert terminal._take_snapshot(slave) == termios.tcgetattr(slave)
    finally:
        os.close(master)
        os.close(slave)


def test_restore_reverts_raw_mode_rewrite():
    master, slave = pty.openpty()
    try:
        terminal.save_terminal_state(slave)
        cooked = termios.tcgetattr(slave)

        # Simulate the stale-snapshot write the Playwright node driver
        # performs on its SIGINT exit path: raw mode, ISIG disabled.
        alien = termios.tcgetattr(slave)
        alien[3] &= ~(termios.ISIG | termios.ICANON | termios.ECHO)
        termios.tcsetattr(slave, termios.TCSANOW, alien)
        broken = termios.tcgetattr(slave)
        assert not broken[3] & termios.ISIG

        terminal.restore_terminal_state(slave)
        healed = termios.tcgetattr(slave)
        assert healed[3] & termios.ISIG
        assert healed[3] & termios.ICANON
        assert healed[3] & termios.ECHO
        assert healed[:4] == cooked[:4]
    finally:
        os.close(master)
        os.close(slave)


def test_restore_without_snapshot_is_noop(monkeypatch):
    def _fail(*_args, **_kwargs):
        raise AssertionError("tcsetattr must not be called")

    monkeypatch.setattr(termios, "tcsetattr", _fail)
    terminal._state.saved = None
    terminal.restore_terminal_state()


def test_restore_keeps_unchanged_terminal(monkeypatch):
    def _fail(*_args, **_kwargs):
        raise AssertionError("tcsetattr must not be called")

    master, slave = pty.openpty()
    try:
        terminal.save_terminal_state(slave)
        monkeypatch.setattr(termios, "tcsetattr", _fail)
        terminal.restore_terminal_state(slave)
    finally:
        os.close(master)
        os.close(slave)


def test_snapshot_swallows_termios_error(monkeypatch):
    monkeypatch.setattr(os, "isatty", lambda _fd: True)
    monkeypatch.setattr(termios, "tcgetattr", _raise_termios_error)
    assert terminal._take_snapshot() is None


def test_restore_skips_when_fd_not_a_tty(monkeypatch):
    def _fail(*_args, **_kwargs):
        raise AssertionError("tcgetattr/tcsetattr must not be called")

    master, slave = pty.openpty()
    try:
        terminal.save_terminal_state(slave)
        monkeypatch.setattr(os, "isatty", lambda _fd: False)
        monkeypatch.setattr(termios, "tcgetattr", _fail)
        monkeypatch.setattr(termios, "tcsetattr", _fail)
        terminal.restore_terminal_state(slave)
    finally:
        os.close(master)
        os.close(slave)


def test_restore_swallows_termios_error(monkeypatch):
    master, slave = pty.openpty()
    try:
        terminal._state.saved = termios.tcgetattr(slave)
    finally:
        os.close(master)
        os.close(slave)

    monkeypatch.setattr(os, "isatty", lambda _fd: True)
    monkeypatch.setattr(termios, "tcgetattr", _raise_termios_error)
    terminal.restore_terminal_state()
