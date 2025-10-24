
-- ==========================================================
-- Snapshot utilities for database: Mediseawall (SQL Server)
-- Version: 1.1 (fixed backslash handling for file paths)
-- Creates:
--   dbo.usp_Mediseawall_TakeSnapshot(@DbName, @SnapshotName)
--   dbo.usp_Mediseawall_RevertToSnapshot(@DbName, @SnapshotName)
-- ==========================================================

USE [master];
GO

IF OBJECT_ID('dbo.usp_Mediseawall_TakeSnapshot') IS NOT NULL
    DROP PROCEDURE dbo.usp_Mediseawall_TakeSnapshot;
GO

CREATE PROCEDURE dbo.usp_Mediseawall_TakeSnapshot
    @DbName       sysname = N'Mediseawall',
    @SnapshotName sysname = NULL
AS
BEGIN
    SET NOCOUNT ON;

    IF DB_ID(@DbName) IS NULL
    BEGIN
        RAISERROR('Database %s non trovato.', 16, 1, @DbName);
        RETURN;
    END

    DECLARE @ts nvarchar(32) = CONVERT(nvarchar(8), GETDATE(), 112) + N'_' +
                               REPLACE(CONVERT(nvarchar(8), GETDATE(), 108), N':', N'');
    IF @SnapshotName IS NULL
        SET @SnapshotName = @DbName + N'_SNAP_' + @ts;

    DECLARE @quotedSnapshot sysname = QUOTENAME(@SnapshotName);

    DECLARE @sql nvarchar(max) = N'CREATE DATABASE ' + @quotedSnapshot + N' ON ';
    DECLARE @sep nvarchar(2) = N'';

    ;WITH f AS (
        SELECT mf.name AS logical_name, mf.physical_name
        FROM sys.master_files AS mf
        WHERE mf.database_id = DB_ID(@DbName)
          AND mf.type = 0               -- ROWS (data files only)
    )
    SELECT
        @sql = @sql + @sep + N'(NAME = N''' +
               REPLACE(f.logical_name, N'''', N'''''') + N''', FILENAME = N''' +
               REPLACE(
                    -- directory of the data file (without trailing backslash)
                    LEFT(f.physical_name, LEN(f.physical_name) - CHARINDEX('\', REVERSE(f.physical_name)))
                    + N'\' + @DbName + N'_' + REPLACE(f.logical_name, ' ', '_') + N'_' + @ts + N'.ss',
                    N'''', N''''''
               ) + N''')',
        @sep = N', '
    FROM f;

    SET @sql = @sql + N' AS SNAPSHOT OF ' + QUOTENAME(@DbName) + N';';

    EXEC (@sql);

    SELECT SnapshotName = @SnapshotName, Sql = @sql;
END
GO

IF OBJECT_ID('dbo.usp_Mediseawall_RevertToSnapshot') IS NOT NULL
    DROP PROCEDURE dbo.usp_Mediseawall_RevertToSnapshot;
GO

CREATE PROCEDURE dbo.usp_Mediseawall_RevertToSnapshot
    @DbName       sysname = N'Mediseawall',
    @SnapshotName sysname = NULL
AS
BEGIN
    SET NOCOUNT ON;

    IF DB_ID(@DbName) IS NULL
    BEGIN
        RAISERROR('Database %s non trovato.', 16, 1, @DbName);
        RETURN;
    END

    IF @SnapshotName IS NULL
    BEGIN
        SELECT TOP (1) @SnapshotName = name
        FROM sys.databases
        WHERE source_database_id = DB_ID(@DbName)
        ORDER BY create_date DESC;
    END

    IF @SnapshotName IS NULL
    BEGIN
        RAISERROR('Nessuno snapshot trovato per %s.', 16, 1, @DbName);
        RETURN;
    END

    DECLARE @quotedSnapshot sysname = QUOTENAME(@SnapshotName);
    DECLARE @sql nvarchar(max) = N'
        ALTER DATABASE ' + QUOTENAME(@DbName) + N' SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
        RESTORE DATABASE ' + QUOTENAME(@DbName) + N' FROM DATABASE_SNAPSHOT = ' + @quotedSnapshot + N';
        ALTER DATABASE ' + QUOTENAME(@DbName) + N' SET MULTI_USER;';

    EXEC (@sql);

    SELECT RestoredTo = @SnapshotName;
END
GO

EXEC dbo.usp_Mediseawall_TakeSnapshot @DBName=N'Mediseawall'


--cotroll o che esista lo snapshot
SELECT
  name              AS snapshot_name,
  create_date,
  state_desc,
  is_read_only,
  source_database_id
FROM sys.databases
WHERE source_database_id = DB_ID('Mediseawall')
ORDER BY create_date DESC;


--controllo che esistea il file fisico dello snapshot
SELECT
  DB_NAME(mf.database_id) AS dbname,
  mf.type_desc,
  mf.physical_name,
  (mf.size*8)/1024 AS sizeMB
FROM sys.master_files mf
JOIN sys.databases d
  ON d.database_id = mf.database_id
WHERE d.source_database_id = DB_ID('Mediseawall');

SELECT name, create_date FROM sys.databases
WHERE source_database_id = DB_ID('Mediseawall')
ORDER BY create_date DESC;