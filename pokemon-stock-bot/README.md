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

## 3. Shops hinzufügen / ändern → `config.json`

Es gibt zwei Shop-Typen:

* **`shopify`**: Für Shops, die auf Shopify laufen (sehr viele TCG-Shops). Der Bot durchsucht
  den ganzen Shop nach `queries` und liest den Lagerstatus direkt aus. Ob ein Shop Shopify nutzt,
  erkennst du so: `https://SHOP/search/suggest.json?q=pokemon` im Browser öffnen. Kommt JSON
  zurück, passt es.
* **`page`**: Eine einzelne Produktseite, z.B. bei Amazon, Müller oder Smyths. Der Bot liest den
  Lagerstatus aus den Produktdaten der Seite oder sucht nach Wörtern wie „ausverkauft“ und
  „In den Warenkorb“.

```json
{ "name": "Mein Shop", "type": "shopify", "url": "https://mein-shop.de",
  "queries": ["30th Celebration"], "require_english_marker": true }

{ "name": "Smyths ETB", "type": "page",
  "url": "https://www.smyths-toys.com/de/de-de/...", "title": "30th ETB EN" }
```

`require_english_marker: true` heißt: Der Produkttitel muss „Englisch“, „English“ oder „EN“
enthalten. Das ist sinnvoll bei deutschen Shops, die mehrere Sprachen verkaufen. Titel mit
„Deutsch“, „Japanisch“, „JP“ usw. werden immer aussortiert (`filter` in der Config).

## Gut zu wissen

* Der erste Start meldet alles, was **gerade schon** auf Lager ist. Danach kommen nur noch
  neue Treffer.
* Steht im Log `!! Shopname: HTTP 403` oder `Verfügbarkeit nicht erkennbar`, blockt der Shop Bots
  (z.B. Pokémon Center, Amazon). Dann den Shop entfernen oder lokal statt auf GitHub laufen lassen.
* Bitte das Intervall nicht unter 60 Sekunden setzen, sonst sperren Shops dich eher.
