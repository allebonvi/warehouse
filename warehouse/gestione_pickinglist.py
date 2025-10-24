# =================== gestione_pickinglist.py (NO-FLICKER + UX TUNING + MICRO-SPINNER) ===================

from __future__ import annotations
import tkinter as tk
import customtkinter as ctk
from tkinter import messagebox
from typing import Optional, Any, Dict, List, Callable
from dataclasses import dataclass

# Usa overlay e runner "collaudati"
from gestione_aree_frame_async import BusyOverlay, AsyncRunner

from async_loop_singleton import get_global_loop
from db_async_singleton import get_db as _get_db_singleton

# === IMPORT procedura async prenota/s-prenota (no pyodbc qui) ===
import asyncio
try:
    from prenota_sprenota_sql import sp_xExePackingListPallet_async, SPResult
except Exception:
    async def sp_xExePackingListPallet_async(*args, **kwargs):
        raise RuntimeError("sp_xExePackingListPallet_async non importabile: verifica prenota_sprenota_sql.py")
    class SPResult:
        def __init__(self, rc=-1, message="Procedura non disponibile", id_result=None):
            self.rc = rc; self.message = message; self.id_result = id_result


# -------------------- SQL --------------------
SQL_PL = """
SELECT
    COUNT(DISTINCT Pallet)        AS Pallet,
    COUNT(DISTINCT Lotto)         AS Lotto,
    COUNT(DISTINCT Articolo)      AS Articolo,
    COUNT(DISTINCT Descrizione)   AS Descrizione,
    SUM(Qta)                      AS Qta,
    Documento,
    CodNazione,
    NAZIONE,
    Stato,
    MAX(PalletCella)              AS PalletCella,
    MAX(Magazzino)                AS Magazzino,
    MAX(Area)                     AS Area,
    MAX(Cella)                    AS Cella,
    MIN(Ordinamento)              AS Ordinamento,
    MAX(IDStato)                  AS IDStato
FROM dbo.XMag_ViewPackingList
GROUP BY Documento, CodNazione, NAZIONE, Stato
ORDER BY MIN(Ordinamento), Documento, NAZIONE, Stato;
"""

SQL_PL_DETAILS = """
SELECT *
FROM ViewPackingListRestante
WHERE Documento = :Documento
ORDER BY Ordinamento;
"""

