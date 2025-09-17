# data_query_frame.py
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from tksheet import Sheet
import pyodbc

class DataQueryFrame(ttk.Frame):
    """
    Frame auto-contenuto con:
      - top bar: connection string + pulsante Esegui
      - box query (Text) con SQL
      - tksheet per mostrare i risultati
      - overlay (progress) durante l'esecuzione
      - menu destro su cella con 'Cattura dettagli' (popup)

    Posizionamento: decidi tu nel container (pack/grid/place).
    """

    def __init__(self, master, conn_str=None, default_query="SELECT * FROM artico;", **kwargs):
        super().__init__(master, **kwargs)

        # --- stato ---
        self.conn_var = tk.StringVar(value=conn_str or
            "Driver={ODBC Driver 17 for SQL Server};"
            "Server=localhost\\SQLEXPRESS;"
            "Database=master;"
            "Trusted_Connection=yes;"
            "TrustServerCertificate=yes;"
        )
        self._running = False
        self._column_headers = []

        # --- layout base ---
        self._build_widgets()
        self._make_overlay()

        # query di default
        self.query_txt.delete("1.0", "end")
        self.query_txt.insert("1.0", default_query)

        # abilita bindings e menu integrato + voce cattura
        self._wire_sheet_right_click()

    # ---------------- UI ----------------
    def _build_widgets(self):
        # barra top
        top = ttk.Frame(self); top.pack(side="top", fill="x", padx=8, pady=(8, 4))
        ttk.Label(top, text="Connection:").pack(side="left")
        self.conn_entry = ttk.Entry(top, textvariable=self.conn_var, width=110)
        self.conn_entry.pack(side="left", padx=6, fill="x", expand=True)
        self.btn_run = ttk.Button(top, text="Esegui query", command=self._on_run_click)
        self.btn_run.pack(side="left", padx=(6, 0))

        # pannello centrale sinistra: query, destra: sheet
        center = ttk.Panedwindow(self, orient="horizontal")
        center.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        left = ttk.Frame(center); right = ttk.Frame(center)
        center.add(left, weight=1); center.add(right, weight=3)

        ttk.Label(left, text="SQL Query").pack(anchor="w")
        self.query_txt = tk.Text(left, height=8, wrap="word")
        self.query_txt.pack(fill="both", expand=True, pady=(2, 6))

        # tksheet
        self.sheet = Sheet(
            right,
            data=[],
            headers=[],
            show_x_scrollbar=True,
            show_y_scrollbar=True
        )
        self.sheet.pack(fill="both", expand=True)

        # abilita interazioni utili
        self.sheet.enable_bindings((
            "single_select", "rc_select",
            "right_click_popup_menu",
            "copy", "cut", "paste",
            "edit_cell", "undo", "redo",
            "column_width_resize", "row_height_resize",
            "column_drag_and_drop", "row_drag_and_drop",
            "arrowkeys",
        ))

        # status bar (facoltativa)
        self.status_var = tk.StringVar()
        ttk.Label(self, textvariable=self.status_var, anchor="w").pack(fill="x", padx=8, pady=(0, 6))

    def _make_overlay(self):
        # overlay che copre tutto il frame (blocca le interazioni)
        self._overlay = tk.Frame(self, bg="#000000", cursor="watch")
        # semi-trasparenza vera non è supportata per child-frames, ma il colore scuro rende il "busy" evidente
        inner = ttk.Frame(self._overlay, padding=20)
        inner.place(relx=0.5, rely=0.5, anchor="center")
        ttk.Label(inner, text="Esecuzione in corso…").pack(pady=(0, 8))
        self._pb = ttk.Progressbar(inner, mode="indeterminate", length=180)
        self._pb.pack()
        # click sull'overlay non propagano
        self._overlay.bind("<Button-1>", lambda e: "break")

    def _show_overlay(self):
        if not self._running:
            self._running = True
            self.btn_run.config(state="disabled")
            # copri questo frame
            self._overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
            self._pb.start(10)
            self.update_idletasks()

    def _hide_overlay(self):
        if self._running:
            self._running = False
            self._pb.stop()
            self._overlay.place_forget()
            self.btn_run.config(state="normal")
            self.configure(cursor="")  # reset

    # ---------------- Right-click menu: 'Cattura dettagli' ----------------
    def _wire_sheet_right_click(self):
        # aggiungi la voce al menu integrato della tabella
        self.sheet.popup_menu_add_command("Cattura dettagli", self._capture_details,
                                          table_menu=True, index_menu=False, header_menu=False)

    @staticmethod
    def _normalize_selected(sel):
        # gestisce tuple/list più lunghe o dict (versioni diverse di tksheet)
        r = c = None; what = "cell"
        if isinstance(sel, dict):
            r = sel.get("row"); c = sel.get("column"); what = sel.get("type", "cell")
        elif isinstance(sel, (tuple, list)):
            if len(sel) >= 2: r, c = sel[0], sel[1]
            if len(sel) >= 3: what = sel[2]
        return r, c, what

    def _show_popup(self, text, title, w=520, h=320):
        # mostra un Toplevel dopo la chiusura del menu integrato
        def _open():
            top = tk.Toplevel(self)
            top.title(title)
            # vicino al puntatore
            x, y = self.winfo_pointerx() + 10, self.winfo_pointery() + 10
            top.geometry(f"{w}x{h}+{x}+{y}")
            top.transient(self.winfo_toplevel())
            top.lift(); top.attributes("-topmost", True)
            top.after(80, lambda: top.attributes("-topmost", False))

            txt = tk.Text(top, wrap="word")
            txt.insert("1.0", text); txt.config(state="disabled")
            txt.pack(fill="both", expand=True)

            bar = ttk.Frame(top); bar.pack(fill="x", padx=8, pady=6)
            def copia():
                self.clipboard_clear(); self.clipboard_append(text)
            ttk.Button(bar, text="Copia dettagli", command=copia).pack(side="right")
        # posticipa per lasciare chiudere il popup menu integrato
        self.after(10, _open)

    def _capture_details(self):
        # robusto su versioni diverse + fallback a celle selezionate
        r, c, what = self._normalize_selected(self.sheet.get_currently_selected())
        if (what != "cell") or (r is None) or (c is None):
            try:
                cells = self.sheet.get_selected_cells()
                if cells:
                    r, c = cells[0]; what = "cell"
            except Exception:
                pass
        if (r is None) or (c is None):
            self._show_popup("Nessuna cella selezionata.\nClic destro su una cella → Cattura dettagli.", "Cattura")
            return

        val = self.sheet.get_cell_data(r, c)
        header = self._column_headers[c] if 0 <= c < len(self._column_headers) else "(nessuno)"

        info = (
            f"Tipo selezione: cell\n"
            f"Riga (0-based): {r}\n"
            f"Colonna (0-based): {c}\n"
            f"Riga (1-based): {r+1}\n"
            f"Colonna (1-based): {c+1}\n"
            f"Header colonna: {header}\n"
            f"Tipo Python: {type(val).__name__}\n"
            f"Valore (repr):\n{val!r}\n"
        )
        self._show_popup(info, f"Dettagli cella ({r},{c})")

    # ---------------- Esecuzione query ----------------
    def _on_run_click(self):
        sql = self.query_txt.get("1.0", "end").strip()
        if not sql:
            messagebox.showwarning("Attenzione", "Inserisci una query SQL.")
            return
        conn_str = self.conn_var.get().strip()
        if not conn_str:
            messagebox.showwarning("Attenzione", "Inserisci una connection string ODBC.")
            return

        # avvia overlay e thread
        self._show_overlay()
        t = threading.Thread(target=self._run_query_thread, args=(conn_str, sql), daemon=True)
        t.start()

    def _run_query_thread(self, conn_str, sql):
        try:
            with pyodbc.connect(conn_str, timeout=30) as cn:
                cur = cn.cursor()
                cur.execute(sql)
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description] if cur.description else []
            data = [list(r) for r in rows]
            # aggiorna UI sul main thread
            self.after(0, lambda: self._update_sheet(data, cols, None))
        except Exception as e:
            self.after(0, lambda: self._update_sheet(None, None, e))

    def _update_sheet(self, data, cols, error):
        try:
            if error:
                messagebox.showerror("Errore query", str(error))
                return
            self._column_headers = cols or []
            self.sheet.set_sheet_data(data or [], reset_col_positions=True,
                                      reset_row_positions=True, redraw=True)
            if cols:
                self.sheet.headers(cols)
            # auto-size semplice
            try:
                self.sheet.set_all_cell_sizes_to_text()
            except Exception:
                pass
            self.status_var.set(f"Righe: {len(data)} - Colonne: {len(cols)}")
        finally:
            self._hide_overlay()
