-- dbo.XMag_DettaglioPallet source

ALTER VIEW [dbo].[XMag_DettaglioPallet]
AS
SELECT     dbo.MagazziniPallet.ID, dbo.MagazziniPallet.Tipo, dbo.MagazziniPallet.IDRiferimento, dbo.MagazziniPallet.NumeroPallet, 
                      dbo.MagazziniPallet.IDMagazzino, dbo.MagazziniPallet.IDArea, dbo.MagazziniPallet.IDCella, dbo.MagazziniPallet.DataMagazzino, 
                      dbo.MagazziniPallet.PesoUnitario, dbo.MagazziniPallet.Tara, dbo.MagazziniPallet.Attributo, dbo.Celle.IDStato
FROM         dbo.MagazziniPallet INNER JOIN
                      dbo.Celle ON dbo.MagazziniPallet.IDCella = dbo.Celle.ID
WHERE     (dbo.MagazziniPallet.Tipo = 'V')
UNION ALL
SELECT     MagazziniPallet_1.ID, MagazziniPallet_1.Tipo, MagazziniPallet_1.IDRiferimento, MagazziniPallet_1.NumeroPallet, MagazziniPallet_1.IDMagazzino, 
                      MagazziniPallet_1.IDArea, MagazziniPallet_1.IDCella, MagazziniPallet_1.DataMagazzino, - (1 * MagazziniPallet_1.PesoUnitario) AS PesoUnitario, 
                      MagazziniPallet_1.Tara, MagazziniPallet_1.Attributo, Celle_1.IDStato
FROM         dbo.MagazziniPallet AS MagazziniPallet_1 INNER JOIN
                      dbo.Celle AS Celle_1 ON MagazziniPallet_1.IDCella = Celle_1.ID
WHERE     (MagazziniPallet_1.Tipo = 'P');

:commento
Dalla tabella Celle e MagazziniPallet ottengo l'insieme delle celle con tipo V = vuota  e p=piena, le celle in questo caso possono essere di qualunque tipo cioè fare riferimento a pallet ancora in deposito oppure già spediti, o piene (1A.15.0e) o spedite (7G.01.01). 


ALTER VIEW dbo.XMag_GiacenzaPallet
AS
SELECT     Attributo AS BarcodePallet, NumeroPallet, IDMagazzino, IDArea, IDCella, SUM(PesoUnitario) AS Peso, Attributo AS CodiceProdotto, IDStato
FROM         dbo.XMag_DettaglioPallet
GROUP BY NumeroPallet, IDMagazzino, IDArea, IDCella, Attributo, IDStato
HAVING      (SUM(PesoUnitario) > 0);
commento:
Ricomprimo la vista ..dettaglio perchè capita che una udc sia stata allocata più volte sulla stessa cella, la riga in questione appare doppia se non si tiene conto della data in cui è avvenuta la lettura  .SI potrebbe pensare di prendere sempre la data più alta , cioè l'ultima a parità di unità di carico. 


ALTER VIEW [dbo].[XMag_GiacenzaPalletxUbicazioneCella]
AS
SELECT    dbo.Celle.ID as IDCella,  dbo.vXTracciaProdotti.Pallet, dbo.vXTracciaProdotti.Lotto, dbo.vXTracciaProdotti.Prodotto, dbo.vXTracciaProdotti.Descrizione, UPPER(REPLICATE('0', 
                      3 - DATALENGTH(dbo.Celle.Corsia)) + dbo.Celle.Corsia + '.' + + REPLICATE('0', 2 - DATALENGTH(dbo.Celle.Colonna)) 
                      + dbo.Celle.Colonna + '.' + REPLICATE('0', 2 - DATALENGTH(dbo.Celle.Fila)) + dbo.Celle.Fila) AS Ubicazione
FROM         dbo.XMag_GiacenzaPallet 
INNER JOIN
                      dbo.vXTracciaProdotti ON dbo.XMag_GiacenzaPallet.BarcodePallet = dbo.vXTracciaProdotti.Pallet COLLATE Latin1_General_CI_AS 
                      LEFT OUTER JOIN
                      dbo.Celle ON dbo.XMag_GiacenzaPallet.IDCella = dbo.Celle.ID;
					  
					  :commento
qui commbino una vista proveniente da sam in cui vado a cercare i dati della unità di carico e li combino con la tabella vista giacenzapallet, in pratica definisco dove in quale ubicazione si trova il pallet

quindi in pratica ho 

tabella               vista                   vista
magazzinipallet ---->xmag_Dettagliopallet--->Xmag_giacenzapallet