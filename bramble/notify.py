"""Telling the person something finished, outside the window when the PC can.

Windows: a toast. Linux: notify-send, only when a notification service is
already running (on a bare Openbox desktop there is none, and Bramble's own
window notice is enough).
"""
from __future__ import annotations

import shutil
import subprocess

from . import paths

_PS_TOAST = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$t = [Windows.UI.Notifications.ToastTemplateType]::ToastText02
$x = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent($t)
$s = $x.GetElementsByTagName('text')
$s.Item(0).AppendChild($x.CreateTextNode('{title}')) > $null
$s.Item(1).AppendChild($x.CreateTextNode('{body}')) > $null
$n = [Windows.UI.Notifications.ToastNotification]::new($x)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Bramble').Show($n)
"""


def _linux_service() -> bool:
    if not shutil.which("gdbus"):
        return False
    try:
        r = subprocess.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus",
                            "--object-path", "/org/freedesktop/DBus", "--method",
                            "org.freedesktop.DBus.NameHasOwner", "org.freedesktop.Notifications"],
                           capture_output=True, text=True, timeout=3)
        return "true" in r.stdout
    except (OSError, subprocess.SubprocessError):
        return False


def send(title: str, body: str) -> None:
    try:
        if paths.IS_WINDOWS:
            clean = lambda s: s.replace("'", "''")
            subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command",
                              _PS_TOAST.format(title=clean(title), body=clean(body))],
                             creationflags=0x08000000)
        elif shutil.which("notify-send") and _linux_service():
            subprocess.Popen(["notify-send", "-a", "bramble", title, body])
    except OSError:
        pass
