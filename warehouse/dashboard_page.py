# dashboard_page.py (rollback: async execution, single apply without streaming)
import json
import threading
import asyncio
from urllib.parse import quote_plus

import tkinter as tk
from tkinter import ttk, messagebox

from tksheet import Sheet
from dataqueryframe import DataQueryFrame
from paged_async_data_frame import PagedAsyncDataFrame

# Usa il tuo client async; prova 2 nomi modulo per compatibilità
try:
    from async_mssql_client import AsyncMSSQLClient, make_mssql_dsn
except Exception:
    from async_msssql_query import AsyncMSSQLClient, make_mssql_dsn  # type: ignore


# --- Event loop asyncio dedicato in un thread separato (GUI libera) ---
class _LoopThread:
    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def stop(self):
        self._loop.call_soon_threadsafe(self._loop.stop)


class AsyncDataQueryFrame(DataQueryFrame):
    """
    Versione senza streaming:
    - la query gira in async (thread/loop dedicato)
    - quando finisce, applichiamo TUTTI i dati in un'unica chiamata a set_sheet_data()
    """
    def __init__(self, master, *, dsn: str | None = None, **kwargs):
        super().__init__(master, **kwargs)
        self._dsn = dsn
        self._loop_thread = _LoopThread()

    def destroy(self):
        try:
            self._loop_thread.stop()
        except Exception:
            pass
        return super().destroy()

    # ----------------- override: esecuzione query -----------------
    def _on_run_click(self):
        sql = self.query_txt.get("1.0", "end").strip()
        if not sql:
            messagebox.showwarning("Attenzione", "Inserisci una query SQL.")
            return

        self._show_overlay()  # overlay attivo SUBITO

        # DSN async dal campo di connessione ODBC, se non passato nel ctor
        dsn = self._dsn
        if not dsn:
            odbc = self.conn_var.get().strip()
            if not odbc:
                self._hide_overlay()
                messagebox.showwarning("Attenzione", "Inserisci una connection string ODBC.")
                return
            dsn = f"mssql+aioodbc:///?odbc_connect={quote_plus(odbc)}"

        async def _run_async():
            client = AsyncMSSQLClient(dsn, enable_log=False)
            try:
                payload_json = await client.query_json(sql, include_sql_in_payload=False)
            finally:
                await client.close()
            return payload_json

        fut = self._loop_thread.submit(_run_async())

        def _on_done(f):
            try:
                payload_json = f.result()
            except Exception as e:
                self.after(0, lambda: self._finish_with_error(e))
                return
            # parse JSON fuori dal main thread (non blocca la GUI)
            try:
                payload = json.loads(payload_json)
            except Exception as e:
                self.after(0, lambda: self._finish_with_error(f"JSON parse error: {e}"))
                return
            # Applica risultati sul MAIN thread (singola apply, no streaming)
            self.after(0, lambda: self._apply_payload_simple(payload))

        fut.add_done_callback(_on_done)

    # ----------------- applicazione risultati: singola passata -----------------
    def _apply_payload_simple(self, payload: dict):
        try:
            if "error" in payload and payload["error"]:
                self._finish_with_error(payload["error"])
                return

            # Estrai colonne/righe dal payload (adatta qui se i nomi differiscono)
            cols = payload.get("columns") or []
            rows = payload.get("rows") or []

            # Normalizza le righe: tksheet vuole liste di liste
            norm_rows = []
            for r in rows:
                if isinstance(r, dict):
                    norm_rows.append([r.get(c) for c in cols])
                elif isinstance(r, (list, tuple)):
                    norm_rows.append(list(r))
                else:
                    norm_rows.append([r])

            # Applica in una sola chiamata
            self._column_headers = cols
            self.sheet.set_sheet_data(norm_rows, reset_col_positions=True,
                                      reset_row_positions=True, redraw=True)
            if cols:
                self.sheet.headers(cols)

            # Auto-size (se la tua versione è lenta, commenta queste 2 righe)
            try:
                self.sheet.set_all_cell_sizes_to_text()
            except Exception:
                pass

            elapsed = payload.get("elapsed_ms", 0)
            self.status_var.set(f"Righe: {len(norm_rows)} - Colonne: {len(cols)} (in {elapsed} ms)")
        finally:
            self._hide_overlay()

    # --- error handling ---
    def _finish_with_error(self, error):
        try:
            self._hide_overlay()
            messagebox.showerror("Errore query", str(error))
        finally:
            self._hide_overlay()


# ---------- Pagina esposta alla sidebar ----------
class DashboardFrame(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)

        ttk.Label(self, text="Dashboard (async, no streaming)", style="Heading.TLabel")\
           .pack(anchor="w", padx=16, pady=(16, 8))

        default_conn = (
            "Driver={SQL Server Native Client 11.0};"
            "Server=mde3\\gesterp;"
            "Database=SAMA1;"
            "Trusted_Connection=yes;"
            "UID=sa;PWD=1Password1;"
            "TrustServerCertificate=yes;"
        )

        # self.dq = AsyncDataQueryFrame(
            # self,
            # dsn=None,                        # oppure DSN 'mssql+aioodbc://...' già pronto
            # conn_str=default_conn,           # usato per costruire il DSN se non passi 'dsn'
            # default_query="SELECT TOP (50000) * FROM dbo.artico;",
        # )
        
        grid = PagedAsyncDataFrame(
            self,
            table="dbo.artico",    # tabella o view
            pk="id",               # ORDER BY stabile
            columns="*",           # o elenco colonne
            where=None,            # opzionale
            page_size=100,
            conn_str=default_conn,
            prefetch_all=True,     # <— prefetch dell’intero dataset in background
            prefetch_chunk=1000,   # dimensione dei batch di prefetch
        )
        grid.place(x=10, y=10, relwidth=0.96, relheight=0.80)
