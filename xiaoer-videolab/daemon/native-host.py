#!/usr/bin/env python3
"""Native messaging host for Xiaoer VideoLab.
Receives {"action":"start"} from the extension and starts the daemon.
Follows Chrome Native Messaging protocol (stdin/stdout, 4-byte length prefix).
"""
import json
import os
import struct
import subprocess
import sys

HOST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(HOST_DIR)


def _send(obj):
    try:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        sys.stdout.buffer.write(struct.pack("<I", len(data)))
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
    except BrokenPipeError:
        pass


def _recv():
    raw = sys.stdin.buffer.read(4)
    if not raw or len(raw) < 4:
        return None
    length = struct.unpack("<I", raw)[0]
    if length == 0:
        return None
    return json.loads(sys.stdin.buffer.read(length).decode("utf-8"))


def main():
    msg = _recv()
    if not msg or msg.get("action") != "start":
        _send({"error": "unknown action"})
        return

    plist = os.path.expanduser("~/Library/LaunchAgents/com.xiaoer.videolab.plist")
    if os.path.isfile(plist):
        subprocess.run(["launchctl", "load", plist], capture_output=True)
        subprocess.run(["launchctl", "start", "com.xiaoer.videolab"], capture_output=True)
        _send({"ok": True, "method": "launchctl"})
    else:
        server = os.path.join(PROJECT_DIR, "daemon", "server.py")
        subprocess.Popen(
            [sys.executable, server],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _send({"ok": True, "method": "direct"})


if __name__ == "__main__":
    main()
