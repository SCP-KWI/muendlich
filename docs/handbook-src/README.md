# Handbuch-Generator

Baut das Handbuch für Lehrpersonen als eine einzige, selbsttragende Datei
(Fonts, Screenshots und Pfeil-Overlays sind eingebettet; die einzigen externen
URLs sind die vier Diktier-Anleitungen von Apple, Google und Microsoft).

**Wohin gebaut wird:** `../../frontend/public/handbuch.html`. Das ist die
einzige echte Datei. Sie liegt dort, weil der Docker-Build des Frontends nur
`frontend/` als Kontext sieht — von dort aus liefert Vite sie im Dev-Server
aus und kopiert sie beim Build nach `dist/`, sodass die App sie in Dev und
Produktion unter demselben Pfad hat. `../handbuch.html` ist ein Symlink
darauf, damit der dokumentierte Pfad weiter aufgeht.

In der App hängt sie am **?-Button** und ist unter `/handbuch` erreichbar —
ohne Login. Die Zuordnung `/handbuch` → `handbuch.html` macht in Produktion
`frontend/nginx.conf`, im Dev-Server ein kleines Plugin in
`frontend/vite.config.js`. Der Service Worker schliesst die Datei bewusst vom
Precache aus (`globIgnores`), sonst lägen ~1 MB in jeder Installation.

## Nur Text ändern

Der ganze Inhalt steht in `handbuch.src.html`. Danach:

```bash
node build.mjs
```

Das genügt, solange sich die Screenshots nicht ändern: `shots/rects.json` und
`shots/web/*.webp` liegen mit im Repo, die App muss dafür nicht laufen.

## Screenshots neu aufnehmen

Nötig, sobald sich die Oberfläche ändert. Voraussetzungen: `backend/.venv`,
Node-Abhängigkeiten hier (`npm install`), ImageMagick und Chromium
(`CHROME_PATH` überschreibt `/usr/bin/chromium`).

```bash
cd ../../frontend && npm run dev     # Vite auf :5173, in einem eigenen Terminal
```

```bash
bash refresh.sh && node build.mjs
```

`refresh.sh` setzt die Demo-Datenbank zurück, startet das Demo-Backend auf
:8000, fährt mit Puppeteer durch die App und konvertiert die PNGs nach WebP.

## Was die Dateien tun

| Datei | Zweck |
|---|---|
| `handbuch.src.html` | Inhalt und Chalk-Styling. `{{FIG:name}}` und `{{FONTS}}` sind die Platzhalter. |
| `build.mjs` | Setzt die Datei zusammen: Fonts einbetten, Bilder als Data-URI, Pfeile als SVG. Die Zuschnitte der Abbildungen stehen oben in `FIGURES`. |
| `shots.mjs` | Fährt die App ab und schreibt `shots/*.png` **plus** `shots/rects.json` — die Bounding-Boxen der markierten Elemente, aus denen `build.mjs` die Pfeile berechnet. Welche Elemente nummeriert werden, steht in den `shot(...)`-Aufrufen. |
| `demo_seed.py` | Demo-Lehrperson, zwei Klassen, Namensliste und die Beispiel-Beobachtungen. |
| `demo_server.py` | Startet das echte Backend, ersetzt aber Stufe 2 (die Cloud-KI) durch einen skriptierten Structurer. Der mitgelieferte Stub ist eine Keyword-Heuristik und zerlegt zu unrealistisch für Screenshots; Anonymisierung, Resolver, Auth und DB sind der echte Code-Pfad. |
| `refresh.sh` | Datenbank zurücksetzen → Backend starten → `shots.mjs` → WebP. |
| `check.mjs` | Rendert das fertige Handbuch in Light und Dark und legt Abbildungen und Seitenstreifen unter `check/` ab — zum Drüberschauen. |
| `mobile.mjs` | Dasselbe im Handy-Viewport, prüft nebenbei auf horizontales Überlaufen. |

## Warum ein Pfeil sitzt, wo er sitzt

Die Pfeile werden nicht von Hand platziert. `shots.mjs` liest beim
Screenshotten die Bounding-Box jedes markierten Elements aus dem DOM,
`build.mjs` legt daraus ein SVG über das Bild. Ein Layout-Wechsel in der App
verschiebt die Pfeile also automatisch mit — solange die Selektoren in
`shots.mjs` noch treffen. Fehlt einer, meldet der Lauf `!! missing`.

## Nicht im Repo

`demo.db`, `backend.log`, `node_modules/`, `check/` und die PNG-Zwischenstufe
unter `shots/` — siehe `.gitignore`.
