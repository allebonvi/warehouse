# db_async_singleton.py
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

class AsyncDB:
    def __init__(self, engine):
        self.engine = engine

    async def query_json(self, sql: str, params: dict):
        async with self.engine.connect() as conn:
            result = await conn.execute(text(sql), params)
            rows = [tuple(r) for r in result]
            return {"rows": rows}

_ENGINE = None

async def _make_engine_async(conn_str: str):
    return create_async_engine(conn_str, pool_pre_ping=True, future=True)

def get_db(loop: asyncio.AbstractEventLoop, conn_str: str) -> AsyncDB:
    """Crea l'engine UNA volta, dentro il loop globale, e restituisce il client."""
    global _ENGINE
    if _ENGINE is None:
        fut = asyncio.run_coroutine_threadsafe(_make_engine_async(conn_str), loop)
        _ENGINE = fut.result()
    return AsyncDB(_ENGINE)

async def dispose_async():
    global _ENGINE
    if _ENGINE is not None:
        await _ENGINE.dispose()
        _ENGINE = None