# -------------------- helpers --------------------
def _rows_to_dicts(res: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Converte il payload ritornato da query_json in lista di dict.
    Supporta:
      - res = [ {..}, {..} ]
      - res = { "rows": [..], "columns": [...] }
      - res = { "data": [..],  "columns": [...] }
      - res = { "rows": [tuple,..], "columns": [...] }
    """
    if res is None:
        return []

    if isinstance(res, list):
        if not res:
            return []
        if isinstance(res[0], dict):
            return res
        return []

    if isinstance(res, dict):
        for rows_key in ("rows", "data", "result", "records"):
            if rows_key in res and isinstance(res[rows_key], list):
                rows = res[rows_key]
                if not rows:
                    return []
                if isinstance(rows[0], dict):
                    return rows
                cols = res.get("columns") or res.get("cols") or []
                out = []
                for r in rows:
                    if cols and isinstance(r, (list, tuple)):
                        out.append({ (cols[i] if i < len(cols) else f"c{i}") : r[i]
                                     for i in range(min(len(cols), len(r))) })
                    else:
                        if isinstance(r, (list, tuple)):
                            out.append({ f"c{i}": r[i] for i in range(len(r)) })
                return out
        if res and all(not isinstance(v, (list, tuple, dict)) for v in res.values()):
            return [res]

    return []

def _s(v) -> str:
    """Stringify safe: None -> '', altrimenti str(v)."""
    return "" if v is None else str(v)

def _first(d: Dict[str, Any], keys: List[str], default: str = ""):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default

# -------------------- column specs --------------------
@dataclass
class ColSpec:
    title: str
    key: str
    width: int
    anchor: str  # 'w' | 'e' | 'center'

# Colonne PL (in alto) — include IDStato per la colorazione
PL_COLS: List[ColSpec] = [
    ColSpec("",          "__check__", 36,  "w"),
    ColSpec("Documento", "Documento", 120, "w"),
    ColSpec("NAZIONE",   "NAZIONE",   240, "w"),
    ColSpec("Stato",     "Stato",     110, "w"),
    ColSpec("IDStato",   "IDStato",    80, "e"),   # nuova colonna
    ColSpec("#Pallet",   "Pallet",    100, "e"),
    ColSpec("#Lotti",    "Lotto",     100, "e"),
    ColSpec("#Articoli", "Articolo",  110, "e"),
    ColSpec("Qta",       "Qta",       120, "e"),
]

DET_COLS: List[ColSpec] = [
    ColSpec("UDC/Pallet", "Pallet",      150, "w"),
    ColSpec("Lotto",      "Lotto",       130, "w"),
    ColSpec("Articolo",   "Articolo",    150, "w"),
    ColSpec("Descrizione","Descrizione", 320, "w"),
    ColSpec("Qta",        "Qta",         110, "e"),
    ColSpec("Ubicazione", "Ubicazione",  320, "w"),
]

ROW_H = 28


# -------------------- Micro spinner (toolbar) --------------------
class ToolbarSpinner:
    """
    Micro-animazione leggerissima per indicare attività:
    mostra una label con frame: ◐ ◓ ◑ ◒ ... finché è attivo.
    """
    FRAMES = ("◐", "◓", "◑", "◒")
    def __init__(self, parent: tk.Widget):
        self.parent = parent
        self.lbl = ctk.CTkLabel(parent, text="", width=28)
        self._i = 0
        self._active = False
        self._job = None

    def widget(self) -> ctk.CTkLabel:
        return self.lbl

    def start(self, text: str = ""):
        if self._active:
            return
        self._active = True
        self.lbl.configure(text=f"{self.FRAMES[self._i]} {text}".strip())
        self._tick()

    def stop(self):
        self._active = False
        if self._job is not None:
            try:
                self.parent.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        self.lbl.configure(text="")

    def _tick(self):
        if not self._active:
            return
        self._i = (self._i + 1) % len(self.FRAMES)
        current = self.lbl.cget("text")
        # Mantieni l'eventuale testo dopo il simbolo
        txt_suffix = ""
        if isinstance(current, str) and len(current) > 2:
            txt_suffix = current[2:]
        self.lbl.configure(text=f"{self.FRAMES[self._i]}{txt_suffix}")
        self._job = self.parent.after(120, self._tick)  # 8 fps soft


# -------------------- Scrollable table --------------------
class ScrollTable(ctk.CTkFrame):
    GRID_COLOR = "#D0D5DD"
    PADX_L = 8
    PADX_R = 8
    PADY   = 2

    def __init__(self, master, columns: List[ColSpec]):
        super().__init__(master)
        self.columns = columns
        self.total_w = sum(c.width for c in self.columns)

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # header
        self.h_canvas = tk.Canvas(self, height=ROW_H, highlightthickness=0, bd=0)
        self.h_inner  = ctk.CTkFrame(self.h_canvas, fg_color="#f3f3f3",
                                     height=ROW_H, width=self.total_w)
        self.h_canvas.create_window((0,0), window=self.h_inner, anchor="nw",
                                    width=self.total_w, height=ROW_H)
        self.h_canvas.grid(row=0, column=0, sticky="ew")

        # body
        self.b_canvas = tk.Canvas(self, highlightthickness=0, bd=0)
        self.b_inner  = ctk.CTkFrame(self.b_canvas, fg_color="transparent",
                                     width=self.total_w)
        self.body_window = self.b_canvas.create_window((0,0), window=self.b_inner,
                                                       anchor="nw", width=self.total_w)
        self.b_canvas.grid(row=1, column=0, sticky="nsew")

        # scrollbars
        self.vbar = tk.Scrollbar(self, orient="vertical",   command=self.b_canvas.yview)
        self.xbar = tk.Scrollbar(self, orient="horizontal", command=self._xscroll_both)
        self.vbar.grid(row=1, column=1, sticky="ns")
        self.xbar.grid(row=2, column=0, sticky="ew")

        # link scroll
        self.b_canvas.configure(yscrollcommand=self.vbar.set, xscrollcommand=self._xscroll_set_both)
        self.h_canvas.configure(xscrollcommand=self.xbar.set)

        # bind
        self.h_inner.bind("<Configure>", lambda e: self._sync_header_width())
        self.b_inner.bind("<Configure>", lambda e: self._on_body_configure())

        self._build_header()

    def _build_header(self):
        for w in self.h_inner.winfo_children():
            w.destroy()

        row = ctk.CTkFrame(self.h_inner, fg_color="#f3f3f3",
                           height=ROW_H, width=self.total_w)
        row.pack(fill="x", expand=False)
        row.pack_propagate(False)

        for col in self.columns:
            holder = ctk.CTkFrame(
                row, fg_color="#f3f3f3",
                width=col.width, height=ROW_H,
                border_width=1, border_color=self.GRID_COLOR
            )
            holder.pack(side="left", fill="y")
            holder.pack_propagate(False)

            lbl = ctk.CTkLabel(holder, text=col.title, anchor="w")
            lbl.pack(fill="both", padx=(self.PADX_L, self.PADX_R), pady=self.PADY)

        self.h_inner.configure(width=self.total_w, height=ROW_H)
        self.h_canvas.configure(scrollregion=(0,0,self.total_w,ROW_H))

    def _update_body_width(self):
        self.b_canvas.itemconfigure(self.body_window, width=self.total_w)
        sr = self.b_canvas.bbox("all")
        if sr:
            self.b_canvas.configure(scrollregion=(0,0,max(self.total_w, sr[2]), sr[3]))
        else:
            self.b_canvas.configure(scrollregion=(0,0,self.total_w,0))

    def _on_body_configure(self):
        self._update_body_width()
        self._sync_header_width()

    def _sync_header_width(self):
        first, _ = self.b_canvas.xview()
        self.h_canvas.xview_moveto(first)

    def _xscroll_both(self, *args):
        self.h_canvas.xview(*args)
        self.b_canvas.xview(*args)

    def _xscroll_set_both(self, first, last):
        self.h_canvas.xview_moveto(first)
        self.xbar.set(first, last)

    def clear_rows(self):
        for w in self.b_inner.winfo_children():
            w.destroy()
        self._update_body_width()

    def add_row(
        self,
        values: List[str],
        row_index: int,
        anchors: Optional[List[str]] = None,
        checkbox_builder: Optional[Callable[[tk.Widget], ctk.CTkCheckBox]] = None,
    ):
        row = ctk.CTkFrame(self.b_inner, fg_color="transparent",
                           height=ROW_H, width=self.total_w)
        row.pack(fill="x", expand=False)
        row.pack_propagate(False)

        for i, col in enumerate(self.columns):
            holder = ctk.CTkFrame(
                row, fg_color="transparent",
                width=col.width, height=ROW_H,
                border_width=1, border_color=self.GRID_COLOR
            )
            holder.pack(side="left", fill="y")
            holder.pack_propagate(False)

            if col.key == "__check__":
                if checkbox_builder:
                    cb = checkbox_builder(holder)
                    cb.pack(padx=(self.PADX_L, self.PADX_R), pady=self.PADY, anchor="w")
                else:
                    ctk.CTkLabel(holder, text="").pack(fill="both")
            else:
                anchor = (anchors[i] if anchors else col.anchor)
                ctk.CTkLabel(holder, text=values[i], anchor=anchor).pack(
                    fill="both", padx=(self.PADX_L, self.PADX_R), pady=self.PADY
                )

        self._update_body_width()


# -------------------- PL row model --------------------
class PLRow:
    def __init__(self, pl: Dict[str, Any], on_check):
        self.pl = pl
        self.var = ctk.BooleanVar(value=False)
        self._callback = on_check
    def is_checked(self) -> bool: return self.var.get()
    def set_checked(self, val: bool): self.var.set(val)
    def build_checkbox(self, parent) -> ctk.CTkCheckBox:
        return ctk.CTkCheckBox(parent, text="", variable=self.var,
                               command=lambda: self._callback(self, self.var.get()))


# -------------------- main frame (no-flicker + UX tuning + spinner) --------------------
class GestionePickingListFrame(ctk.CTkFrame):
    def __init__(self, master, *, db_client=None, conn_str=None):
        super().__init__(master)
        self.db_client = db_client or _get_db_singleton(get_global_loop(), conn_str)
        self.runner = AsyncRunner(self)        # runner condiviso (usa loop globale)
        self.busy = BusyOverlay(self)          # overlay collaudato

        self.rows_models: list[PLRow] = []
        self._detail_cache: Dict[Any, list] = {}
        self.detail_doc = None

        self._first_loading: bool = False  # flag per cursore d'attesa solo al primo load

        self._build_layout()
        # 🔇 Niente reload immediato: carichiamo quando la finestra è idle (= già resa)
        self.after_idle(self._first_show)

    def _first_show(self):
        """Chiamato a finestra già resa → evitiamo sfarfallio del primo paint e mostriamo wait-cursor."""
        self._first_loading = True
        try:
            self.winfo_toplevel().configure(cursor="watch")
        except Exception:
            pass
        # spinner inizia
        self.spinner.start(" Carico…")
        self.reload_from_db(first=True)

    # ---------- UI ----------
    def _build_layout(self):
        for r in (1, 3): self.grid_rowconfigure(r, weight=1)
        self.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(self)
        top.grid(row=0, column=0, sticky="ew", padx=10, pady=(8,4))
        for i, (text, cmd) in enumerate([
            ("Ricarica", self.reload_from_db),
            ("Prenota", self.on_prenota),
            ("S-prenota", self.on_sprenota),
            ("Esporta XLSX", self.on_export)
        ]):
            ctk.CTkButton(top, text=text, command=cmd).grid(row=0, column=i, padx=6)

        # --- micro spinner a destra della toolbar ---
        self.spinner = ToolbarSpinner(top)
        self.spinner.widget().grid(row=0, column=10, padx=(8,0))  # largo spazio a destra

        self.pl_table = ScrollTable(self, PL_COLS)
        self.pl_table.grid(row=1, column=0, sticky="nsew", padx=10, pady=(4,8))

        self.det_table = ScrollTable(self, DET_COLS)
        self.det_table.grid(row=3, column=0, sticky="nsew", padx=10, pady=(4,10))

        self._draw_details_hint()

    def _draw_details_hint(self):
        self.det_table.clear_rows()
        self.det_table.add_row(
            values=["", "", "", "Seleziona una Picking List per vedere le UDC…", "", ""],
            row_index=0,
            anchors=["w"]*6
        )

    def _apply_row_colors(self, rows: List[Dict[str, Any]]):
        """Colorazione differita (after_idle) per evitare micro-jank durante l'inserimento righe."""
        try:
            for idx, d in enumerate(rows):
                row_widget = self.pl_table.b_inner.winfo_children()[idx]
                if int(d.get("IDStato") or 0) == 1:
                    row_widget.configure(fg_color="#ffe6f2")   # rosa tenue
                else:
                    row_widget.configure(fg_color="transparent")
        except Exception:
            pass

    def _refresh_mid_rows(self, rows: List[Dict[str, Any]]):
        self.pl_table.clear_rows()
        self.rows_models.clear()

        for r, d in enumerate(rows):
            model = PLRow(d, self.on_row_checked)
            self.rows_models.append(model)
            values = [
                "",  # checkbox
                _s(d.get("Documento")),
                _s(d.get("NAZIONE")),
                _s(d.get("Stato")),
                _s(d.get("IDStato")),          # nuova colonna visibile
                _s(d.get("Pallet")),
                _s(d.get("Lotto")),
                _s(d.get("Articolo")),
                _s(d.get("Qta")),
            ]
            self.pl_table.add_row(
                values=values,
                row_index=r,
                anchors=[c.anchor for c in PL_COLS],
                checkbox_builder=model.build_checkbox
            )

        # 🎯 Colora dopo che la UI è resa → no balzi visivi
        self.after_idle(lambda: self._apply_row_colors(rows))

    # ----- helpers -----
    def _get_selected_model(self) -> Optional[PLRow]:
        for m in self.rows_models:
            if m.is_checked():
                return m
        return None

    def _recolor_row_by_documento(self, documento: str, idstato: int):
        """Aggiorna colore riga e cella IDStato per il Documento indicato."""
        for idx, m in enumerate(self.rows_models):
            if _s(m.pl.get("Documento")) == _s(documento):
                m.pl["IDStato"] = idstato
                def _paint():
                    try:
                        row_widget = self.pl_table.b_inner.winfo_children()[idx]
                        row_widget.configure(fg_color="#ffe6f2" if idstato == 1 else "transparent")
                        row_children = row_widget.winfo_children()
                        if len(row_children) >= 5:
                            holder = row_children[4]
                            if holder.winfo_children():
                                lbl = holder.winfo_children()[0]
                                if hasattr(lbl, "configure"):
                                    lbl.configure(text=str(idstato))
                    except Exception:
                        pass
                # differisci la colorazione (smooth)
                self.after_idle(_paint)
                break

    def _reselect_documento_after_reload(self, documento: str):
        """(Opzionale) Dopo un reload DB, riseleziona la PL con lo stesso Documento."""
        for m in self.rows_models:
            if _s(m.pl.get("Documento")) == _s(documento):
                m.set_checked(True)
                self.on_row_checked(m, True)
                break

    # ----- eventi -----
    def on_row_checked(self, model: PLRow, is_checked: bool):
        # selezione esclusiva
        if is_checked:
            for m in self.rows_models:
                if m is not model and m.is_checked():
                    m.set_checked(False)

            self.detail_doc = model.pl.get("Documento")
            self.spinner.start(" Carico dettagli…")  # spinner ON

            async def _job():
                return await self.db_client.query_json(SQL_PL_DETAILS, {"Documento": self.detail_doc})

            def _ok(res):
                self.spinner.stop()  # spinner OFF
                self._detail_cache[self.detail_doc] = _rows_to_dicts(res)
                # differisci il render dei dettagli (più fluido)
                self.after_idle(self._refresh_details)

            def _err(ex):
                self.spinner.stop()
                messagebox.showerror("DB", f"Errore nel caricamento dettagli:\n{ex}")

            self.runner.run(
                _job(),
                on_success=_ok,
                on_error=_err,
                busy=self.busy,
                message=f"Carico UDC per Documento {self.detail_doc}…"
            )

        else:
            if not any(m.is_checked() for m in self.rows_models):
                self.detail_doc = None
                self._refresh_details()

    # ----- load PL -----
    def reload_from_db(self, first: bool = False):
        self.spinner.start(" Carico…")  # spinner ON
        async def _job():
            return await self.db_client.query_json(SQL_PL, {})
        def _on_success(res):
            rows = _rows_to_dicts(res)
            self._refresh_mid_rows(rows)
            self.spinner.stop()  # spinner OFF
            # se era il primo load, ripristina il cursore standard
            if self._first_loading:
                try:
                    self.winfo_toplevel().configure(cursor="")
                except Exception:
                    pass
                self._first_loading = False
        def _on_error(ex):
            self.spinner.stop()
            if self._first_loading:
                try:
                    self.winfo_toplevel().configure(cursor="")
                except Exception:
                    pass
                self._first_loading = False
            messagebox.showerror("DB", f"Errore nel caricamento:\n{ex}")

        self.runner.run(
            _job(),
            on_success=_on_success,
            on_error=_on_error,
            busy=self.busy,
            message="Caricamento Picking List…" if first else "Aggiornamento…"
        )

    def _refresh_details(self):
        self.det_table.clear_rows()
        if not self.detail_doc:
            self._draw_details_hint()
            return

        rows = self._detail_cache.get(self.detail_doc, [])
        if not rows:
            self.det_table.add_row(values=["", "", "", "Nessuna UDC trovata.", "", ""],
                                   row_index=0, anchors=["w"]*6)
            return

        for r, d in enumerate(rows):
            pallet = _s(_first(d, ["Pallet", "UDC", "PalletID"]))
            lotto  = _s(_first(d, ["Lotto"]))
            articolo = _s(_first(d, ["Articolo", "CodArticolo", "CodiceArticolo", "Art", "Codice"]))
            descr    = _s(_first(d, ["Descrizione", "Descr", "DescrArticolo", "DescArticolo", "DesArticolo"]))
            qta      = _s(_first(d, ["Qta", "Quantita", "Qty", "QTY"]))
            ubi_raw  = _first(d, ["Ubicazione", "Cella", "PalletCella"])
            loc      = "Non scaffalata" if (ubi_raw is None or str(ubi_raw).strip()=="") else str(ubi_raw).strip()

            self.det_table.add_row(
                values=[pallet, lotto, articolo, descr, qta, loc],
                row_index=r,
                anchors=[c.anchor for c in DET_COLS]
            )

    # ----- azioni -----
    def on_prenota(self):
        model = self._get_selected_model()
        if not model:
            messagebox.showinfo("Prenota", "Seleziona una Picking List (checkbox) prima di prenotare.")
            return

        documento = _s(model.pl.get("Documento"))
        current = int(model.pl.get("IDStato") or 0)
        desired = 1
        if current == desired:
            messagebox.showinfo("Prenota", f"La Picking List {documento} è già prenotata.")
            return

        id_operatore = 1  # TODO: recupera dal contesto reale
        self.spinner.start(" Prenoto…")

        async def _job():
            return await sp_xExePackingListPallet_async(self.db_client, id_operatore, documento)

        def _ok(res: SPResult):
            self.spinner.stop()
            if res and res.rc == 0:
                self._recolor_row_by_documento(documento, desired)
            else:
                msg = (res.message if res else "Errore sconosciuto")
                messagebox.showerror("Prenota", f"Operazione non riuscita:\n{msg}")

        def _err(ex):
            self.spinner.stop()
            messagebox.showerror("Prenota", f"Errore:\n{ex}")

        self.runner.run(
            _job(),
            on_success=_ok,
            on_error=_err,
            busy=self.busy,
            message=f"Prenoto la Picking List {documento}…"
        )

    def on_sprenota(self):
        model = self._get_selected_model()
        if not model:
            messagebox.showinfo("S-prenota", "Seleziona una Picking List (checkbox) prima di s-prenotare.")
            return

        documento = _s(model.pl.get("Documento"))
        current = int(model.pl.get("IDStato") or 0)
        desired = 0
        if current == desired:
            messagebox.showinfo("S-prenota", f"La Picking List {documento} è già NON prenotata.")
            return

        id_operatore = 1  # TODO: recupera dal contesto reale
        self.spinner.start(" S-prenoto…")

        async def _job():
            return await sp_xExePackingListPallet_async(self.db_client, id_operatore, documento)

        def _ok(res: SPResult):
            self.spinner.stop()
            if res and res.rc == 0:
                self._recolor_row_by_documento(documento, desired)
            else:
                msg = (res.message if res else "Errore sconosciuto")
                messagebox.showerror("S-prenota", f"Operazione non riuscita:\n{msg}")

        def _err(ex):
            self.spinner.stop()
            messagebox.showerror("S-prenota", f"Errore:\n{ex}")

        self.runner.run(
            _job(),
            on_success=_ok,
            on_error=_err,
            busy=self.busy,
            message=f"S-prenoto la Picking List {documento}…"
        )

    def on_export(self):
        messagebox.showinfo("Esporta", "Stub esportazione.")


# factory per main
def create_frame(parent, *, db_client=None, conn_str=None) -> 'GestionePickingListFrame':
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("green")
    return GestionePickingListFrame(parent, db_client=db_client, conn_str=conn_str)

# =================== /gestione_pickinglist.py ===================
