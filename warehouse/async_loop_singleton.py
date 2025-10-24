# async_loop_singleton.py
import asyncio, threading
from typing import Callable

class _LoopHolder:
    def __init__(self):
        self.loop = None
        self.thread = None

_GLOBAL = _LoopHolder()

def get_global_loop() -> asyncio.AbstractEventLoop:
    """Start a single asyncio loop in a background thread and return it."""
    if _GLOBAL.loop:
        return _GLOBAL.loop

    ready = threading.Event()

    def _run():
        _GLOBAL.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_GLOBAL.loop)
        ready.set()
        _GLOBAL.loop.run_forever()

    _GLOBAL.thread = threading.Thread(target=_run, name="asyncio-bg-loop", daemon=True)
    _GLOBAL.thread.start()
    ready.wait()
    return _GLOBAL.loop

def stop_global_loop():
    if _GLOBAL.loop and _GLOBAL.loop.is_running():
        _GLOBAL.loop.call_soon_threadsafe(_GLOBAL.loop.stop)
        _GLOBAL.thread.join(timeout=2)
        _GLOBAL.loop = None
        _GLOBAL.thread = None
