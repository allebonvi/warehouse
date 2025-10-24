from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Any, Dict, List


@dataclass
class SPResult:
    rc: int = 0                      # equivalente a @RC OUTPUT
    message: Optional[str] = ""      # eventuale messaggio/errore
    id_result: Optional[int] = None  # ID del record inserito in LogPackingList


# --- helpers per il client async (senza conoscere l'API esatta forniamo fallback robusti) ---
async def _query_one_value(db, sql: str, params: Dict[str, Any]) -> Optional[Any]:
    """
    Ritorna la prima colonna della prima riga, oppure None.
    Tenta prima query_json(...), poi altri metodi comuni.
    """
    if hasattr(db, "query_json"):
        res = await db.query_json(sql, params)
        # res può essere una lista di dict o un payload con rows/columns
        if isinstance(res, list) and res:
            row0 = res[0]
            if isinstance(row0, dict):
                # prima colonna disponibile
                return next(iter(row0.values()), None)
        elif isinstance(res, dict):
            rows = None
            for k in ("rows", "data", "result", "records"):
                if k in res and isinstance(res[k], list):
                    rows = res[k]
                    break
            if rows:
                r0 = rows[0]
                if isinstance(r0, dict):
                    return next(iter(r0.values()), None)
                if isinstance(r0, (list, tuple)) and r0:
                    return r0[0]
        return None

    # fallback: altri metodi (se esistono)
    if hasattr(db, "query_value"):
        return await db.query_value(sql, params)
    if hasattr(db, "scalar"):
        return await db.scalar(sql, params)
    raise RuntimeError("Il client DB non espone query_json/query_value/scalar")


async def _query_all(db, sql: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Ritorna una lista di dict {col:val}."""
    if hasattr(db, "query_json"):
        res = await db.query_json(sql, params)
        if res is None:
            return []
        if isinstance(res, list):
            return res if res and isinstance(res[0], dict) else []
        if isinstance(res, dict):
            for k in ("rows", "data", "result", "records"):
                if k in res and isinstance(res[k], list):
                    rows = res[k]
                    if rows and isinstance(rows[0], dict):
                        return rows
                    cols = res.get("columns") or res.get("cols") or []
                    out = []
                    for r in rows:
                        if isinstance(r, (list, tuple)) and cols:
                            out.append({ (cols[i] if i < len(cols) else f"c{i}") : r[i]
                                         for i in range(min(len(cols), len(r))) })
                    return out
        return []
    # fallback
    if hasattr(db, "fetch_all"):
        return await db.fetch_all(sql, params)
    raise RuntimeError("Il client DB non espone query_json/fetch_all")


async def _execute(db, sql: str, params: Dict[str, Any]) -> int:
    """
    Esegue DML e ritorna rowcount (se disponibile).
    Prova .execute / .exec / .execute_non_query / altrimenti usa query_json.
    """
    for name in ("execute", "exec", "execute_non_query"):
        if hasattr(db, name):
            rc = await getattr(db, name)(sql, params)
            # alcuni client ritornano None, altri rowcount, altri payload
            if isinstance(rc, int):
                return rc
            return 0
    # fallback rozzo: molti back-end accettano anche DML in query_json
    if hasattr(db, "query_json"):
        await db.query_json(sql, params)
        return 0
    raise RuntimeError("Il client DB non espone metodi di esecuzione DML noti")


# --- Procedura portata in async, usando il client DB passato dall'app ---
async def sp_xExePackingListPallet_async(db, IDOperatore: int, Documento: str) -> SPResult:
    """
    Porting asincrono di [dbo].[sp_xExePackingListPallet] usando il client DB già aperto dall'app.
    Logica:
      1) Recupera LOGIN operatore
      2) Elenca le celle (DISTINCT Cella da XMag_ViewPackingList per Documento)
      3) Per ogni cella: leggi IDStato e toggla 0<->1 + aggiorna ModUtente/ModDataOra
      4) Description = TOP 1 NAZIONE per Documento
      5) Inserisci LogPackingList(Code=Documento, Description, IDInsUser=IDOperatore, InsDateTime=GETDATE())
    """
    try:
        # 1) LOGIN operatore (se manca, prosegue come da SP originaria)
        nominativo = await _query_one_value(
            db,
            "SELECT LOGIN FROM Operatori WHERE id = :IDOperatore",
            {"IDOperatore": IDOperatore}
        ) or ""

        # 2) Celle da trattare
        celle = await _query_all(
            db,
            """
            SELECT DISTINCT Cella
            FROM dbo.XMag_ViewPackingList
            WHERE Documento = :Documento
            """,
            {"Documento": Documento}
        )
        id_celle = [r.get("Cella") for r in celle if "Cella" in r]

        # 3) Toggle stato per ogni cella
        for id_cella in id_celle:
            if id_cella is None:
                continue
            stato = await _query_one_value(
                db,
                "SELECT IDStato FROM Celle WHERE ID = :IDC",
                {"IDC": id_cella}
            )
            if stato == 0:
                await _execute(
                    db,
                    """
                    UPDATE Celle
                       SET IDStato = 1,
                           ModUtente = :N,
                           ModDataOra = GETDATE()
                     WHERE ID = :IDC
                    """,
                    {"N": nominativo, "IDC": id_cella}
                )
            else:
                await _execute(
                    db,
                    """
                    UPDATE Celle
                       SET IDStato = 0,
                           ModUtente = :N,
                           ModDataOra = GETDATE()
                     WHERE ID = :IDC
                    """,
                    {"N": nominativo, "IDC": id_cella}
                )

        # 4) Description = NAZIONE (TOP 1)
        description = await _query_one_value(
            db,
            """
            SELECT TOP 1 NAZIONE
            FROM dbo.XMag_ViewPackingList
            WHERE Documento = :Documento
            GROUP BY Documento, NAZIONE
            ORDER BY NAZIONE
            """,
            {"Documento": Documento}
        )

        # 5) LogPackingList
        await _execute(
            db,
            """
            INSERT INTO dbo.LogPackingList (Code, Description, IDInsUser, InsDateTime)
            VALUES (:Code, :Descr, :IDInsUser, GETDATE());
            """,
            {"Code": Documento, "Descr": description, "IDInsUser": IDOperatore}
        )

        # Se vuoi proprio l'ID appena inserito:
        new_id = await _query_one_value(db, "SELECT SCOPE_IDENTITY() AS ID", {})
        return SPResult(rc=0, message="", id_result=int(new_id) if new_id is not None else None)

    except Exception as e:
        return SPResult(rc=-1, message=str(e), id_result=None)
