# async_runner.py
import asyncio
from typing import Callable

class AsyncRunner:
    """Esegue un awaitable sul loop globale e richiama i callback in Tk via .after."""
    def __init__(self, tk_root, loop: asyncio.AbstractEventLoop):
        self.tk = tk_root
        self.loop = loop

    def run(self, awaitable, on_ok: Callable, on_err: Callable, busy=None, message: str | None=None):
        if busy: busy.show(message or "Lavoro in corso…")
        fut = asyncio.run_coroutine_threadsafe(awaitable, self.loop)
        self._poll(fut, on_ok, on_err, busy)

    def _poll(self, fut, on_ok, on_err, busy):
        if fut.done():
            if busy: busy.hide()
            try:
                res = fut.result()
                on_ok(res)
            except Exception as ex:
                on_err(ex)
            return
        self.tk.after(50, lambda: self._poll(fut, on_ok, on_err, busy))
