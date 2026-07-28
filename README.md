# EW Rothrist Smart Meter — Home Assistant Integration

[![hacs][hacs-badge]][hacs-url]
[![validate][validate-badge]][validate-url]

Holt die 15-Minuten-Lastgangdaten aus dem
[Kundenportal der EW Rothrist AG](https://www.ewrothrist.ch/de/services/lastgang.php)
und speist sie als Langzeit-Statistik in das **Energie-Dashboard** von
Home Assistant ein — inklusive Backfill der Historie.

> Inoffizielle Integration. Weder von der EW Rothrist AG entwickelt noch
> unterstützt.

## Wichtig vorweg: keine Echtzeitdaten

Das Portal aktualisiert die Lastgangdaten **mit mehreren Stunden Verzug**
(typisch 3–6 h). Die Zähler messen zwar alle 15 Minuten, aber die Werte
erscheinen erst verzögert im Portal. Diese Integration kann daher **keine
Live-Leistung** liefern.

Weil die Daten nachträglich eintreffen, wären normale Sensor-Zustände
falsch. Die Integration importiert die Werte deshalb als **externe
Langzeit-Statistik** (`ewrothrist:<zählernummer>_energy`) — rückwirkend und
stundengenau, damit sie im Energie-Dashboard korrekt einsortiert werden.

Wer Sekundenwerte braucht: Die Smart Meter haben eine lokale
**Kundenschnittstelle (CII)**, die standardmässig gesperrt ist und bei der
EW Rothrist freigeschaltet werden kann. Daran lässt sich ein lokaler Leser
(z. B. ESPHome) anschliessen. Diese Integration bleibt daneben für die
abrechnungsgenauen Werte nützlich.

## Installation

### Über HACS (empfohlen)

1. HACS → Integrationen → ⋮ → **Benutzerdefinierte Repositories**
2. Repository `https://github.com/gyshey/ha-ewrothrist`, Kategorie
   **Integration** → Hinzufügen
3. „EW Rothrist Smart Meter" installieren, Home Assistant neu starten

### Manuell

Den Ordner `custom_components/ewrothrist/` nach `/config/custom_components/`
kopieren und Home Assistant neu starten.

## Einrichtung

Einstellungen → Geräte & Dienste → **Integration hinzufügen** → „EW Rothrist
Smart Meter" → E-Mail-Adresse und Passwort des Kundenportals eingeben.

Die Zählernummer wird automatisch aus dem Portal gelesen. Beim ersten Lauf
importiert die Integration die konfigurierte Historie (Standard: 365 Tage).

### Optionen

| Option | Standard | Bedeutung |
|---|---|---|
| Abrufintervall | 60 min | Öfter bringt wenig — das Portal aktualisiert nur alle paar Stunden. |
| Historie beim Erst-Import | 365 Tage | Einmaliger Backfill. Das Portal liefert je nach Zähler ein bis mehrere Jahre. |

## Energie-Dashboard

Einstellungen → Dashboards → **Energie** → *Stromnetz → Netzbezug
hinzufügen* → Statistik `EW Rothrist Verbrauch CH…` auswählen. Sie erscheint
dort als **Statistik**, nicht als Sensor-Entität.

> ⚠️ **Doppelzählung vermeiden:** Home Assistant *summiert* alle
> eingetragenen Netzbezugs-Quellen. Wer den Netzbezug bereits lokal misst
> (Shelly 3EM, Shelly EM, P1-Leser …), darf den EWR-Zähler **nicht
> zusätzlich** eintragen — sonst wird derselbe Strom doppelt gezählt.
> Entweder die lokale Messung ersetzen, oder den EWR-Wert nur zum Vergleich
> in einer `statistics-graph`-Karte nutzen.

## Entitäten

Ergänzend zur Statistik (informativ — die Daten hinken einige Stunden):

| Entität | Bedeutung |
|---|---|
| Letzte Leistung | kW des letzten gelieferten 15-Minuten-Slots |
| Daten aktuell bis | Zeitstempel des letzten gelieferten Slots |
| Verbrauch heute (Teildaten) | Summe der bisher gelieferten Slots von heute |
| Verbrauch gestern | Tagessumme des Vortags |

## Wie es funktioniert

Das Portal hat keine API. Die Integration meldet sich wie ein Browser an
(`login.php`, Multipart-Formular) und liest die serverseitig gerenderte
Tabelle von `lastgang.php` (`zeitraum=datum`, bis 31 Tage pro Anfrage in
15-Minuten-Auflösung).

Eigenheiten, die dabei berücksichtigt werden:

- Werte sind **mittlere Leistung in kW** je 15-Minuten-Slot
  (kWh = kW × 0,25).
- Noch nicht gelieferte Slots stehen als `0.00` in der Tabelle und sind
  nicht von echten Nullen unterscheidbar. Die Integration schneidet die
  Null-Serie am Ende ab und holt sie beim nächsten Abruf nach.
- Jeder Abruf überlappt die letzten 48 Stunden, damit nachträgliche
  Korrekturen des Netzbetreibers übernommen werden.
- Zeitumstellungen werden korrekt behandelt (die doppelte Stunde im Herbst
  wird als `fold=1` aufgelöst).
- Läuft die Portal-Session ab, meldet sich die Integration automatisch neu
  an; bei falschem Passwort startet Home Assistant den Reauth-Dialog.

## Mitwirken

Fehlerberichte und Pull Requests sind willkommen. Da das Portal reines HTML
liefert, kann eine Layout-Änderung seitens der EW Rothrist das Parsing
brechen — Issues mit einem (anonymisierten) HTML-Ausschnitt helfen dann sehr.

## Lizenz

MIT — siehe [LICENSE](LICENSE).

[hacs-badge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg
[hacs-url]: https://github.com/hacs/integration
[validate-badge]: https://github.com/gyshey/ha-ewrothrist/actions/workflows/validate.yml/badge.svg
[validate-url]: https://github.com/gyshey/ha-ewrothrist/actions/workflows/validate.yml
