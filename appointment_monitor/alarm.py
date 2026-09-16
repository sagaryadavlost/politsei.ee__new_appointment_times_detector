from __future__ import annotations

import os
import platform
import subprocess
import threading
import time

import config


class AlarmManager:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._player: subprocess.Popen | None = None

    def start(self) -> None:
        self.stop()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._stop_player()
        self._thread = None

    def test(self) -> None:
        self.start()
        threading.Timer(6, self.stop).start()

    def notify(self, title: str, message: str) -> None:
        if platform.system() == "Darwin":
            # Escape double quotes for AppleScript
            escaped_message = message.replace('"', '\\"')
            escaped_title = title.replace('"', '\\"')
            script = f'display notification "{escaped_message}" with title "{escaped_title}"'
            subprocess.run(["osascript", "-e", script], check=False)

    def _loop(self) -> None:
        sound_file = config.ALARM_SOUND_FILE
        repeat_count = config.ALARM_REPEAT_COUNT
        repeat_interval = config.ALARM_REPEAT_INTERVAL_SECONDS
        
        for i in range(repeat_count):
            if self._stop.is_set():
                break
            if platform.system() == "Darwin":
                # afplay on macOS can play MP3, AIFF, WAV, etc.
                if os.path.exists(sound_file):
                    self._play(["afplay", sound_file])
                else:
                    # Fallback to system sound
                    self._play(["afplay", "/System/Library/Sounds/Glass.aiff"])
            else:
                # On Linux/Windows, try to use available players for MP3
                if os.path.exists(sound_file):
                    self._play_sound_cross_platform(sound_file)
                else:
                    # Fallback to terminal bell
                    print("\a", end="", flush=True)
            
            # Wait for the repeat interval, but check for stop signal more frequently
            for _ in range(int(repeat_interval * 2)):  # Check every 0.5 seconds
                if self._stop.is_set():
                    break
                time.sleep(0.5)

    def _play(self, command: list[str]) -> None:
        try:
            self._player = subprocess.Popen(command)
            while self._player.poll() is None:
                if self._stop.is_set():
                    self._stop_player()
                    return
                time.sleep(0.1)
        except FileNotFoundError:
            return
        finally:
            self._player = None

    def _stop_player(self) -> None:
        player = self._player
        if player is None or player.poll() is not None:
            return
        player.terminate()
        try:
            player.wait(timeout=1)
        except subprocess.TimeoutExpired:
            player.kill()

    def _play_sound_cross_platform(self, sound_file: str) -> None:
        """Play sound file on Linux/Windows using available players."""
        system = platform.system()
        try:
            if system == "Linux":
                # Try common Linux audio players
                for player in ["mpg123", "ffplay", "aplay", "paplay"]:
                    try:
                        self._play([player, sound_file])
                        return
                    except FileNotFoundError:
                        continue
            elif system == "Windows":
                # Use Windows built-in media player via PowerShell
                self._play([
                    "powershell", "-c",
                    f'(New-Object Media.SoundPlayer "{sound_file}").PlaySync()'
                ])
        except Exception:
            # Ultimate fallback
            print("\a", end="", flush=True)

