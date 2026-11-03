"""The sign-in lock-out and its owner alert, built once per app.

``src/login_lockout.py`` (vendored) owns the policy; this module is the app's
side of it: which notifier hears about a guessing streak, and the text. The
alert goes to the fleet's ``coding alerts`` chat through the vendored
``src/notify`` Telegram notifier, from a thread so a sign-in never waits on
Telegram. The text names the app, the client address and the failure count —
never the secret that was presented.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from src.config import AlertsConfig
from src.login_lockout import LockoutAlert, LoginLockout
from src.notify import Notifier, NotifierError, TelegramConfig, build_notifier

logger = logging.getLogger(__name__)

APP_NAME = "task-os"


def notifier_for(alerts: AlertsConfig) -> Notifier | None:
    """The configured alert channel, or ``None`` when alerts are off."""
    return build_notifier(alerts.notifier, TelegramConfig(alerts.telegram_bot_token, alerts.telegram_chat_id))


def alert_text(alert: LockoutAlert) -> str:
    held = f" (+{alert.suppressed} more held back)" if alert.suppressed else ""
    return f"🚨 {APP_NAME}: {alert.failures} wrong passwords in a row from {alert.key}{held}"


def build_lockout(
    notifier: Notifier | None, *, clock: Callable[[], float] = time.monotonic,
) -> LoginLockout:
    """One ``LoginLockout`` whose alert is sent to ``notifier`` (``None`` = silent)."""

    def alert_owner(alert: LockoutAlert) -> None:
        if notifier is None:
            return
        text = alert_text(alert)

        def send() -> None:
            try:
                notifier.send_text(text)
            except NotifierError as exc:
                logger.warning("⚠️ login alert not delivered: %s", type(exc).__name__)

        threading.Thread(target=send, daemon=True, name="login-alert").start()

    return LoginLockout(on_alert=alert_owner, clock=clock)
