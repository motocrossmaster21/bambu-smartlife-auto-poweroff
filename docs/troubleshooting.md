# Fehlersuche

| Phase / Symptom | Prüfen |
|---|---|
| `STARTING` | HA muss fertig gestartet sein. |
| `DISARMED` | Freigabe steht aus; keine Abschaltung gewünscht. |
| `FAULT` | Fehlversuch oder abgebrochener Versuch gespeichert. Steckdose prüfen, Freigabe aus, `p1s_guard.acknowledge_fault` aufrufen. |
| `BRIDGE_OFFLINE` | Richtige HA-Bridge-Eintrag-ID? QR-Kopplung fertig bestätigt? Integration geladen und MQTT verbunden? |
| `MISSING_OR_STALE_DATA` | Alle sieben Drucker-Entities korrekt? Neue Berichte nach Start, maximal 60 Sekunden alt? Diagnose-Entities aktivieren. |
| `PRINTER_OFFLINE` | Bambu-Online-Sensor muss `on` sein. Cloud-Anmeldung/Internet prüfen. |
| `PLUG_NOT_ON` | Reale Steckdose muss als verfügbare Switch-Entity `on` melden. |
| `WAITING_FOR_FINISH` | Nur Rohwert `finish` gilt; kein übersetzter Text. |
| `INVALID_TEMPERATURE` | Alle Temperaturen müssen endliche, nicht negative Zahlen mit Einheit °C sein. |
| `INCOMPLETE_PROGRESS` | Erfolgreicher Druck muss zusätzlich 100 % melden. |
| `WAITING_FOR_COOLDOWN` | Düse zu warm oder Düsen-/Bett-Solltemperatur ungleich 0. |
| `STABILIZING` | Mindestens 30 Sekunden ohne Unterbrechung warten. |
| `SAFE`, aber keine Abschaltung | Automation aktiviert und Entity-ID korrekt? Nach Aktivierung Freigabe aus/ein, damit eine neue Wartezeit beginnt. |
| `POWER_OFF` | Versuch läuft; auf neue `off`-Meldung wird maximal 20 Sekunden gewartet. |

Telemetrie-Alter kann lokal unter Entwicklerwerkzeuge → Template betrachtet werden:

```jinja2
{% set s = states.sensor.REPLACE_WITH_ACTUAL_SENSOR %}
{{ s.last_reported if s is defined else 'Entity zuerst zuordnen' }}
```

Den Platzhalter durch den tatsächlichen Objektnamen ersetzen. `last_changed`
misst die letzte Wertänderung, nicht den letzten Bericht; eine stabile kalte
Düse darf lange denselben Wert haben. Der Guard verwendet `last_reported`.
Falls die Integration auch dieses Datum nicht regelmäßig aktualisiert, bleibt
die Automatik vorsichtshalber gesperrt. Nicht einfach die Altersgrenze abschalten.

HA nicht erreichbar: `HA_BIND_IP`, Port 8123, Container-Logs, NAS-Firewall und
Dateimounts prüfen. Ein nicht vorhandener Mount-Quellpfad kann von Docker als
Verzeichnis angelegt werden; das vollständige Projekt und Vorbereitungsskript
sind deshalb erforderlich. Mit `docker compose config --quiet` prüfen.

Smart-Life-Schalter fehlt: Bridge-QR in HA fertig bestätigt? Im Gateway-Panel
Untergerät hinzugefügt? Gerät `Bambu Auto Power Off` in HA vorhanden? App/Region
unterstützt? Keine zweite gerätelose Helper-Version mit demselben Namen anlegen.

ENV-Änderung wirkungslos: `docker compose up -d --force-recreate` verwenden.
Die HA-Logik nicht während eines aktiven Abschaltversuchs neu laden. Bei Updates
vorher Freigabe ausschalten und auf Abschluss laufender Versuche warten.

Ein Fehler bleibt erkennbar, selbst wenn die Steckdose zeitverzögert doch noch
ausgeht. Der Guard wiederholt den Befehl nicht automatisch. Ein neuer Druck
benötigt eine neue Freigabe; bei einem gespeicherten Fehler zunächst quittieren.
