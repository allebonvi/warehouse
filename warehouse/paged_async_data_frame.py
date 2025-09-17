# paged_async_data_frame.py
import json
import asyncio
import threading
from urllib.parse import quote_plus

import tkinter as tk
from tkinter import ttk, messagebox
from tksheet import Sheet

try:
    from async_mssql_client import AsyncMSSQLClient
except Exception:
    from async_msssql_query import AsyncMSSQLClient  # fallback al tuo nome file


class _LoopThread:
    """Event loop asyncio dedicato in un thread separato (non blocca la GUI)."""
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.th = threading.Thread(target=self._run, daemon=True)
        self.th.start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def stop(self):
        self.loop.call_soon_threadsafe(self.loop.stop)


class PagedAsyncDataFrame(ttk.Frame):
    """
    Griglia tksheet con paginazione server-side e prefetch opzionale.
    - Mostra solo 'page_size' righe per volta (default 100)
    - Prev/Next/First/Last, input pagina, cambio page_size
    - Async (GUI reattiva) con event loop dedicato
    - Prefetch ALL opzionale (in background): scarica tutto il dataset una volta,
      ma visualizza SEMPRE in blocchi da page_size (niente freeze del paint)
    - Overlay bianco (no "flash" nero)
    """
    def __init__(self, master, *, table, pk, columns="*", where=None,
                 page_size=100, dsn=None, conn_str=None,
                 prefetch_all=False, prefetch_chunk=1000,  # quante righe per batch di prefetch
                 **kwargs):
        super().__init__(master, **kwargs)

        if not (dsn or conn_str):
            raise ValueError("Passa 'dsn' async oppure 'conn_str' ODBC")
        self._dsn = dsn or f"mssql+aioodbc:///?odbc_connect={quote_plus(conn_str)}"

        # Query params
        self.table = table
        self.pk = pk
        self.columns = columns
        self.where = where

        # Paging state
        self.page_size = int(page_size)
        self.page = 1
        self.total_rows = 0
        self.total_pages = 1

        # Prefetch state
        self.prefetch_all = bool(prefetch_all)
        self.prefetch_chunk = max(self.page_size, int(prefetch_chunk))
        self._prefetch_task = None
        self._cache_rows = []     # lista di righe (liste), riempita dal prefetch
        self._cache_ready = False # quando True abbiamo scaricato tutto

        # Async loop
        self._lt = _LoopThread()

        # ---- UI ----
        # Top bar
        top = ttk.Frame(self); top.pack(fill="x", padx=8, pady=(8, 6))
        self.lbl_title = ttk.Label(top, text=f"Tabella: {self.table}")
        self.lbl_title.pack(side="left")
        self.lbl_info = ttk.Label(top, text=""); self.lbl_info.pack(side="right")

        # Sheet
        self.sheet = Sheet(self, data=[], headers=[])
        self.sheet.pack(fill="both", expand=True, padx=8, pady=(0, 6))
        self.sheet.enable_bindings((
            "single_select","rc_select","right_click_popup_menu",
            "copy","edit_cell","arrowkeys"
        ))
        # Colori chiari per evitare flash scuro
        try:
            self.sheet.set_options(table_bg="#ffffff", index_bg="#ffffff", header_bg="#ffffff",
                                   table_selected_cells_border_color="#cccccc")
        except Exception:
            pass

        # Pager
        pager = ttk.Frame(self); pager.pack(fill="x", padx=8, pady=(0, 8))
        self.btn_first = ttk.Button(pager, text="⏮ Primo", command=self.go_first)
        self.btn_prev  = ttk.Button(pager, text="◀ Indietro", command=self.go_prev)
        self.btn_next  = ttk.Button(pager, text="Avanti ▶", command=self.go_next)
        self.btn_last  = ttk.Button(pager, text="Ultimo ⏭", command=self.go_last)
        self.btn_first.pack(side="left"); self.btn_prev.pack(side="left", padx=(6,0))
        self.btn_next.pack(side="left", padx=(12,0)); self.btn_last.pack(side="left", padx=(6,0))

        ttk.Label(pager, text="Pagina:").pack(side="left", padx=(16,4))
        self.ent_page = ttk.Spinbox(pager, from_=1, to=1, width=6, command=self.go_spin)
        self.ent_page.pack(side="left")
        ttk.Label(pager, text=" / ").pack(side="left")
        self.lbl_pages = ttk.Label(pager, text="1"); self.lbl_pages.pack(side="left")

        ttk.Label(pager, text="  Righe/pagina:").pack(side="left", padx=(16,4))
        self.ent_psize = ttk.Spinbox(pager, from_=20, to=1000, increment=20,
                                     width=6, command=self.change_psize)
        self.ent_psize.set(str(self.page_size))
        self.ent_psize.pack(side="left")

        # Prefetch toggle / indicator
        self.prefetch_var = tk.BooleanVar(value=self.prefetch_all)
        self.chk_prefetch = ttk.Checkbutton(pager, text="Prefetch completo (bg)", variable=self.prefetch_var,
                                            command=self._toggle_prefetch)
        self.chk_prefetch.pack(side="right")

        # Overlay bianco
        self._overlay = tk.Frame(self, bg="#FFFFFF", cursor="watch")  # <--- bianco
        inner = ttk.Frame(self._overlay, padding=20)
        inner.place(relx=0.5, rely=0.5, anchor="center")
        ttk.Label(inner, text="Caricamento…").pack(pady=(0,8))
        self._pb = ttk.Progressbar(inner, mode="indeterminate", length=160)
        self._pb.pack()

        # Avvio: count + prima pagina
        self.reload_all()

    # ---------- overlay ----------
    def _busy_on(self, determinate=False, maximum=0):
        self._overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        if determinate and maximum > 0:
            try:
                self._pb.configure(mode="determinate", maximum=maximum, value=0)
            except Exception:
                pass
        else:
            try:
                self._pb.configure(mode="indeterminate")
            except Exception:
                pass
        self._pb.start(10); self.update_idletasks()
        for b in (self.btn_first, self.btn_prev, self.btn_next, self.btn_last):
            b.config(state="disabled")

    def _busy_off(self):
        self._pb.stop()
        self._overlay.place_forget()
        self._update_buttons()

    # ---------- pager logic ----------
    def reload_all(self):
        """Ricalcola COUNT(*) e poi carica la prima pagina (o cache se esiste)."""
        self.page = 1
        self._refresh_count_then_page()

    def go_first(self): self.page = 1; self._run_page()
    def go_prev(self):
        if self.page > 1: self.page -= 1; self._run_page()
    def go_next(self):
        if self.page < self.total_pages: self.page += 1; self._run_page()
    def go_last(self): self.page = self.total_pages; self._run_page()
    def go_spin(self):
        try:
            p = int(self.ent_page.get())
            if 1 <= p <= self.total_pages:
                self.page = p; self._run_page()
        except Exception:
            pass
    def change_psize(self):
        try:
            self.page_size = max(1, int(self.ent_psize.get()))
        except Exception:
            self.page_size = 100
        self.reload_all()

    def _update_buttons(self):
        self.ent_page.config(to=max(1, self.total_pages))
        self.lbl_pages.config(text=str(max(1, self.total_pages)))
        self.btn_first.config(state=("disabled" if self.page <= 1 else "normal"))
        self.btn_prev.config(state=("disabled"  if self.page <= 1 else "normal"))
        self.btn_next.config(state=("disabled"  if self.page >= self.total_pages else "normal"))
        self.btn_last.config(state=("disabled"  if self.page >= self.total_pages else "normal"))

    # ---------- SQL helpers ----------
    def _where_sql(self):
        return f" WHERE {self.where} " if self.where else " "
    def _order_sql(self):
        return f" ORDER BY {self.pk} "
    def _count_sql(self):
        return f"SELECT COUNT(*) AS cnt FROM {self.table}{self._where_sql()};"
    def _page_sql(self, page, page_size=None):
        ps = page_size or self.page_size
        off = (page - 1) * ps
        return (f"SELECT {self.columns} FROM {self.table}"
                f"{self._where_sql()}{self._order_sql()}OFFSET {off} ROWS "
                f"FETCH NEXT {ps} ROWS ONLY;")

    # ---------- async runs ----------
    def _refresh_count_then_page(self):
        self._busy_on()
        async def _job():
            client = AsyncMSSQLClient(self._dsn, enable_log=False)
            try:
                cnt_json = await client.query_json(self._count_sql(), include_sql_in_payload=False)
                cnt = self._parse_count(cnt_json)
                if self.prefetch_var.get():
                    # Prepara anche la prima pagina (per apparire subito)
                    pg_json = await client.query_json(self._page_sql(1), include_sql_in_payload=False)
                else:
                    pg_json = await client.query_json(self._page_sql(1), include_sql_in_payload=False)
            finally:
                await client.close()
            return cnt, pg_json

        def _done(fut):
            try:
                cnt, pg_json = fut.result()
            except Exception as e:
                self.after(0, lambda: self._fail(e)); return
            try:
                payload = json.loads(pg_json)
            except Exception as e:
                self.after(0, lambda: self._fail(f"JSON parse error: {e}")); return
            self.total_rows = cnt
            self.total_pages = max(1, (cnt + self.page_size - 1)//self.page_size)
            self.page = 1
            self.after(0, lambda: self._apply_payload(payload, 1, cnt))
            # avvia prefetch in background se richiesto
            if self.prefetch_var.get():
                self.after(50, self._start_prefetch_background)

        self._lt.submit(_job()).add_done_callback(_done)

    def _run_page(self):
        # se cache pronta, disegna dalla cache senza chiamare il DB
        if self._cache_ready and self._cache_rows:
            self._apply_cached_page()
            return

        self._busy_on()
        async def _job():
            client = AsyncMSSQLClient(self._dsn, enable_log=False)
            try:
                pg_json = await client.query_json(self._page_sql(self.page), include_sql_in_payload=False)
            finally:
                await client.close()
            return pg_json

        def _done(fut):
            try:
                pg_json = fut.result()
            except Exception as e:
                self.after(0, lambda: self._fail(e)); return
            try:
                payload = json.loads(pg_json)
            except Exception as e:
                self.after(0, lambda: self._fail(f"JSON parse error: {e}")); return
            self.after(0, lambda: self._apply_payload(payload, self.page, self.total_rows))

        self._lt.submit(_job()).add_done_callback(_done)

    def _parse_count(self, payload_json):
        try:
            p = json.loads(payload_json)
            cols = p.get("columns") or p.get("Cols") or []
            rows = p.get("rows") or p.get("Rows") or []
            if rows and cols:
                if "cnt" in cols:
                    i = cols.index("cnt")
                else:
                    i = 0
                return int(rows[0][i])
            return int(rows[0][0])
        except Exception:
            return 0

    # ---------- apply page from payload (single apply — 100 righe veloce) ----------
    def _apply_payload(self, payload, page_num, total_rows):
        try:
            if payload.get("error"):
                self._fail(payload["error"]); return
            cols = payload.get("columns") or payload.get("Cols") or []
            rows = payload.get("rows") or payload.get("Rows") or []

            # normalizza a liste di liste
            data = []
            for r in rows:
                if isinstance(r, dict):
                    data.append([r.get(c) for c in cols])
                elif isinstance(r, (list, tuple)):
                    data.append(list(r))
                else:
                    data.append([r])

            # apply
            self.sheet.set_sheet_data(data, reset_col_positions=True,
                                      reset_row_positions=True, redraw=True)
            if cols:
                self.sheet.headers(cols)

            self.lbl_info.config(text=f"Righe totali: {total_rows}")
            self.ent_page.set(str(page_num)); self._busy_off()
        except Exception as e:
            self._fail(e)

    # ---------- apply page from cache ----------
    def _apply_cached_page(self):
        start = (self.page - 1) * self.page_size
        end = min(start + self.page_size, len(self._cache_rows))
        page_rows = self._cache_rows[start:end]
        try:
            self.sheet.set_sheet_data(page_rows, reset_col_positions=True,
                                      reset_row_positions=True, redraw=True)
            # headers già impostati quando è partita la cache
            self.lbl_info.config(text=f"Righe totali (cache): {len(self._cache_rows)}")
            self.ent_page.set(str(self.page)); self._busy_off()
        except Exception as e:
            self._fail(e)

    # ---------- prefetch in background (scarica tutto il dataset in batch) ----------
    def _toggle_prefetch(self):
        self.prefetch_all = self.prefetch_var.get()
        if self.prefetch_all and not self._cache_ready:
            self._start_prefetch_background()

    def _start_prefetch_background(self):
        # evita doppi prefetch
        if self._prefetch_task is not None:
            return

        # reset cache
        self._cache_rows = []
        self._cache_ready = False

        # prepara overlay progress determinato (ma NON blocchiamo i comandi pager)
        # quindi non usiamo _busy_on; mostriamo un badge nello status
        self.lbl_info.config(text="Prefetch in corso… 0%")

        async def _job():
            client = AsyncMSSQLClient(self._dsn, enable_log=False)
            try:
                # prendi header e prima pagina per fissare l'ordine colonne
                first_json = await client.query_json(self._page_sql(1), include_sql_in_payload=False)
                first = json.loads(first_json)
                cols = first.get("columns") or first.get("Cols") or []
                rows = first.get("rows") or first.get("Rows") or []
                def norm(block):
                    out = []
                    for r in block:
                        if isinstance(r, dict):
                            out.append([r.get(c) for c in cols])
                        elif isinstance(r, (list, tuple)):
                            out.append(list(r))
                        else:
                            out.append([r])
                    return out
                cache = norm(rows)

                # imposta header subito
                def _set_headers():
                    if cols:
                        try:
                            self.sheet.headers(cols)
                        except Exception:
                            pass
                self.after(0, _set_headers)

                total = self.total_rows
                fetched = len(cache)

                # batch successivi
                page_idx = 2
                while fetched < total:
                    batch = min(self.prefetch_chunk, total - fetched)
                    # calcola pagina e page_size equivalenti per usare OFFSET/FETCH
                    # (batch potrebbe essere multipli della page_size, va bene)
                    off = fetched
                    sql = (f"SELECT {self.columns} FROM {self.table}"
                           f"{self._where_sql()}{self._order_sql()}OFFSET {off} ROWS "
                           f"FETCH NEXT {batch} ROWS ONLY;")
                    block_json = await client.query_json(sql, include_sql_in_payload=False)
                    p = json.loads(block_json)
                    block = p.get("rows") or p.get("Rows") or []
                    cache.extend(norm(block))
                    fetched = len(cache)

                    # update UI progress
                    def _upd():
                        pct = int((fetched / total) * 100) if total else 100
                        self.lbl_info.config(text=f"Prefetch in corso… {pct}%")
                    self.after(0, _upd)

                    page_idx += 1

            finally:
                await client.close()

            return cache

        def _done(fut):
            try:
                cache = fut.result()
            except Exception as e:
                self.after(0, lambda: self._prefetch_fail(e)); return

            def _apply_cache():
                self._cache_rows = cache or []
                self._cache_ready = True
                self.total_pages = max(1, (len(self._cache_rows) + self.page_size - 1)//self.page_size)
                self._update_buttons()
                self.lbl_info.config(text=f"Prefetch completato – righe totali cache: {len(self._cache_rows)}")
            self.after(0, _apply_cache)

        self._prefetch_task = self._lt.submit(_job())
        self._prefetch_task.add_done_callback(_done)

    def _prefetch_fail(self, e):
        self._prefetch_task = None
        self.lbl_info.config(text=f"Prefetch fallito: {e}")

    # ---------- misc ----------
    def destroy(self):
        try:
            self._lt.stop()
        except Exception:
            pass
        return super().destroy()

