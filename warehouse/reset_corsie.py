# reset_corsie.py
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime

from gestione_aree_frame_async import BusyOverlay, AsyncRunner

# ---------------- SQL ----------------
SQL_CORSIE = """
    WITH C AS (
        SELECT DISTINCT LTRIM(RTRIM(Corsia)) AS Corsia
        FROM dbo.Celle
        WHERE ID <> 9999 AND (DelDataOra IS NULL) AND LTRIM(RTRIM(Corsia)) <> '7G'
    )
    SELECT Corsia
    FROM C
    ORDER BY
      CASE
        WHEN LEFT(Corsia,3)='MAG' AND TRY_CONVERT(int, SUBSTRING(Corsia,4,50)) IS NOT NULL THEN 0
        WHEN TRY_CONVERT(int, Corsia) IS NOT NULL THEN 1
        ELSE 2
      END,
      CASE WHEN LEFT(Corsia,3)='MAG' THEN TRY_CONVERT(int, SUBSTRING(Corsia,4,50)) END,
      CASE WHEN TRY_CONVERT(int, Corsia) IS NOT NULL THEN TRY_CONVERT(int, Corsia) END,
      CASE WHEN TRY_CONVERT(int, Corsia) IS NOT NULL THEN SUBSTRING(Corsia, LEN(CAST(TRY_CONVERT(int, Corsia) AS varchar(20)))+1, 50) END,
      Corsia;
"""

SQL_RIEPILOGO = """
WITH C AS (
    SELECT ID, LTRIM(RTRIM(Corsia)) AS Corsia,
           LTRIM(RTRIM(Colonna)) AS Colonna,
           LTRIM(RTRIM(Fila)) AS Fila
    FROM dbo.Celle
    WHERE ID <> 9999 AND (DelDataOra IS NULL)
      AND LTRIM(RTRIM(Corsia)) = :corsia
),
S AS (
    SELECT c.ID, COUNT(DISTINCT g.BarcodePallet) AS n
    FROM C AS c LEFT JOIN dbo.XMag_GiacenzaPallet AS g ON g.IDCella = c.ID
    GROUP BY c.ID
)
SELECT
  COUNT(*) AS TotCelle,
  SUM(CASE WHEN s.n>0 THEN 1 ELSE 0 END) AS CelleOccupate,
  SUM(CASE WHEN s.n>1 THEN 1 ELSE 0 END) AS CelleDoppie,
  SUM(COALESCE(s.n,0)) AS TotPallet
FROM C LEFT JOIN S s ON s.ID = C.ID;
"""

SQL_DETTAGLIO = """
WITH C AS (
    SELECT ID, LTRIM(RTRIM(Corsia)) AS Corsia,
           LTRIM(RTRIM(Colonna)) AS Colonna,
           LTRIM(RTRIM(Fila)) AS Fila
    FROM dbo.Celle
    WHERE ID <> 9999 AND (DelDataOra IS NULL)
      AND LTRIM(RTRIM(Corsia)) = :corsia
),
S AS (
    SELECT c.ID, COUNT(DISTINCT g.BarcodePallet) AS n
    FROM C AS c LEFT JOIN dbo.XMag_GiacenzaPallet AS g ON g.IDCella = c.ID
    GROUP BY c.ID
)
SELECT c.ID AS IDCella,
       CONCAT(c.Corsia, '.', c.Colonna, '.', c.Fila) AS Ubicazione,
       COALESCE(s.n,0) AS NumUDC
FROM C c LEFT JOIN S s ON s.ID = c.ID
WHERE COALESCE(s.n,0) > 0
ORDER BY TRY_CONVERT(int,c.Colonna), c.Colonna, TRY_CONVERT(int,c.Fila), c.Fila;
"""

SQL_COUNT_DELETE = """
SELECT COUNT(*) AS RowsToDelete
FROM dbo.MagazziniPallet mp
JOIN dbo.Celle c ON c.ID = mp.IDCella
WHERE c.ID <> 9999 AND LTRIM(RTRIM(c.Corsia)) = :corsia;
"""

SQL_DELETE = """
DELETE mp
FROM dbo.MagazziniPallet mp
JOIN dbo.Celle c ON c.ID = mp.IDCella
WHERE c.ID <> 9999 AND LTRIM(RTRIM(c.Corsia)) = :corsia;
"""

