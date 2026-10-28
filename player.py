import asyncio
import logging
import random
from pathlib import Path
from typing import Callable
from collections import deque

import discord

from config import AUDIO_EXTENSIONS, IDLE_TIMEOUT_SECONDS, MUSIC_DIR

log = logging.getLogger(__name__)

MAX_CONSECUTIVE_ERRORS = 5
MIN_VALID_AUDIO_LENGTH = 1.0

def scan_music_directory(music_dir: Path = MUSIC_DIR) -> list[Path]:
    return sorted(p for p in music_dir.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS)

def make_audio_source(path: Path) -> discord.AudioSource:
    return discord.FFmpegPCMAudio(str(path))

class GuildPlayer:
    def __init__(
        self,
        voice_client: discord.VoiceClient,
        *,
        shuffle: bool = True,
        scanner: Callable[[], list[Path]] = scan_music_directory,
        timeout_duration: float = IDLE_TIMEOUT_SECONDS,
        min_valid_audio_length: float = MIN_VALID_AUDIO_LENGTH,
        on_disconnect: Callable[[], None] | None = None,
    ):
        self.voice_client = voice_client
        self.shuffle = shuffle
        self.queue: list[Path] = []
        self.requests: deque[Path] = deque()
        self.index = 0
        self.current: Path | None = None
        self.playlist_active = False

        self.scanner = scanner
        self.timeout_duration = timeout_duration
        self.min_valid_audio_length = min_valid_audio_length
        self.on_disconnect = on_disconnect

        self.event_loop = asyncio.get_running_loop()
        self.counter = 0 # The counter exists to stop accidental callbacks from running or duplicate function calls
        self.humans_present = True
        self.timeout: asyncio.Task | None = None
        self.time_started = 0.0
        self.error_streak = 0
        self.closed = False

    def rebuild_queue(self, last_played: Path | None = None) -> None:
        tracks = list(self.scanner())
        if self.shuffle:
            random.shuffle(tracks)
            if last_played is not None and len(tracks) > 1 and tracks[0] == last_played:
                tracks[0], tracks[-1] = tracks[-1], tracks[0]
        else:
            tracks.sort()
        self.queue = tracks
        self.index = 0

    def set_shuffle(self, enabled: bool) -> None:
        self.shuffle = enabled
        remaining = self.queue[self.index:]
        if enabled:
            random.shuffle(remaining)
        else:
            remaining.sort()
        self.queue[self.index:] = remaining

    def get_upcoming(self, count: int = 10) -> list[Path]:
        upcoming = list(self.requests) + self.queue[self.index:]
        return upcoming[:count]

    async def start(self) -> None:
        self.counter += 1
        self.playlist_active = True
        self.stop_voice_client()
        self.current = None
        self.error_streak = 0
        self.rebuild_queue()
        await self.play_next()

    async def skip(self) -> Path | None:
        if self.current is None:
            return None
        skipped_audio = self.current
        self.counter += 1
        self.stop_voice_client()
        self.error_streak = 0
        await self.play_next()
        return skipped_audio

    def stop(self) -> None:
        self.counter += 1
        self.playlist_active = False
        self.stop_voice_client()
        self.current = None
        self.queue = []
        self.index = 0
        self.error_streak = 0

    def stop_voice_client(self) -> None:
        self.voice_client.stop()

    async def play_next(self) -> None:
        vc = self.voice_client
        if self.closed or not vc.is_connected():
            self.current = None
            return

        if self.requests:
            audio = self.requests.popleft()
        elif not self.playlist_active:
            self.current = None
            return
        else:
            if self.index >= len(self.queue):
                self.rebuild_queue(last_played=self.current)
                if not self.queue:
                    self.current = None
                    return
            audio = self.queue[self.index]
            self.index += 1
        self.current = audio
        self.counter += 1
        counter = self.counter

        def after_playback(error: Exception | None) -> None:
            asyncio.run_coroutine_threadsafe(
                self.on_audio_end(counter, error), self.event_loop)

        try:
            vc.play(make_audio_source(audio), after=after_playback)
        except Exception:
            log.exception(f"Could not start {audio}.")
            self.current = None
            return

        self.time_started = self.event_loop.time()
        log.info(f"Now playing: {audio.name}")
        if not self.humans_present:
            vc.pause()

    async def on_audio_end(self, count: int, error: Exception | None) -> None:
        if self.closed or count != self.counter:
            return

        too_short = self.event_loop.time() - self.time_started < self.min_valid_audio_length
        if error is not None or too_short:
            self.error_streak += 1
            log.warning(f"Track failed or ended instantly. Error number {self.error_streak} is: {error}")
            if self.error_streak >= MAX_CONSECUTIVE_ERRORS:
                log.error("Too many consecutive errors. Stopping...")
                self.playlist_active = False
                self.current = None
                return
        else:
            self.error_streak = 0
        await self.play_next()

    def on_humans_changed(self, humans_present: bool) -> None:
        if humans_present == self.humans_present:
            return
        self.humans_present = humans_present
        vc = self.voice_client

        if humans_present:
            self.cancel_timeout()
            if vc.is_paused():
                vc.resume()
        else:
            if vc.is_playing():
                vc.pause()
            if self.timeout is None:
                self.timeout = asyncio.create_task(self.create_timeout())

    def cancel_timeout(self) -> None:
        if self.timeout is not None and self.timeout is not asyncio.current_task():
            self.timeout.cancel()
        self.timeout = None

    async def add_request(self, path: Path) -> bool:
        self.requests.append(path)
        if self.current is None:
            await self.play_next()
            return True
        return False

    async def create_timeout(self) -> None:
        try:
            await asyncio.sleep(self.timeout_duration)
        except asyncio.CancelledError:
            return
        log.info(f"Channel empty for {self.timeout_duration}s. Disconnecting...")
        await self.close()
        if self.on_disconnect:
            self.on_disconnect()

    async def close(self, *, disconnect: bool = True) -> None:
        self.closed = True
        self.counter += 1
        self.requests.clear()
        self.current = None
        self.cancel_timeout()
        self.stop_voice_client()
        if disconnect and self.voice_client.is_connected():
            await self.voice_client.disconnect()
