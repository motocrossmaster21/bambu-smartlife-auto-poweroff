# Tuya-Steckdose und Smart-Life-Freigabe

## 1. Reale Steckdose nach Home Assistant importieren

Die Steckdose bleibt mit dem bisherigen Smart-Life-Konto gekoppelt. In HA die
offizielle Integration **Tuya** hinzufügen. Den User Code in Smart Life unter
**Ich → Einstellungen → Konto und Sicherheit → User Code** ablesen, im
HA-Dialog verwenden und dessen QR-Code mit Smart Life scannen.

Die gewünschte Steckdose identifizieren, nicht anhand eines Beispielnamens
auswählen. In Entwicklerwerkzeuge ihren `switch` und die Zustände `on`/`off`
prüfen. Die tatsächliche Entity-ID wird `P1S_PLUG_ENTITY` in `.env`.
Ein manueller Schaltversuch ist nur bei sicherem, kaltem und nicht druckendem
Drucker sinnvoll. Alternativ zuerst eine separate Teststeckdose verwenden.

Für diesen aktuellen HA-Anmeldeweg sind keine selbst zusammengestellten
Tuya Access ID/Access Secret/Local-Key-ENV erforderlich. Wenn der Steckdosentyp
keine steuerbare HA-Switch-Entity liefert, kann die Abnahme noch nicht erfolgen.
Nicht ohne neue Prüfung auf eine indirekte Szene ausweichen.

Quelle: [Offizielle HA-Tuya-Anleitung](https://www.home-assistant.io/integrations/tuya/).

## 2. Bridge für die umgekehrte Richtung einrichten

`tuya_cloud_ha_bridge v1.1.2` ist über das Installationsskript vorhanden.
Alternativ als benutzerdefiniertes HACS-Repository
`https://github.com/tuya/tuya_cloud_ha_bridge` vom Typ **Integration** installieren.
HA nach einer manuellen Installation neu starten.

In HA **Tuya Cloud HA Bridge** hinzufügen. Der Einrichtungsdialog verweist für
den erforderlichen **API Key** auf [tuya.ai](https://tuya.ai/). Den Schlüssel dort
für das eigene Konto beziehen und direkt im lokalen HA-Dialog eingeben. Keine
separaten Gateway-Secrets erfinden: Gateway-ID und TuyaLink-Zugang werden durch
den Einrichtungsablauf erzeugt bzw. gespeichert. Die Region wird anhand des Keys
aufgelöst; bei nicht unterstütztem Konto/Region stoppt die Einrichtung.

Den erzeugten Gateway-QR-Code mit **Smart Life** scannen. Der Upstream empfiehlt
eine kompatible Tuya-App ab Version 7.6.0; die erfolgreiche Kopplung mit deiner
Smart-Life-Version und Kontoregion muss vor Ort geprüft werden. Nach dem Scan
unbedingt **zur HA-Seite zurückkehren und Submit/Absenden bestätigen**.
Andernfalls ist die Gateway-Einrichtung nicht fertig gespeichert.

Im Gateway-Gerätepanel der App ein Untergerät hinzufügen und das HA-Gerät
**Bambu Auto Power Off** wählen. Es enthält ausschließlich den normalen
Switch-Proxy für den internen Freigabe-Helper. Unterstützte Upstream-Domains
umfassen `switch`, `light`, `fan`, `climate`, `cover`, `humidifier`, `vacuum` und
`water_heater`; `input_boolean` wird deshalb nicht direkt exportiert.

Das Smartphone soll anschließend zwei getrennte Geräte zeigen:

| Smart Life | Wirkung |
|---|---|
| P1S Power Plug (bisheriger Name möglich) | Direkte Stromversorgung |
| Bambu Auto Power Off | Einmalige Freigabe der HA-Sicherheitslogik |

Die reale Steckdose nicht noch einmal über die Bridge exportieren. Falls die
offizielle Tuya-Integration den neu exportierten virtuellen Switch wieder
importiert, dessen Duplikat in HA deaktivieren. Der Guard benutzt ausschließlich
den lokalen Helper, nicht diese zurückimportierte Entity.

Die HA-Konfigurationseintrag-ID der Bridge in `TUYA_BRIDGE_ENTRY_ID` setzen,
wie in der README beschrieben. Ein API Key, die Cloud-Gateway-ID und eine
HA-Config-Entry-ID sind unterschiedliche Werte.

## 3. Beide Richtungen prüfen

Zunächst die Abschaltautomation in HA deaktivieren oder eine ungefährliche
Teststeckdose verwenden. In Smart Life den Freigabeschalter einschalten:
`switch.bambu_auto_power_off` und `input_boolean.bambu_auto_power_off` müssen
in HA `on` anzeigen. Danach den Helper in HA ausschalten: Smart Life muss
ebenfalls `off` anzeigen. Die reale Steckdose muss dabei unverändert bleiben.

Dann Bridge neu laden: Während der Trennung darf der Guard nicht `SAFE` werden.
Nach erfolgreicher Verbindung und neuen Druckerberichten muss die vollständige
Stabilisierung erneut beginnen. Erst danach die Abnahmetests mit dem echten
Drucker durchführen. Die pausierte Abschaltautomation wieder aktivieren, während
die Freigabe aus ist.

## Credentials und Grenzen

Anmeldetokens, API Key und generierte Gateway-Credentials liegen unter
`/config/.storage` im vom Git ausgeschlossenen Laufzeitordner. Weder diese Dateien
noch Diagnose-Exports, Screenshots von QR-Codes oder `.env` veröffentlichen.
Das Repository enthält nur Quellcode, Platzhalter und nicht geheime Einstellungen.

Die Bridge nutzt TuyaLink-MQTT intern. Der Guard prüft den aktuellen
`runtime_data.connected`-Wert dieses ausgewählten HA-Konfigurationseintrags.
Fehlt das Feld nach einem Update oder ist die Integration nicht geladen, bleibt
die Abschaltung gesperrt. Das ist kein Test einer unabhängigen Internetverbindung
und erkennt einen Cloud-Ausfall erst nach der Erkennung durch den MQTT-Client.

Quelle: [Tuya Bridge v1.1.2](https://github.com/tuya/tuya_cloud_ha_bridge/tree/v1.1.2).