class ResetCorsieWindow(tk.Toplevel):
    """
    Finestra per:
    - selezionare una corsia
    - vedere riepilogo occupazione / doppie / pallet
    - vedere l'elenco celle occupate
    - svuotare (DELETE MagazziniPallet) tutte le celle della corsia selezionata
    """
    def __init__(self, parent, db_client):
        super().__init__(parent)
        self.title("Reset Corsie — svuotamento celle per corsia")
        self.geometry("1000x680")
        self.minsize(880, 560)
        self.resizable(True, True)

        self.db = db_client
        self._busy = BusyOverlay(self)
        self._async = AsyncRunner(self)

        self._build_ui()
        self._load_corsie()

    # ---------- UI ----------
    def _build_ui(self):
        top = ttk.Frame(self); top.pack(fill="x", padx=8, pady=8)
        ttk.Label(top, text="Corsia:").pack(side="left")
        self.cmb = ttk.Combobox(top, state="readonly", width=14)
        self.cmb.pack(side="left", padx=(6,10))
        ttk.Button(top, text="Carica", command=self.refresh).pack(side="left")
        ttk.Button(top, text="Svuota corsia…", command=self._ask_reset).pack(side="right")

        mid = ttk.Frame(self); mid.pack(fill="both", expand=True, padx=8, pady=(0,8))
        mid.grid_columnconfigure(0, weight=1); mid.grid_rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(mid, columns=("Ubicazione","NumUDC"), show="headings", selectmode="browse")
        self.tree.heading("Ubicazione", text="Ubicazione")
        self.tree.heading("NumUDC", text="UDC in cella")
        self.tree.column("Ubicazione", width=240, anchor="w")
        self.tree.column("NumUDC", width=120, anchor="e")

        sy = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        sx = ttk.Scrollbar(mid, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")

        bottom = ttk.LabelFrame(self, text="Riepilogo")
        bottom.pack(fill="x", padx=8, pady=(0,8))

        g = ttk.Frame(bottom); g.pack(fill="x", padx=8, pady=8)
        self.var_tot_celle = tk.StringVar(value="0")
        self.var_occ = tk.StringVar(value="0")
        self.var_dbl = tk.StringVar(value="0")
        self.var_pallet = tk.StringVar(value="0")

        def _kv(parent, label, var, col):
            ttk.Label(parent, text=label, font=("Segoe UI", 9, "bold")).grid(row=0, column=col*2, sticky="w", padx=(0,6))
            ttk.Label(parent, textvariable=var).grid(row=0, column=col*2+1, sticky="w", padx=(0,18))

        g.grid_columnconfigure(7, weight=1)
        _kv(g, "Tot. celle:", self.var_tot_celle, 0)
        _kv(g, "Celle occupate:", self.var_occ, 1)
        _kv(g, "Celle doppie:", self.var_dbl, 2)
        _kv(g, "Tot. pallet:", self.var_pallet, 3)

    # ---------- Data ----------
    def _load_corsie(self):
        def _ok(res):
            rows = res.get("rows", []) if isinstance(res, dict) else []
            items = [r[0] for r in rows]
            self.cmb["values"] = items
            if items:
                # auto 1A se presente
                sel = "1A" if "1A" in items else items[0]
                self.cmb.set(sel)
                self.refresh()
            else:
                messagebox.showinfo("Info", "Nessuna corsia trovata.", parent=self)
        def _err(ex):
            messagebox.showerror("Errore", f"Caricamento corsie fallito:\n{ex}", parent=self)
        self._async.run(self.db.query_json(SQL_CORSIE, {}), _ok, _err, busy=self._busy, message="Carico corsie…")

    def refresh(self):
        corsia = self.cmb.get().strip()
        if not corsia:
            return
        # riepilogo
        def _ok_sum(res):
            rows = res.get("rows", []) if isinstance(res, dict) else []
            if rows:
                tot, occ, dbl, pallet = rows[0]
                self.var_tot_celle.set(str(tot or 0))
                self.var_occ.set(str(occ or 0))
                self.var_dbl.set(str(dbl or 0))
                self.var_pallet.set(str(pallet or 0))
            else:
                self.var_tot_celle.set("0"); self.var_occ.set("0"); self.var_dbl.set("0"); self.var_pallet.set("0")
        def _err_sum(ex):
            messagebox.showerror("Errore", f"Riepilogo fallito:\n{ex}", parent=self)

        self._async.run(self.db.query_json(SQL_RIEPILOGO, {"corsia": corsia}), _ok_sum, _err_sum, busy=self._busy, message=f"Riepilogo {corsia}…")

        # dettaglio
        def _ok_det(res):
            rows = res.get("rows", []) if isinstance(res, dict) else []
            for i in self.tree.get_children(): self.tree.delete(i)
            for idc, ubi, n in rows:
                self.tree.insert("", "end", values=(ubi, n))
        def _err_det(ex):
            messagebox.showerror("Errore", f"Dettaglio fallito:\n{ex}", parent=self)

        self._async.run(self.db.query_json(SQL_DETTAGLIO, {"corsia": corsia}), _ok_det, _err_det, busy=None, message=None)

    # ---------- Reset ----------
    def _ask_reset(self):
        corsia = self.cmb.get().strip()
        if not corsia:
            return
        # Primo: quante righe verrebbero cancellate?
        def _ok_count(res):
            rows = res.get("rows", []) if isinstance(res, dict) else []
            n = int(rows[0][0]) if rows else 0
            if n <= 0:
                messagebox.showinfo("Svuota corsia", f"Nessun pallet da rimuovere per la corsia {corsia}.", parent=self)
                return
            # doppia conferma
            msg = (f"Verranno cancellati {n} record da MagazziniPallet per la corsia {corsia}.",f"Questa operazione è irreversibile."f"Digitare il nome della corsia per confermare:")
            confirm = tk.simpledialog.askstring("Conferma", msg, parent=self)
            if confirm is None:
                return
            if confirm.strip().upper() != corsia.upper():
                messagebox.showwarning("Annullato", "Testo di conferma non corrispondente.", parent=self)
                return
            self._do_reset(corsia)
        def _err_count(ex):
            messagebox.showerror("Errore", f"Conteggio righe da cancellare fallito:\n{ex}", parent=self)

        self._async.run(self.db.query_json(SQL_COUNT_DELETE, {"corsia": corsia}), _ok_count, _err_count, busy=self._busy, message="Verifico…")

    def _do_reset(self, corsia: str):
        def _ok_del(_):
            messagebox.showinfo("Completato", f"Corsia {corsia}: svuotamento completato.", parent=self)
            self.refresh()
        def _err_del(ex):
            messagebox.showerror("Errore", f"Svuotamento fallito:\n{ex}", parent=self)

        self._async.run(self.db.query_json(SQL_DELETE, {"corsia": corsia}), _ok_del, _err_del, busy=self._busy, message=f"Svuoto {corsia}…")


def open_reset_corsie_window(parent, db_app):
    win = ResetCorsieWindow(parent, db_app)
    win.lift(); win.focus_set()
    return win
