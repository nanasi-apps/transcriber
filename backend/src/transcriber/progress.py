from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable

ProgressFn = Callable[[int, str], None]
MessageFactory = Callable[[float], str]


def start_progress_ticker(
    on_progress: ProgressFn,
    *,
    start_pct: int,
    end_pct: int,
    base_message: str,
    interval: float = 0.75,
    ramp_seconds: float = 20.0,
    message_factory: MessageFactory | None = None,
) -> Callable[[int | None, str | None], None]:
    stop_event = threading.Event()
    started_at = time.monotonic()
    last_pct = start_pct

    def default_message(elapsed: float) -> str:
        return f"{base_message}... ({int(elapsed)}s)"

    make_message = message_factory or default_message

    def run() -> None:
        nonlocal last_pct
        span = max(0, end_pct - start_pct - 1)
        if span <= 0:
            return

        while not stop_event.wait(interval):
            elapsed = time.monotonic() - started_at
            estimated = start_pct + int(span * (1 - math.exp(-elapsed / ramp_seconds)))
            pct = min(end_pct - 1, max(last_pct + 1, estimated))
            if pct <= last_pct:
                continue

            last_pct = pct
            on_progress(pct, make_message(elapsed))

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    def stop(final_pct: int | None = None, final_message: str | None = None) -> None:
        stop_event.set()
        thread.join(timeout=1)
        if final_pct is not None and final_message is not None:
            on_progress(final_pct, final_message)

    return stop
