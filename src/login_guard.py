"""The sign-in lock-out and its owner alert, built once per app.

``src/login_lockout.py`` (vendored) owns the policy and ``src/login_alert.py``
(vendored) the alert's text, send thread and logged outcome; this module is
the app's side: which notifier hears about a guessing streak. The alert goes
to the fleet's ``coding alerts`` chat through the vendored ``src/notify``
Telegram notifier.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from src.config import AlertsConfig
from src.login_alert import build_login_alert
from src.login_lockout import LoginLockout
from src.notify import Notifier, TelegramConfig, build_notifier

APP_NAME = "task-os"


def notifier_for(alerts: AlertsConfig) -> Notifier | None:
    """The configured alert channel, or ``None`` when alerts are off."""
    return build_notifier(alerts.notifier, TelegramConfig(alerts.telegram_bot_token, alerts.telegram_chat_id))


def build_lockout(
    notifier: Notifier | None, *, clock: Callable[[], float] = time.monotonic,
) -> LoginLockout:
    """One ``LoginLockout`` whose alert is sent to ``notifier`` (``None`` = logged as unconfigured)."""
    return LoginLockout(on_alert=build_login_alert(APP_NAME, lambda: notifier), clock=clock)
