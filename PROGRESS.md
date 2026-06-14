# CryptoBot — Progress & Decision Log

## Aktivna grana: `claude-grid-logic`
Baza: `claude-server-stable` (stabilna, ne diramo)

---

## Što je napravljeno

### Grid logika (`main.py`)
- **Nova logika buy ordera nakon sell filla**: novi buy se postavlja `sell_pct%` ispod filla (ne `buy_pct%`)
- **Razlog**: eliminira echo/duplikat sell ordere koji su trošili neplaniran kapital
- **Efekt**: novi sell se vraća na ~istu razinu filla (razlika = sell%² ≈ zanemarivo)
- **Tradeoff**: gap između sellova = sell%, ne buy% — prihvatljivo za male postotke (1-5%)
- Radi ispravno za 1-1, 1-2, 1-3 i sve kombinacije

### Optimizer (`core/backtester.py`)
- Filtar: prikazuje samo kombinacije gdje `open_positions <= floor(total_capital / amount) * 1.10`
- Razlog: s normalize_amount (fer usporedba), mali buy% skalira amount prema dolje i otvara previše pozicija koje korisnik nije planirao

### Backtest UI (`templates/backtest.html`, `static/js/modules/settings.js`)
- Dropdown "Optimiziraj po" — bira se primarna metrika (realizirani profit ili ukupni P&L)
- Fix: `<pre>` element imao bijeli background od Bootstrapa — dodan `background:transparent; color:inherit`

### CSS fix (`static/css/styles.css`)
- `text-muted` globalno popravljen za tamnu/svijetlu temu — Bootstrap override gutao boju

### UI — show/hide lozinke
- Dodano eye dugme (`bi-eye`) na: login stranicu, Gmail App Password, Current/New Password, CMC API ključ
- API ključevi burze već su imali show/hide — preskočeno

---

## Ključne odluke o strategiji (razgovor s korisnikom)

### Zašto buy% = sell%?
- Echo pozicije (nastaju kad sell% > buy%) troše kapital na "međurazine" umjesto da idu dublje u grid
- Svaka kuna kapitala s buy=sell% ide u dubinu pokrivenosti pada — prioritet je pokriti veći % pada
- Naviše se trguje na dnu — bez kapitala na dnu = propušteni trejdovi

### Strategija pokrivenosti
- BTC: aktivna zona 65% pada od ATH, rezerva do 75%
- ETH: aktivna zona 70% pada od ATH, rezerva do 80%
- Kapital za 65% pada ≈ 11,000 USDC (kalkulator na dashboardu to računa)

### Fee logika
- Sell% mora biti ≥ buy% uvijek
- Fee ≈ 0.2% po ciklusu (buy + sell) — ako je sell% = 1%, fee uzima ~20% profita
- Manji sell% nije neisplativ ali je manje efikasan

### Duplikat sell orderi
- Nastaju kad sell% ≈ 2× buy% (npr. 1-2): echo sell pada na gotovo istu cijenu kao postojeći
- Rješenje: nova logika buy = sell_pct% ispod filla

---

## Trenutno testiranje (server)
- BTC/USDC: 1% buy, 3% sell — u tijeku
- ETH/USDC: 1% buy, 3% sell — u tijeku  
- BNB/USDC: 0.2% buy, 0.6% sell — za brže cikliranje i validaciju logike

---

## Sljedeće za uraditi
- [ ] Pratiti rezultate nove grid logike na serveru
- [ ] Ako grid logika prođe test → mergati u `claude-server-stable`
- [ ] Video editor projekt (novi repo `video-editor`) — player tracking, statistike
