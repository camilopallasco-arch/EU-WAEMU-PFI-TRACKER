# European public finance in the WAEMU — tracker

An interactive globe of investments by EU public financial institutions (DFIs, bilateral
development banks, national promotional banks, export credit agencies, plus the EIB and EBRD)
in the eight WAEMU countries: Benin, Burkina Faso, Côte d'Ivoire, Guinea-Bissau, Mali, Niger,
Senegal and Togo. Data refreshes automatically on the 1st of every month.

## Set it up (no installation needed)

1. Create a free account at https://github.com.
2. Click **New repository**. Name it `eu-pfi-waemu-tracker`, choose **Public**, click **Create repository**.
3. Click **uploading an existing file**, drag in everything from this folder **except the `raw` folder**
   (GitHub downloads that itself), and click **Commit changes**.
   The `.github` folder is hidden on Mac/Windows: show hidden files (Mac: Cmd+Shift+.) so you can drag it in.
4. Go to **Settings → Pages**. Under "Build and deployment", set **Source** to **GitHub Actions**.
5. Go to **Settings → Actions → General**, scroll to "Workflow permissions", choose
   **Read and write permissions**, and save.
6. Open the **Actions** tab, click **Monthly update**, then **Run workflow**. After about 5 minutes
   your site is live at `https://<your-username>.github.io/eu-pfi-waemu-tracker/`.

From then on it updates itself on the 1st of each month. A green tick in the Actions tab means
the run worked; a red cross means something failed (click it to read the log).

## Adding deals by hand (ECAs, promotional banks, missing DFIs)

Edit `data/manual_entries.csv` directly on GitHub (open the file, click the pencil icon).
One row per deal:

| column | example |
|---|---|
| institution_id | `sace` (see `data/institutions.csv` for all ids) |
| title | `Dakar water desalination plant` |
| client | `SONES` |
| countries | `SN` or `SN\|CI` (ISO codes, separated by `\|`) |
| year | `2024` |
| instrument | `Loan`, `Equity`, `Guarantee`, `Grant` or `Insurance` |
| sector | `Water` |
| amount, currency | `45000000`, `EUR` |
| source_url | link to the press release or report |

Saving the file republishes the site within minutes.

## How it works

| file | what it does |
|---|---|
| `fetch_*.py` | download each source into `raw/` |
| `normalize.py` | convert every source into the shared data model in `data/` |
| `build_site.py` | put the data into `site/index.html` |
| `run_all.py` | run everything in order, write `data/changelog.csv` |
| `.github/workflows/monthly.yml` | runs `run_all.py` on GitHub every month |

## Data model (`data/`)

- `institutions.csv` covers every institution in scope, with its type, member state, HQ coordinates and coverage status.
- `investments.csv` has one row per deal. It includes the amount in original currency and EUR (ECB monthly rate; XOF fixed at 655.957), instrument, sector, client and its domicile, E&S category, and source link.
- `investment_countries.csv` splits each deal across WAEMU countries. `attribution_method` takes one of these values:
  - `single_country` for a deal in one country.
  - `iati_percentage` when the publisher states the country shares.
  - `equal_split_estimate` for multi-country deals with no published shares.
  - `regional_unallocated` for regional deals that only mention a WAEMU country. These are listed but excluded from totals.
- `geo_precision` is `site` when the publisher gives coordinates, otherwise `country_centroid`.
- `sources.csv`, `countries.csv` and `changelog.csv` hold the provenance, reference data and monthly change log.

## Sources and known gaps

Automated sources are IATI via d-portal (AFD, KfW Development Bank, FMO, EIB, EBRD, Atradius DSB,
Invest International, DGGF), the Proparco website, the BIO website, the DEG CSV export, and the
Finnfund and IFU APIs.

Not yet covered: Swedfund, COFIDES and OeEB load their portfolios with JavaScript (needs a
headless browser or manual entry); SIMEST and SOFID; most ECAs and NPBs, which disclose little
project-level data. Add these through `manual_entries.csv`. The Early Warning System
(ews.rightsindevelopment.org, free account) is a useful cross-check.

Caveats: IATI amounts for AFD and KfW include grants and small NGO projects, so filter by instrument
for investment-only views. Amounts are commitments at signing, not current exposure.
