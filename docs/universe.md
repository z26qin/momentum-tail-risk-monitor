# Proxy universe for the positioning panel

- **Source:** Nasdaq stock screener (api.nasdaq.com/api/screener/stocks)
- **Retrieved (UTC):** 2026-07-25T03:10:52+00:00
- **Definition:** the 200 largest US-domiciled, US-listed common stocks by market capitalisation on the retrieval date, after excluding warrants, units, preferred shares, depositary shares, rights, notes, and fund/trust vehicles by instrument name, and after requiring at least $5,000,000 of traded notional on the snapshot date.
- **Liquidity floor rationale:** market capitalisation alone admitted an exchangeable debenture trading zero shares a day, whose days-to-cover of 120 moved the whole leg average. The floor sits three orders of magnitude below the least liquid genuine constituent.
- **Smallest member by market capitalisation:** $61.2B
- **Largest member:** $5.01T

## Survivorship warning

This list is **current membership applied historically**. Every output
derived from it inherits survivorship bias:

- Companies that were large during the sample but were later acquired,
  delisted, or fell out of the top 200 are absent for the entire sample,
  not just for the period after they left.
- Companies that grew into the top 200 late in the sample are present from
  the beginning, on the strength of information that did not exist then.
- The screen is by market capitalisation, so the universe is large-cap
  dominated. A real momentum loser decile contains far more mid- and
  small-cap names, which are also the names where short-leg crowding is
  most acute. The panel therefore understates crowding relative to a true
  momentum universe.

It is a labelled proxy for the momentum loser leg, not a reconstruction of
it. Production would use CRSP/Compustat point-in-time index constituents.

## Constituents

