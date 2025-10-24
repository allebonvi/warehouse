SELECT  *  FROM vViewMappaturaDescrizioneCorsia  WHERE ( Area > 0) ORDER BY Area Desc

SELECT  *  FROM Celle  WHERE ( ID > 0) ORDER BY ID Desc

SELECT TOP 1000 [mc_X]      ,[minFila]      ,[maxFila]      ,[minColonna]      ,[maxColonna]      ,[mc_Numero_Magazzino]      ,[mc_Numero_Area]  FROM vViewMappaturaPosizCorsia   WHERE  [mc_Numero_Area] =1


SELECT  CASE WHEN Nota = 'ASC' THEN 0 ELSE CASE WHEN Nota = 'DESC' THEN 1 END END AS Nota  FROM MagLayout WHERE     (IDArea  = 1) 

SELECT ID, Descrizione FROM Magazzini ORDER BY Descrizione

SELECT ID, Descrizione FROM Celle ORDER BY Descrizione

SELECT [ID],[CorsiaDescrizione] FROM vViewMappaturaDescrizioneCorsia


 SELECT     COUNT(DISTINCT Pallet) AS Pallet, COUNT(DISTINCT Lotto) AS Lotto, COUNT(DISTINCT Articolo) AS Articolo, COUNT(DISTINCT Descrizione) AS Descrizione, SUM(Qta) AS Qta, Documento, CodNazione, NAZIONE, Stato, MAX(PalletCella) AS PalletCella, MAX(Magazzino) AS Magazzino, MAX(Area) AS Area, MAX(Cella) AS Cella, MIN(Ordinamento) AS Ordinamento, MAX(IDStato) AS IDStato  FROM         dbo.XMag_ViewPackingList  GROUP BY Documento, CodNazione, NAZIONE, Stato 
 
 SELECT * FROM vViewPackingListRestante WHERE Documento = 237 ORDER BY Ordinamento 
 SELECT * FROM ViewPackingListRestante WHERE Documento = 246 ORDER BY Ordinamento 
 



USE master;
GO

-- (facoltativo) terminare connessioni attive
ALTER DATABASE SAMA1 SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
GO

-- Ripristino dal tuo snapshot
RESTORE DATABASE SAMA1
FROM DATABASE_SNAPSHOT = 'SAMA1_SNAP_20251014_112623';
GO

-- Riporta il DB in multi-user
ALTER DATABASE SAMA1 SET MULTI_USER;
GO



SELECT @@SERVERNAME AS server_name, DB_NAME() AS database_name;

SELECT name, create_date 
FROM sys.databases 
WHERE source_database_id IS NOT NULL;


SELECT COUNT(*) AS righe FROM dbo.XMag_ViewPackingList;

SELECT COUNT(*) AS righe FROM dbo.ViewPackingListRestante;

SELECT Documento, Stato, IDStato, NAZIONE, COUNT(*) AS righe
FROM dbo.ViewPackingListRestante
WHERE Documento IN (240,241)
GROUP BY Documento, Stato, IDStato, NAZIONE;



EXEC sp_refreshview N'dbo.XMag_ViewPackingList';
EXEC sp_refreshview N'dbo.ViewPackingListRestante';