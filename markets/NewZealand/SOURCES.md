# Sources and evidence

## NZX Main Board

Official market page: `https://www.nzx.com/markets/NZSX`

Used to seed the current instrument universe. It includes both equities and funds, therefore every item is profile-resolved and filtered before becoming an issuer.

## NZX company profile

Pattern: `https://www.nzx.com/companies/{TICKER}`

Provides company code, ordinary-share ISIN where present, instrument type, primary listing venue, issuer website and fiscal-year end.

## NZX company Documents

Pattern: `https://www.nzx.com/companies/{TICKER}/documents`

Some issuers expose direct historical `Annual Report - YYYY` PDF links. Example verified during design: NZX Limited exposes annual reports from 2013 through 2025, covering the complete required 2017-2025 range.

## NZX annual-report announcements

Annual-report announcements use type `ANNREP`. Official announcement attachments can resolve to `api.nzx.com/public/announcement/.../attachment/...pdf`.

## NZX Data Products

NZX advertises Company Research Centre / i-search and historical announcement/data products. Company Research Centre states annual reports date back to 1983. These licensed/authorized exports are the preferred production source for a commercial large-scale corpus.

## NZX Website Terms

Official terms: `https://www.nzx.com/meta-pages/terms-of-use`

The public-site adapter is gated behind explicit acknowledgement. The project does not bypass access controls.

## ISO MIC

ISO 10383 identifies `XNZE` as New Zealand Exchange / NZX all markets. ZETA country ISO-3 is `NZL`.