| Rank | Symbol | Name | Sector | Market cap (USD bn) |
|---:|---|---|---|---:|
| 1 | `NVDA` | NVIDIA Corporation Common Stock | Technology | 5,005.5 |
| 2 | `AAPL` | Apple Inc. Common Stock | Technology | 4,891.2 |
| 3 | `GOOGL` | Alphabet Inc. Class A Common Stock | Technology | 3,874.0 |
| 4 | `GOOG` | Alphabet Inc. Class C Capital Stock | Technology | 3,866.1 |
| 5 | `MSFT` | Microsoft Corporation Common Stock | Technology | 2,835.4 |
| 6 | `AMZN` | Amazon.com Inc. Common Stock | Consumer Discretionary | 2,496.8 |
| 7 | `AVGO` | Broadcom Inc. Common Stock | Technology | 1,817.0 |
| 8 | `META` | Meta Platforms Inc. Class A Common Stock | Technology | 1,510.8 |
| 9 | `SPCX` | Space Exploration Technologies Corp. Class A Common Stock | Technology | 1,506.4 |
| 10 | `TSLA` | Tesla Inc. Common Stock | Industrials | 1,175.7 |
| 11 | `LLY` | Eli Lilly and Company Common Stock | Health Care | 1,126.4 |
| 12 | `BRK-A` | Berkshire Hathaway Inc. | — | 1,095.8 |
| 13 | `BRK-B` | Berkshire Hathaway Inc. | — | 1,092.0 |
| 14 | `MU` | Micron Technology Inc. Common Stock | Technology | 1,040.1 |
| 15 | `JPM` | JP Morgan Chase & Co. Common Stock | Finance | 946.4 |
| 16 | `WMT` | Walmart Inc. Common Stock | Consumer Discretionary | 871.2 |
| 17 | `AMD` | Advanced Micro Devices Inc. Common Stock | Technology | 851.1 |
| 18 | `V` | Visa Inc. | Consumer Discretionary | 673.9 |
| 19 | `XOM` | ExxonMobil Holdings Corporation Common Stock | Energy | 650.5 |
| 20 | `JNJ` | Johnson & Johnson Common Stock | Health Care | 634.1 |
| 21 | `MA` | Mastercard Incorporated Common Stock | Consumer Discretionary | 476.8 |
| 22 | `INTC` | Intel Corporation Common Stock | Technology | 464.0 |
| 23 | `ABBV` | AbbVie Inc. Common Stock | Health Care | 458.2 |
| 24 | `CSCO` | Cisco Systems Inc. Common Stock (DE) | Telecommunications | 450.0 |
| 25 | `BAC` | Bank of America Corporation Common Stock | Finance | 440.3 |
| 26 | `AMAT` | Applied Materials Inc. Common Stock | Technology | 425.8 |
| 27 | `COST` | Costco Wholesale Corporation Common Stock | Consumer Discretionary | 414.7 |
| 28 | `CAT` | Caterpillar Inc. Common Stock | Industrials | 409.4 |
| 29 | `CVX` | Chevron Corporation Common Stock | Energy | 387.9 |
| 30 | `UNH` | UnitedHealth Group Incorporated Common Stock (DE) | Health Care | 382.1 |
| 31 | `LRCX` | Lam Research Corporation Common Stock | Technology | 381.7 |
| 32 | `GE` | GE Aerospace Common Stock | Technology | 367.0 |
| 33 | `KO` | Coca-Cola Company (The) Common Stock | Consumer Staples | 354.0 |
| 34 | `PG` | Procter & Gamble Company (The) Common Stock | Consumer Discretionary | 343.3 |
| 35 | `MS` | Morgan Stanley Common Stock | Finance | 338.3 |
| 36 | `HD` | Home Depot Inc. (The) Common Stock | Consumer Discretionary | 332.0 |
| 37 | `ORCL` | Oracle Corporation Common Stock | Technology | 331.2 |
| 38 | `MRK` | Merck & Company Inc. Common Stock (new) | Health Care | 323.7 |
| 39 | `GS` | Goldman Sachs Group Inc. (The) Common Stock | Finance | 313.1 |
| 40 | `PM` | Philip Morris International Inc Common Stock | Health Care | 300.8 |
| 41 | `PLTR` | Palantir Technologies Inc. Class A Common Stock | Technology | 294.7 |
| 42 | `NFLX` | Netflix Inc. Common Stock | Consumer Discretionary | 291.9 |
| 43 | `RTX` | RTX Corporation Common Stock | Industrials | 286.6 |
| 44 | `DELL` | Dell Technologies Inc. Class C Common Stock  | Technology | 283.5 |
| 45 | `KLAC` | KLA Corporation Common Stock | Technology | 275.0 |
| 46 | `GEV` | GE Vernova Inc. Common Stock | — | 270.3 |
| 47 | `WFC` | Wells Fargo & Company Common Stock | Finance | 264.1 |
| 48 | `PANW` | Palo Alto Networks Inc. Common Stock | Technology | 263.9 |
| 49 | `TXN` | Texas Instruments Incorporated Common Stock | Technology | 254.4 |
| 50 | `LIN` | Linde plc Ordinary Shares | Basic Materials | 237.0 |
| 51 | `C` | Citigroup Inc. Common Stock | Finance | 225.5 |
| 52 | `AXP` | American Express Company Common Stock | Finance | 222.6 |
| 53 | `ANET` | Arista Networks Inc. Common Stock | Telecommunications | 219.1 |
| 54 | `SNDK` | Sandisk Corporation Common Stock | Technology | 212.7 |
| 55 | `TMO` | Thermo Fisher Scientific Inc Common Stock | Industrials | 211.2 |
| 56 | `AMGN` | Amgen Inc. Common Stock | Health Care | 203.0 |
| 57 | `IBM` | International Business Machines Corporation Common Stock | Technology | 201.3 |
| 58 | `TMUS` | T-Mobile US Inc. Common Stock | Telecommunications | 194.9 |
| 59 | `VZ` | Verizon Communications Inc. Common Stock | Telecommunications | 193.7 |
| 60 | `MCD` | McDonald's Corporation Common Stock | Consumer Discretionary | 188.1 |
| 61 | `APH` | Amphenol Corporation Common Stock | Technology | 187.8 |
| 62 | `NEE` | NextEra Energy Inc. Common Stock | Technology | 187.2 |
| 63 | `CRWD` | CrowdStrike Holdings Inc. Class A Common Stock | Technology | 186.6 |
| 64 | `PEP` | PepsiCo Inc. Common Stock | Consumer Staples | 186.5 |
| 65 | `UNP` | Union Pacific Corporation Common Stock | Industrials | 182.5 |
| 66 | `ADI` | Analog Devices Inc. Common Stock | Technology | 181.1 |
| 67 | `ABT` | Abbott Laboratories Common Stock | Health Care | 179.5 |
| 68 | `WDC` | Western Digital Corporation Common Stock | Technology | 179.2 |
| 69 | `WELL` | Welltower Inc. Common Stock | Real Estate | 177.9 |
| 70 | `SCHW` | Charles Schwab Corporation (The) Common Stock | Finance | 177.3 |
| 71 | `QCOM` | QUALCOMM Incorporated Common Stock | Technology | 176.0 |
| 72 | `TJX` | TJX Companies Inc. (The) Common Stock | Consumer Discretionary | 170.4 |
| 73 | `MRVL` | Marvell Technology Inc. Common Stock | Technology | 170.1 |
| 74 | `DE` | Deere & Company Common Stock | Industrials | 169.6 |
| 75 | `T` | AT&T Inc. | Telecommunications | 165.3 |
| 76 | `BA` | Boeing Company (The) Common Stock | Industrials | 165.2 |
| 77 | `DIS` | Walt Disney Company (The) Common Stock | Consumer Discretionary | 164.7 |
| 78 | `BLK` | BlackRock Inc. Common Stock | Finance | 163.9 |
| 79 | `GILD` | Gilead Sciences Inc. Common Stock | Health Care | 160.5 |
| 80 | `IBKR` | Interactive Brokers Group Inc. Class A Common Stock | Finance | 155.6 |
| 81 | `SCCO` | Southern Copper Corporation Common Stock | Basic Materials | 149.6 |
| 82 | `COP` | ConocoPhillips Common Stock | Energy | 146.5 |
| 83 | `PLD` | Prologis Inc. Common Stock | Real Estate | 140.5 |
| 84 | `PFE` | Pfizer Inc. Common Stock | Health Care | 139.9 |
| 85 | `BKNG` | Booking Holdings Inc. Common Stock | Consumer Discretionary | 137.5 |
| 86 | `CVS` | CVS Health Corporation Common Stock | Consumer Staples | 137.5 |
| 87 | `DHR` | Danaher Corporation Common Stock | Industrials | 134.6 |
| 88 | `LMT` | Lockheed Martin Corporation Common Stock | Industrials | 134.3 |
| 89 | `UBER` | Uber Technologies Inc. Common Stock | Consumer Discretionary | 134.2 |
| 90 | `CRM` | Salesforce Inc. Common Stock | Technology | 134.0 |
| 91 | `APP` | Applovin Corporation Class A Common Stock | Technology | 131.7 |
| 92 | `BMY` | Bristol-Myers Squibb Company Common Stock | Health Care | 126.8 |
| 93 | `SYK` | Stryker Corporation Common Stock | Health Care | 126.6 |
| 94 | `SPGI` | S&P Global Inc. Common Stock | Finance | 126.2 |
| 95 | `GLW` | Corning Incorporated Common Stock | Industrials | 126.2 |
| 96 | `COF` | Capital One Financial Corporation Common Stock | Finance | 125.0 |
| 97 | `PGR` | Progressive Corporation (The) Common Stock | Finance | 124.9 |
| 98 | `PH` | Parker-Hannifin Corporation Common Stock | Industrials | 124.5 |
| 99 | `MO` | Altria Group Inc. | Health Care | 121.9 |
| 100 | `VRTX` | Vertex Pharmaceuticals Incorporated Common Stock | Health Care | 121.2 |
| 101 | `ISRG` | Intuitive Surgical Inc. Common Stock | Health Care | 119.2 |
| 102 | `SBUX` | Starbucks Corporation Common Stock | Consumer Discretionary | 117.7 |
| 103 | `LOW` | Lowe's Companies Inc. Common Stock | Consumer Discretionary | 116.4 |
| 104 | `HWM` | Howmet Aerospace Inc. Common Stock | Industrials | 115.7 |
| 105 | `FTNT` | Fortinet Inc. Common Stock | Technology | 111.6 |
| 106 | `VRT` | Vertiv Holdings LLC Class A Common Stock | Technology | 111.5 |
| 107 | `SO` | Southern Company (The) Common Stock | Utilities | 109.7 |
| 108 | `BNY` | The Bank of New York Mellon Corporation Common Stock | Finance | 109.1 |
| 109 | `EQIX` | Equinix Inc. Common Stock REIT | Real Estate | 106.9 |
| 110 | `MDT` | Medtronic plc. Ordinary Shares | Health Care | 106.5 |
| 111 | `GD` | General Dynamics Corporation Common Stock | Industrials | 104.6 |
| 112 | `NOW` | ServiceNow Inc. Common Stock | Technology | 101.8 |
| 113 | `DUK` | Duke Energy Corporation (Holding Company) Common Stock | Utilities | 101.8 |
| 114 | `MCK` | McKesson Corporation Common Stock | Health Care | 101.1 |
| 115 | `PNC` | PNC Financial Services Group Inc. (The) Common Stock | Finance | 100.8 |
| 116 | `ADP` | Automatic Data Processing Inc. Common Stock | Industrials | 100.7 |
| 117 | `NEM` | Newmont Corporation | Basic Materials | 99.5 |
| 118 | `USB` | U.S. Bancorp Common Stock | Finance | 99.2 |
| 119 | `CEG` | Constellation Energy Corporation Common Stock  | Utilities | 99.1 |
| 120 | `MAR` | Marriott International Class A Common Stock | Consumer Discretionary | 98.7 |
| 121 | `CSX` | CSX Corporation Common Stock | Industrials | 98.6 |
| 122 | `UPS` | United Parcel Service Inc. Common Stock | Industrials | 97.6 |
| 123 | `BX` | Blackstone Inc. Common Stock | Finance | 96.6 |
| 124 | `WM` | Waste Management Inc. Common Stock | Utilities | 95.9 |
| 125 | `PWR` | Quanta Services Inc. Common Stock | Industrials | 93.9 |
| 126 | `SNOW` | Snowflake Inc. Common Stock | Technology | 92.9 |
| 127 | `NET` | Cloudflare Inc. Class A Common Stock | Technology | 92.7 |
| 128 | `CME` | CME Group Inc. Class A Common Stock | Finance | 92.5 |
| 129 | `CMI` | Cummins Inc. Common Stock | Industrials | 91.7 |
| 130 | `MNST` | Monster Beverage Corporation | Consumer Staples | 91.4 |
| 131 | `WMB` | Williams Companies Inc. (The) Common Stock | Utilities | 90.5 |
| 132 | `MPC` | Marathon Petroleum Corporation Common Stock | Energy | 90.3 |
| 133 | `FCX` | Freeport-McMoRan Inc. Common Stock | Basic Materials | 90.0 |
| 134 | `CDNS` | Cadence Design Systems Inc. Common Stock | Technology | 90.0 |
| 135 | `VLO` | Valero Energy Corporation Common Stock | Energy | 89.8 |
| 136 | `ADBE` | Adobe Inc. Common Stock | Technology | 89.5 |
| 137 | `KKR` | KKR & Co. Inc. Common Stock | Finance | 89.2 |
| 138 | `MMM` | 3M Company Common Stock | Health Care | 89.0 |
| 139 | `DDOG` | Datadog Inc. Class A Common Stock | Technology | 87.9 |
| 140 | `MRSH` | Marsh Common Stock | Finance | 86.3 |
| 141 | `HOOD` | Robinhood Markets Inc. Class A Common Stock | Finance | 85.5 |
| 142 | `ABNB` | Airbnb Inc. Class A Common Stock | Consumer Discretionary | 85.0 |
| 143 | `HCA` | HCA Healthcare Inc. Common Stock | Health Care | 84.8 |
| 144 | `EPD` | Enterprise Products Partners L.P. Common Stock | Utilities | 83.8 |
| 145 | `PSX` | Phillips 66 Common Stock | Energy | 82.9 |
| 146 | `EMR` | Emerson Electric Company Common Stock | Technology | 82.9 |
| 147 | `ICE` | Intercontinental Exchange Inc. Common Stock | Finance | 82.4 |
| 148 | `CTAS` | Cintas Corporation Common Stock | Industrials | 82.4 |
| 149 | `MCO` | Moody's Corporation Common Stock | Finance | 82.4 |
| 150 | `ELV` | Elevance Health Inc. Common Stock | Health Care | 81.9 |
| 151 | `ITW` | Illinois Tool Works Inc. Common Stock | Industrials | 81.4 |
| 152 | `INTU` | Intuit Inc. Common Stock | Technology | 81.1 |
| 153 | `TRV` | The Travelers Companies Inc. Common Stock | Finance | 80.8 |
| 154 | `CMCSA` | Comcast Corporation Class A Common Stock | Telecommunications | 79.7 |
| 155 | `NSC` | Norfolk Southern Corporation Common Stock | Industrials | 78.8 |
| 156 | `RCL` | Royal Caribbean Cruises Ltd. Common Stock | Consumer Discretionary | 78.7 |
| 157 | `SHW` | Sherwin-Williams Company (The) Common Stock | Consumer Discretionary | 78.3 |
| 158 | `EOG` | EOG Resources Inc. Common Stock | Energy | 78.0 |
| 159 | `MDLZ` | Mondelez International Inc. Class A Common Stock | Consumer Staples | 77.7 |
| 160 | `AMT` | American Tower Corporation (REIT) Common Stock | Real Estate | 77.7 |
| 161 | `AON` | Aon plc Class A Ordinary Shares (Ireland) | Finance | 77.3 |
| 162 | `HON` | Honeywell International Inc. Common Stock | Industrials | 77.0 |
| 163 | `NOC` | Northrop Grumman Corporation Common Stock | Industrials | 77.0 |
| 164 | `ROST` | Ross Stores Inc. Common Stock | Consumer Discretionary | 76.6 |
| 165 | `CI` | The Cigna Group Common Stock | Health Care | 76.6 |
| 166 | `ECL` | Ecolab Inc. Common Stock | Consumer Discretionary | 75.6 |
| 167 | `DASH` | DoorDash Inc. Class A Common Stock | Technology | 75.3 |
| 168 | `DLR` | Digital Realty Trust Inc. Common Stock | Real Estate | 75.0 |
| 169 | `FDX` | FedEx Corporation Common Stock | Consumer Discretionary | 74.5 |
| 170 | `SPG` | Simon Property Group Inc. Common Stock | Real Estate | 74.5 |
| 171 | `HLT` | Hilton Worldwide Holdings Inc. Common Stock  | Consumer Discretionary | 74.0 |
| 172 | `AEP` | American Electric Power Company Inc. Common Stock | Utilities | 73.7 |
| 173 | `KMI` | Kinder Morgan Inc. Common Stock | Utilities | 73.1 |
| 174 | `CL` | Colgate-Palmolive Company Common Stock | Consumer Discretionary | 72.6 |
| 175 | `GM` | General Motors Company Common Stock | Industrials | 72.5 |
| 176 | `ORLY` | O'Reilly Automotive Inc. Common Stock | Consumer Discretionary | 72.4 |
| 177 | `SNPS` | Synopsys Inc. Common Stock | Technology | 71.5 |
| 178 | `URI` | United Rentals Inc. Common Stock | Consumer Discretionary | 71.1 |
| 179 | `APO` | Apollo Global Management Inc. (New) Common Stock | Finance | 70.7 |
| 180 | `PCAR` | PACCAR Inc. Common Stock | Consumer Discretionary | 69.6 |
| 181 | `MSI` | Motorola Solutions Inc. Common Stock | Technology | 69.4 |
| 182 | `TDG` | Transdigm Group Incorporated Common Stock | Industrials | 69.2 |
| 183 | `REGN` | Regeneron Pharmaceuticals Inc. Common Stock | Health Care | 68.8 |
| 184 | `ALL` | Allstate Corporation (The) Common Stock | Finance | 66.9 |
| 185 | `RSG` | Republic Services Inc. Common Stock | Utilities | 66.7 |
| 186 | `APD` | Air Products and Chemicals Inc. Common Stock | Basic Materials | 66.3 |
| 187 | `CVNA` | Carvana Co. Class A Common Stock | Consumer Discretionary | 66.3 |
| 188 | `BSX` | Boston Scientific Corporation Common Stock | Health Care | 65.8 |
| 189 | `MPWR` | Monolithic Power Systems Inc. Common Stock | Technology | 65.5 |
| 190 | `GWW` | W.W. Grainger Inc. Common Stock | Industrials | 65.3 |
| 191 | `HONA` | Honeywell Aerospace Inc. Common Stock  | Industrials | 64.7 |
| 192 | `WBD` | Warner Bros. Discovery Inc. Series A Common Stock  | Consumer Discretionary | 64.6 |
| 193 | `TFC` | Truist Financial Corporation Common Stock | Finance | 64.5 |
| 194 | `AFL` | AFLAC Incorporated Common Stock | Finance | 63.9 |
| 195 | `AJG` | Arthur J. Gallagher & Co. Common Stock | Finance | 63.7 |
| 196 | `HPE` | Hewlett Packard Enterprise Company Common Stock | Technology | 63.2 |
| 197 | `D` | Dominion Energy Inc. Common Stock | Utilities | 62.5 |
| 198 | `TGT` | Target Corporation Common Stock | Consumer Discretionary | 62.1 |
| 199 | `NKE` | Nike Inc. Common Stock | Consumer Discretionary | 61.9 |
| 200 | `O` | Realty Income Corporation Common Stock | Real Estate | 61.2 |
