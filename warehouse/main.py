
import sys
import asyncio
import tkinter as tk
from tkinter import ttk
import customtkinter as ctk

from async_msssql_query import AsyncMSSQLClient, make_mssql_dsn
from async_loop_singleton import get_global_loop

from layout_window import open_layout_window
from view_celle_multiple import open_celle_multiple_window
from reset_corsie import open_reset_corsie_window
from search_pallets import open_search_window

# Try factory, else frame, else app (senza passare conn_str all'App)
try:
    from gestione_pickinglist import create_frame as create_pickinglist_frame
except Exception:
    try:
        from gestione_pickinglist import GestionePickingListFrame as _PLFrame
        import customtkinter as ctk
        def create_pickinglist_frame(parent, db_client=None, conn_str=None):
            ctk.set_appearance_mode("light")
            ctk.set_default_color_theme("green")
            return _PLFrame(parent, db_client=db_client, conn_str=conn_str)
    except Exception:
        # Ultimo fallback: alcune versioni espongono solo la App e NON accettano conn_str
        # Ultimo fallback: alcune versioni espongono solo la App e NON accettano parametri
        from gestione_pickinglist import GestionePickingListApp as _PLApp
        def create_pickinglist_frame(parent, db_client=None, conn_str=None):
            app = _PLApp()  # <-- niente parametri qui
            app.mainloop()
            return tk.Frame(parent)



# ---- Config ----
SERVER = r"mde3\gesterp"
DBNAME = "Mediseawall"
USER = "sa"
PASSWORD = "1Password1"

if sys.platform.startswith("win"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

# Create ONE global loop and make it the default everywhere
_loop = get_global_loop()
asyncio.set_event_loop(_loop)

# --- DPI tracker compatibility ---
def _noop(*args, **kwargs):
    return None
if not hasattr(tk.Toplevel, "block_update_dimensions_event"):
    tk.Toplevel.block_update_dimensions_event = _noop  # type: ignore[attr-defined]
if not hasattr(tk.Toplevel, "unblock_update_dimensions_event"):
    tk.Toplevel.unblock_update_dimensions_event = _noop  # type: ignore[attr-defined]

dsn_app = make_mssql_dsn(server=SERVER, database=DBNAME, user=USER, password=PASSWORD)
db_app = AsyncMSSQLClient(dsn_app)


def open_pickinglist_window(parent: tk.Misc, db_client: AsyncMSSQLClient):
    win = ctk.CTkToplevel(parent)
    win.title("Gestione Picking List")
    win.geometry("1200x700+0+100")
    win.minsize(1000, 560)

    # 1) tieni la toplevel fuori scena mentre componi
    try:
        win.withdraw()
        # opzionale: rendila invisibile anche se il WM la “intr intravede”
        win.attributes("-alpha", 0.0)
    except Exception:
        pass

    # 2) costruisci tutto il contenuto
    frame = create_pickinglist_frame(win, db_client=db_client)
    try:
        frame.pack(fill="both", expand=True)
    except Exception:
        pass

    # 3) quando è pronta, mostra "a scatto" davanti, senza topmost
    try:
        win.update_idletasks()
        try:
            win.transient(parent)  # z-order legato alla main
        except Exception:
            pass
        try:
            win.deiconify()
        except Exception:
            pass
        win.lift()
        try:
            win.focus_force()
        except Exception:
            pass
        # ripristina opacità
        try:
            win.attributes("-alpha", 1.0)
        except Exception:
            pass
    except Exception:
        pass

    win.bind("<Escape>", lambda e: win.destroy())
    win.protocol("WM_DELETE_WINDOW", win.destroy)
    return win




class Launcher(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Warehouse 1.0.0")
        self.geometry("1200x70+0+0")

        wrap = ttk.Frame(self)
        wrap.pack(pady=10, fill="x")

        ttk.Button(wrap, text="Gestione Corsie",
                   command=lambda: open_reset_corsie_window(self, db_app)).grid(row=0, column=0, padx=6, pady=6, sticky="ew")
        ttk.Button(wrap, text="Gestione Layout",
                   command=lambda: open_layout_window(self, db_app)).grid(row=0, column=1, padx=6, pady=6, sticky="ew")
        ttk.Button(wrap, text="UDC Fantasma",
                   command=lambda: open_celle_multiple_window(self, db_app)).grid(row=0, column=2, padx=6, pady=6, sticky="ew")
        ttk.Button(wrap, text="Ricerca UDC",
                   command=lambda: open_search_window(self, db_app)).grid(row=0, column=3, padx=6, pady=6, sticky="ew")
        ttk.Button(wrap, text="Gestione Picking List",
                   command=lambda: open_pickinglist_window(self, db_app)).grid(row=0, column=4, padx=6, pady=6, sticky="ew")

        for i in range(5):
            wrap.grid_columnconfigure(i, weight=1)

        def _on_close():
            try:
                fut = asyncio.run_coroutine_threadsafe(db_app.dispose(), _loop)
                try:
                    fut.result(timeout=2)
                except Exception:
                    pass
            finally:
                self.destroy()

        self.protocol("WM_DELETE_WINDOW", _on_close)


if __name__ == "__main__":
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("green")
    Launcher().mainloop()
