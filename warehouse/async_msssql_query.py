# async_mssql_client.py
# pip install sqlalchemy[asyncio] aioodbc orjson

from __future__ import annotations
import asyncio
import logging
import time
from typing import Any, Dict, Iterable, List, Optional

try:
    import orjson as _json
    def _dumps(obj: Any) -> str:
        # default=str: serializza in modo sicuro datetimes/Decimal ecc.
        return _json.dumps(obj, default=str).decode("utf-8")
except Exception:
    import json as _json
    def _dumps(obj: Any) -> str:
        return _json.dumps(obj, default=str)

from urllib.parse import quote_plus
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy import text


def make_mssql_dsn(
    server: str,
    database: str,
    user: Optional[str] = None,
    password: Optional[str] = None,
    *,
    driver: str = "ODBC Driver 17 for SQL Server",
    trust_server_certificate: Optional[bool] = None,
    encrypt: Optional[str] = None,   # "yes"/"no" oppure "mandatory" (driver 18)
    extra_odbc_kv: Optional[Dict[str, str]] = None,
) -> str:
    """
    Crea un DSN leggibile per mssql+aioodbc usando una connection string ODBC “umana”
    che poi viene URL-encodata automaticamente.
    """
    parts: List[str] = [f"DRIVER={{{{}}}}".format(driver), f"SERVER={server}", f"DATABASE={database}"]
    if user is not None:
        parts.append(f"UID={user}")
    if password is not None:
        parts.append(f"PWD={password}")
    if encrypt is not None:
        parts.append(f"Encrypt={encrypt}")
    if trust_server_certificate is not None:
        parts.append(f"TrustServerCertificate={'Yes' if trust_server_certificate else 'No'}")
    if extra_odbc_kv:
        for k, v in extra_odbc_kv.items():
            parts.append(f"{k}={v}")

    odbc_str = ";".join(parts) + ";"
    return f"mssql+aioodbc:///?odbc_connect={quote_plus(odbc_str)}"


class AsyncMSSQLClient:
    """
    Client MSSQL async con:
    - query_json(sql, params, ...) -> JSON {columns, rows, rowcount, elapsed_ms, metadata}
    - logging opzionale (SQL, params, tempi, rowcount, eccezioni con traceback)
    - context manager async (facoltativo)

    Uso tipico:
        dsn = make_mssql_dsn("localhost", "MyDb", "user", "pass")
        client = AsyncMSSQLClient(dsn, enable_log=True)
        json_payload = asyncio.run(client.query_json("SELECT TOP 5 * FROM dbo.Clienti WHERE Attivo=:a", {"a": 1}))
    """

    def __init__(
        self,
        dsn: str,
        *,
        enable_log: bool = False,
        logger: Optional[logging.Logger] = None,
        engine_kwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._dsn = dsn
        self._engine: AsyncEngine = create_async_engine(dsn, future=True, **(engine_kwargs or {}))
        self._logger = logger or logging.getLogger(self.__class__.__name__)
        self._enable_log = enable_log

        if self._enable_log and not logger:
            # Configurazione “gentile”: se non hai un logger, attiviamo basicConfig
            logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    async def __aenter__(self) -> "AsyncMSSQLClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self) -> None:
        await self._engine.dispose()

    async def query_json(
        self,
        sql: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        max_rows: Optional[int] = None,
        as_dict_rows: bool = False,
        include_sql_in_payload: bool = False,
    ) -> str:
        """
        Esegue una SELECT (o qualsiasi statement che ritorni righe) in modo asincrono.

        Ritorna un JSON con:
            {
              "columns": [...],
              "rows": [[...], ...]      # oppure [{"col": val, ...}, ...] se as_dict_rows=True
              "rowcount": int,
              "elapsed_ms": float,
              "metadata": {"dialect": "...", "driver": "..."},
              "sql": "...", "params": {...}  # opzionali se include_sql_in_payload=True
            }

        Logging:
          - se enable_log=True, logga la query, i params, il tempo e l’eventuale eccezione.
        """
        t0 = time.perf_counter()
        if self._enable_log:
            self._logger.info("SQL start")
            self._logger.info("query=%s", sql)
            if params:
                self._logger.info("params=%s", params)

        try:
            async with self._engine.connect() as conn:
                res = await conn.execute(text(sql), params or {})
                cols = list(res.keys())

                if as_dict_rows:
                    # mappature (dict per riga)
                    rows_iter = res.mappings()
                    rows = (await rows_iter.fetchall()) if max_rows is None else await rows_iter.fetchmany(max_rows)
                    data = [dict(r) for r in rows]
                else:
                    # lista di liste
                    rows = res.fetchall() if max_rows is None else res.fetchmany(max_rows)
                    data = [[row[i] for i in range(len(cols))] for row in rows]

                elapsed = round((time.perf_counter() - t0) * 1000, 3)
                payload = {
                    "columns": cols,
                    "rows": data,
                    "rowcount": res.rowcount if res.rowcount is not None else len(data),
                    "elapsed_ms": elapsed,
                    "metadata": {
                        "dialect": conn.engine.dialect.name,
                        "driver": getattr(conn.engine.dialect, "driver", None),
                    },
                }
                if include_sql_in_payload:
                    payload["sql"] = sql
                    if params:
                        payload["params"] = params

                if self._enable_log:
                    self._logger.info("SQL done: rowcount=%s elapsed_ms=%.3f", payload["rowcount"], elapsed)

                return _dumps(payload)

        except Exception as e:
            if self._enable_log:
                self._logger.exception("SQL error while executing query")  # traceback completo
            # Rispondiamo con un payload di errore utile al chiamante
            elapsed = round((time.perf_counter() - t0) * 1000, 3)
            err_payload = {
                "error": str(e),
                "elapsed_ms": elapsed,
                "sql": sql if include_sql_in_payload or self._enable_log else None,
                "params": (params or None) if (include_sql_in_payload or self._enable_log) else None,
            }
            return _dumps(err_payload)

    async def execute_non_query(
        self,
        sql: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        commit: bool = True,
    ) -> int:
        """
        Per INSERT/UPDATE/DELETE. Ritorna il rowcount. Con commit=True apre una transazione.
        Logga errori se enable_log=True.
        """
        t0 = time.perf_counter()
        if self._enable_log:
            self._logger.info("EXEC start")
            self._logger.info("query=%s", sql)
            if params:
                self._logger.info("params=%s", params)
        try:
            async with self._engine.begin() if commit else self._engine.connect() as conn:
                res = await conn.execute(text(sql), params or {})
                rc = res.rowcount or 0
                if self._enable_log:
                    self._logger.info("EXEC done: rowcount=%s elapsed_ms=%.3f",
                                      rc, round((time.perf_counter() - t0) * 1000, 3))
                return rc
        except Exception:
            if self._enable_log:
                self._logger.exception("EXEC error")
            raise
