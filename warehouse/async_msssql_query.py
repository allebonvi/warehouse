# async_msssql_query.py — loop-safe, compat rows=list, no pooling
from __future__ import annotations

import asyncio, urllib.parse, time, logging
from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy import text

try:
    import orjson as _json
    def _dumps(obj: Any) -> str: return _json.dumps(obj, default=str).decode("utf-8")
except Exception:
    import json as _json
    def _dumps(obj: Any) -> str: return _json.dumps(obj, default=str)

def make_mssql_dsn(
    *, server: str, database: str, user: Optional[str]=None, password: Optional[str]=None,
    driver: str="ODBC Driver 17 for SQL Server", trust_server_certificate: bool=True,
    encrypt: Optional[str]=None, extra_odbc_kv: Optional[Dict[str,str]]=None
) -> str:
    kv = {"DRIVER": driver, "SERVER": server, "DATABASE": database,
          "TrustServerCertificate": "Yes" if trust_server_certificate else "No"}
    if user: kv["UID"] = user
    if password: kv["PWD"] = password
    if encrypt: kv["Encrypt"] = encrypt
    if extra_odbc_kv: kv.update(extra_odbc_kv)
    odbc = ";".join(f"{k}={v}" for k,v in kv.items()) + ";"
    return f"mssql+aioodbc:///?odbc_connect={urllib.parse.quote_plus(odbc)}"

class AsyncMSSQLClient:
    """
    Engine creato pigramente sul loop corrente, senza pool (NullPool).
    Evita “Future attached to a different loop” nei reset/close del pool.
    """
    def __init__(self, dsn: str, *, echo: bool=False, log: bool=True):
        self._dsn = dsn
        self._echo = echo
        self._engine = None
        self._engine_loop: Optional[asyncio.AbstractEventLoop] = None
        self._logger = logging.getLogger("AsyncMSSQLClient")
        if log and not self._logger.handlers:
            h = logging.StreamHandler()
            h.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
            self._logger.addHandler(h)
        self._enable_log = log

    async def _ensure_engine(self):
        if self._engine is not None:
            return
        loop = asyncio.get_running_loop()
        self._engine = create_async_engine(
            self._dsn,
            echo=self._echo,
            # IMPORTANTI:
            poolclass=NullPool,                 # no pooling → no reset su loop “sbagliati”
            connect_args={"loop": loop},        # usa il loop corrente in aioodbc
        )
        self._engine_loop = loop
        if self._enable_log:
            self._logger.info("Engine created on loop %s", id(loop))

    async def dispose(self):
        if self._engine is None:
            return
        # sempre sullo stesso loop in cui è nato
        if asyncio.get_running_loop() is self._engine_loop:
            await self._engine.dispose()
        else:
            fut = asyncio.run_coroutine_threadsafe(self._engine.dispose(), self._engine_loop)
            fut.result(timeout=2)
        self._engine = None
        if self._enable_log:
            self._logger.info("Engine disposed")

    async def query_json(self, sql: str, params: Optional[Dict[str, Any]]=None, *, as_dict_rows: bool=False) -> Dict[str, Any]:
        await self._ensure_engine()
        t0 = time.perf_counter()
        async with self._engine.connect() as conn:
            res = await conn.execute(text(sql), params or {})
            rows = res.fetchall()
            cols = list(res.keys())
        if as_dict_rows:
            rows_out = [dict(zip(cols, r)) for r in rows]
        else:
            rows_out = [list(r) for r in rows]
        return {"columns": cols, "rows": rows_out, "elapsed_ms": round((time.perf_counter()-t0)*1000, 3)}

    async def exec(self, sql: str, params: Optional[Dict[str, Any]]=None, *, commit: bool=False) -> int:
        await self._ensure_engine()
        async with (self._engine.begin() if commit else self._engine.connect()) as conn:
            res = await conn.execute(text(sql), params or {})
            return res.rowcount or 0
