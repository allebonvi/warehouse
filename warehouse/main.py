import tkinter as tk
from tkinter import ttk, messagebox
from json_sidebar import JsonSidebar
#from dataqueryframe import DataQueryFrame
from dashboard_page import DashboardFrame

# ---- contenuto centrale con Frame multipli ----
#class DashboardFrame(ttk.Frame):
#    def __init__(self, master): super().__init__(master); ttk.Label(self, text="Dashboard").pack(padx=20, pady=20)
class ProgettiAttiviFrame(ttk.Frame):
    def __init__(self, master): super().__init__(master); ttk.Label(self, text="Progetti Attivi").pack(padx=20, pady=20)
class ProgettiArchiviatiFrame(ttk.Frame):
    def __init__(self, master): super().__init__(master); ttk.Label(self, text="Progetti Archiviati").pack(padx=20, pady=20)
class UtentiFrame(ttk.Frame):
    def __init__(self, master): super().__init__(master); ttk.Label(self, text="Utenti").pack(padx=20, pady=20)
class RuoliFrame(ttk.Frame):
    def __init__(self, master): super().__init__(master); ttk.Label(self, text="Ruoli").pack(padx=20, pady=20)

FRAME_MAP = {
    "DashboardFrame": DashboardFrame,
    "ProgettiAttiviFrame": ProgettiAttiviFrame,
    "ProgettiArchiviatiFrame": ProgettiArchiviatiFrame,
    "UtentiFrame": UtentiFrame,
    "RuoliFrame": RuoliFrame,
}






def make_page_loader(container):
    current = {"widget": None}
    def loader(frame_name: str):
        cls = FRAME_MAP.get(frame_name)
        if not cls: return
        if current["widget"] is not None:
            current["widget"].destroy()
        w = cls(container)
        w.pack(fill="both", expand=True)
        current["widget"] = w
    return loader

def open_settings(): messagebox.showinfo("Preferenze", "Apri impostazioni…")
def exit_app(): root.destroy()

root = tk.Tk()
root.geometry("1000x600")
root.title("Demo Sidebar Tree")

# area contenuti
main = ttk.Frame(root); main.place(relx=0.08, rely=0, relwidth=0.92, relheight=1.0)
page_loader = make_page_loader(main)

 



callbacks = {"open_settings": open_settings, "exit_app": exit_app}

sidebar = JsonSidebar(root, "sidebar_config.json", callbacks=callbacks, page_loader=page_loader)

# adatta la main area quando apri/chiudi la sidebar
def _retile():
    info = sidebar.place_info()
    rw = float(info.get("relwidth", 0.08))
    main.place_configure(relx=rw, relwidth=1.0 - rw, rely=0, relheight=1.0)
_orig_toggle = sidebar.toggle
def _toggle_and_retile():
    _orig_toggle()
    root.after_idle(_retile)
sidebar.toggle = _toggle_and_retile
root.after_idle(_retile)

root.mainloop()
