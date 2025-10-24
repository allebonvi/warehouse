# gestione_aree_frame_async.py
from __future__ import annotations

import asyncio
import threading
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Optional

__VERSION__ = "GestioneAreeFrame v3.2.5-singleloop"
#print("[GestioneAreeFrame] loaded", __VERSION__)

try:
    from async_msssql_query import AsyncMSSQLClient  # noqa: F401
except Exception:
    AsyncMSSQLClient = object  # type: ignore

# ========================
# Global asyncio loop
# ========================
class _LoopHolder:
    def __init__(self):
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None
        self.ready = threading.Event()

_GLOBAL = _LoopHolder()

def _run_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _GLOBAL.loop = loop
    _GLOBAL.ready.set()
    loop.run_forever()

def get_global_loop() -> asyncio.AbstractEventLoop:
    if _GLOBAL.loop is not None:
        return _GLOBAL.loop
    _GLOBAL.thread = threading.Thread(target=_run_loop, name="warehouse-asyncio", daemon=True)
    _GLOBAL.thread.start()
    _GLOBAL.ready.wait(timeout=5.0)
    if _GLOBAL.loop is None:
        raise RuntimeError("Impossibile avviare l'event loop globale")
    return _GLOBAL.loop

def stop_global_loop():
    if _GLOBAL.loop and _GLOBAL.loop.is_running():
        _GLOBAL.loop.call_soon_threadsafe(_GLOBAL.loop.stop)
    if _GLOBAL.thread:
        _GLOBAL.thread.join(timeout=2.0)
    _GLOBAL.loop = None
    _GLOBAL.thread = None
    _GLOBAL.ready.clear()

# ========================
# Busy overlay
# ========================
class BusyOverlay:
    def __init__(self, parent: tk.Misc):
        self.parent = parent
        self._top: Optional[tk.Toplevel] = None
        self._pb: Optional[ttk.Progressbar] = None
        self._lbl: Optional[ttk.Label] = None
        self._bind_id = None

    def _reposition(self):
        if not self._top:
            return
        root = self.parent.winfo_toplevel()
        root.update_idletasks()
        x, y = root.winfo_rootx(), root.winfo_rooty()
        w, h = root.winfo_width(), root.winfo_height()
        self._top.geometry(f"{w}x{h}+{x}+{y}")

    def show(self, message="Attendere…"):
        if self._top:
            if self._lbl:
                self._lbl.configure(text=message)
            return
        root = self.parent.winfo_toplevel()
        top = tk.Toplevel(root)
        self._top = top
        top.overrideredirect(True)
        try:
            top.attributes("-alpha", 0.22)
        except tk.TclError:
            pass
        top.configure(bg="#000")
        top.attributes("-topmost", True)

        wrap = ttk.Frame(top, padding=20)
        wrap.place(relx=0.5, rely=0.5, anchor="center")
        self._lbl = ttk.Label(wrap, text=message, font=("Segoe UI", 11, "bold"))
        self._lbl.pack(pady=(0, 10))
        self._pb = ttk.Progressbar(wrap, mode="indeterminate", length=260)
        self._pb.pack(fill="x")
        try:
            self._pb.start(12)
        except Exception:
            pass

        self._reposition()
        self._bind_id = root.bind("<Configure>", lambda e: self._reposition(), add="+")

    def hide(self):
        if self._pb:
            try:
                self._pb.stop()
            except Exception:
                pass
        self._pb = None
        if self._top:
            try:
                self._top.destroy()
            except Exception:
                pass
        self._top = None
        root = self.parent.winfo_toplevel()
        if self._bind_id:
            try:
                root.unbind("<Configure>", self._bind_id)
            except Exception:
                pass
            self._bind_id = None

# ========================
# AsyncRunner (single-loop)
# ========================
class AsyncRunner:
    """Run awaitables on the single global loop and callback on Tk main thread."""
    def __init__(self, widget: tk.Misc):
        self.widget = widget
        self.loop = get_global_loop()

    def run(
        self,
        awaitable,
        on_success: Callable[[Any], None],
        on_error: Optional[Callable[[BaseException], None]] = None,
        busy: Optional[BusyOverlay] = None,
        message: str = "Operazione in corso…",
    ):
        if busy:
            busy.show(message)
        fut = asyncio.run_coroutine_threadsafe(awaitable, self.loop)

        def _poll():
            if fut.done():
                if busy:
                    busy.hide()
                try:
                    res = fut.result()
                except BaseException as ex:
                    if on_error:
                        self.widget.after(0, lambda e=ex: on_error(e))
                    else:
                        print("[AsyncRunner] Unhandled error:", repr(ex))
                else:
                    self.widget.after(0, lambda r=res: on_success(r))
            else:
                self.widget.after(60, _poll)

        _poll()

    def close(self):
        # no-op: loop is global
        pass
