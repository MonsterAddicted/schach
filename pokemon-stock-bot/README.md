# Pokémon 30th Celebration – Stock-Bot 🟢📧

Prüft **jede Minute** mehrere Online-Shops auf **englische** Pokémon-TCG-„30th Celebration“-Produkte
(ETB, Booster Bundle, Mini Tins, Ultra-Premium Collection, …) und schickt dir **eine E-Mail**,
sobald etwas auf Lager ist. Du bekommst nur eine Mail, wenn ein Produkt *neu* verfügbar wird,
also nicht jede Minute dieselbe.

## 1. Gmail-App-Passwort erstellen (einmalig)

1. Bei Google die **Bestätigung in zwei Schritten** aktivieren (falls noch nicht an).
2. <https://myaccount.google.com/apppasswords> öffnen → Name z.B. „Pokemon Bot“ → **Erstellen**.
3. Das 16-stellige Passwort kopieren. Das ist dein `SMTP_PASSWORD`.

## 2a. Kostenlos 24/7 auf GitHub laufen lassen (empfohlen)

1. Diese Änderungen in den `main`-Branch mergen (GitHub führt Zeitpläne nur auf `main` aus).
2. Im Repo: **Settings → Secrets and variables → Actions → New repository secret**:
   | Name | Wert |
   |---|---|
   | `SMTP_USER` | deine Gmail-Adresse |
   | `SMTP_PASSWORD` | das App-Passwort aus Schritt 1 |
   | `MAIL_TO` | (optional) Empfänger, Standard = `SMTP_USER` |
3. **Actions → Pokémon Stock-Bot → Run workflow** klicken, um den ersten Lauf sofort zu starten.
   Danach startet GitHub ihn stündlich von selbst. Es läuft immer nur ein Lauf, der ~6 Stunden
   lang jede Minute prüft.

> Hinweis: GitHub pausiert Zeitpläne in Repos, in denen 60 Tage lang nichts passiert.
> Dann einfach unter *Actions* wieder aktivieren.

## 2b. Oder auf deinem eigenen PC / Raspberry Pi

```bash
cd pokemon-stock-bot
export SMTP_USER="deine.adresse@gmail.com"
export SMTP_PASSWORD="abcd efgh ijkl mnop"
python3 bot.py --test-mail   # prüft, ob die Mail ankommt
python3 bot.py               # läuft endlos, prüft jede Minute
```

Windows (PowerShell): `$env:SMTP_USER="..."` und `$env:SMTP_PASSWORD="..."`, dann `python bot.py`.

Ein Durchlauf zum Testen, ohne Endlosschleife: `python3 bot.py --once`

## 3. Welche Shops werden geprüft?

**Shops mit Geschäft in Graz:**

| Shop | Geschäft in Graz |
|---|---|
| Kartenchaos | Herrgottwiesgasse 117 (TCG-Fachgeschäft) |
| Spielewerk | Annenstraße 35 (Spiele & Trading Cards) |
| Smyths Toys | Shopping Center West, Weblinger Gürtel 25 |
| Müller | mehrere Filialen |
| MediaMarkt | mehrere Filialen |
| Libro | mehrere Filialen |
| Thalia | mehrere Filialen |
| Kastner & Öhler | Sackstraße (Spielwarenabteilung) |

Dazu kommen die Online-Shops TCGviert, Gate to the Games, Magic Madhouse und Total Cards.
Trading Cards United (Münzgrabenstraße 10) hat keinen Online-Shop und fehlt deshalb.

Bei allen Shops in Graz muss im Titel „Englisch“, „English“ oder „EN“ stehen, weil dort meist
die deutsche Version („30 Jahre“) verkauft wird.

## 4. Shops hinzufügen / ändern → `config.json`

| Typ | Wofür |
|---|---|
| `auto` | Probiert selbst aus, ob der Shop auf Shopify oder WooCommerce läuft, sonst nutzt er `search_url`. **Für neue Shops am einfachsten.** |
| `shopify` | Shopify-Shops. Liest den Lagerstatus direkt aus, sehr zuverlässig. |
| `woocommerce` | WordPress-/WooCommerce-Shops. Ebenfalls zuverlässig. |
| `search` | Beliebiger Shop: Öffnet die Suchseite, folgt den passenden Produktlinks und liest dort den Lagerstatus. `{q}` in `search_url` wird durch den Suchbegriff ersetzt. |
| `page` | Eine einzelne Produktseite. |

```json
{ "name": "Mein Shop", "type": "auto", "url": "https://mein-shop.at",
  "search_url": "https://mein-shop.at/suche?q={q}",
  "queries": ["30th Celebration"], "require_english_marker": true }
```

`require_english_marker: true` heißt: Im Produkttitel muss „Englisch“, „English“ oder „EN“
stehen. Titel mit „Deutsch“, „Japanisch“, „JP“, „Plüsch“ usw. werden immer aussortiert
(`filter` in der Config).

## Gut zu wissen

* Der erste Start meldet alles, was **gerade schon** auf Lager ist. Danach kommen nur noch
  neue Treffer.
* **Erster Test:** `python3 bot.py --once` zeigt für jeden Shop, ob er funktioniert.
  Große Ketten (MediaMarkt, Müller, Smyths, Thalia) bauen ihre Suchseiten teils erst im
  Browser zusammen oder blocken Bots. Dann findet der Bot dort nichts. In dem Fall eine
  konkrete Produktseite als `page` eintragen, sobald das Produkt online gelistet ist.
* Steht im Log `!! Shopname: HTTP 403` oder `Verfügbarkeit nicht erkennbar`, blockt der Shop Bots
  (z.B. Pokémon Center, Amazon). Dann den Shop entfernen oder lokal statt auf GitHub laufen lassen.
* Bitte das Intervall nicht unter 60 Sekunden setzen, sonst sperren Shops dich eher.
