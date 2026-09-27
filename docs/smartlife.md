# BambuOff als Smart-Life-Auslöser einrichten

Hier wird ein **eigenes TuyaLink-Gerät** eingerichtet, dessen Software auf deinem
PC/NAS läuft. Ein vorhandenes Smart-Life-Steckdosengerät wird nicht geändert.
Ein simuliertes Testgerät aus Tuyas Cloud-Debugger ist nicht dasselbe: wir
benötigen echte MQTT-Gerätezugangsdaten für den eigenen Software-Client.

## 1. TuyaLink-Produkt und Statusfeld

Im [Tuya Developer Portal](https://platform.tuya.com/) ein Konto einrichten bzw.
anmelden. TuyaLink-Zugriff und Geräteaktivierung müssen für dein Konto verfügbar
sein. Vor einem kostenpflichtigen Angebot dessen Bedingungen prüfen; das
Projekt führt keine Buchungen/Abos durch.

Ein neues Produkt über den Verbindungsweg **TuyaLink** mit dem standardmäßigen
TuyaLink-Datenprotokoll anlegen. Name: **BambuOff**. Ein normales Einzelgerät
verwenden, kein Gateway. Für den Anfang ein geeignetes Sensor-/Custom-Produkt
mit einer Standard-/Debug-Bedienoberfläche wählen, soweit das Portal es anbietet.

Unter **Function Definition** einen Property-Datenpunkt anlegen:

| Feld | Wert |
|---|---|
| Anzeigename | BambuOff / Sicher zum Ausschalten |
| Code | `bambu_off` |
| Typ | Boolean |
| Richtung / Zugriff | Vom Gerät gemeldet, nur lesbar |
| Werte | false = keine Freigabe, true = Druck sicher beendet |

Der Code muss exakt mit `TUYA_PROPERTY_CODE` übereinstimmen. Kein schreibbarer
Schalter ist erforderlich: ein manuelles EIN würde die Druckerprüfung umgehen.

## 2. Als Automationsbedingung freigeben

Unter **Product Configuration → Scenario Connection Settings → Settings**
den Datenpunkt `bambu_off` als **Condition** aktivieren. Er muss Benutzern als
Auslösebedingung zur Verfügung stehen. Eine **Action** für diesen Datenpunkt wird
nicht benötigt. Produktänderungen entsprechend dem Portal speichern/anwenden.

Dies ist der entscheidende Schritt: Nur weil das Gerät in der App erscheint,
ist sein Wert noch nicht automatisch als Szenenauslöser freigegeben.

## 3. Gerät erzeugen und Zugangsdaten übernehmen

Im Geräteentwicklungs-/Debug-Bereich ein TuyaLink-Gerät erzeugen/aktivieren.
Die Oberfläche und verfügbaren Testkontingente hängen vom Konto ab. Folgende
Werte lokal übernehmen:

- **Device ID** → `TUYA_DEVICE_ID`
- **Device Secret** → `TUYA_DEVICE_SECRET`
- **MQTT-Endpunkt des Datenzentrums** → `TUYA_MQTT_HOST`

Die Product ID gehört zur Produktverwaltung. Für die hier verwendete direkte
MQTT-Geräteanmeldung wird sie nicht zusätzlich benötigt. Weder ein Tuya-Cloud-
Access Secret noch der frühere Bridge-API-Key ersetzt das Device Secret.
Nicht den Local Key oder die Device ID deiner realen Steckdose verwenden.

## 4. QR-Code mit Smart Life koppeln

Unter **Device Binding Configuration** den Bindungsbereich passend freigeben.
Tuya dokumentiert dafür **All Developer Platform Accounts**, wenn das Gerät
mit einem Tuya-App-Konto gebunden werden soll. Den vom Portal für dieses Gerät
erzeugten QR-Code mit Smart Life scannen und die Gerätebindung abschließen.

Den Dienst mit gültigen Bambu-/Tuya-Zugängen und `MODE=live` starten. Die
MQTT-Verbindung kann schon für die Geräteaktivierung/Kopplung erforderlich sein.
Er meldet nach Verbindungsaufbau zunächst **false** und wartet auf die Bestätigung.
Eine endgültige EIN-Meldung setzt neue, sichere Bambu-Daten voraus.

## 5. Verfügbarkeit prüfen und Automation erstellen

In Smart Life **Szene/Smart → Automation → Bedingung hinzufügen → Gerätestatus
ändert sich → BambuOff** öffnen. Dort muss der Datenpunkt als Bedingung mit
`true/EIN` auswählbar sein. Falls nicht: Schritt 2, Produktveröffentlichung,
App-Version und Kontoregion prüfen. **Solange dieser Eintrag fehlt, ist die
Smart-Life-Abnahme nicht bestanden.** Home Assistant wird dadurch nicht benötigt,
aber dieses Kontoproblem kann nicht allein mit Python-Code behoben werden.

Zunächst eine harmlose Benachrichtigung/Testaktion verwenden. Nach Prüfung:

```text
WENN BambuOff auf EIN wechselt
DANN deine P1S-Steckdose ausschalten
```

Der Dienst setzt `BambuOff` nach rund **30 Sekunden automatisch auf AUS**.
Bleibt der Druckstatus abgeschlossen, entsteht kein weiterer Impuls. Erst ein
neuer Druck mit beobachtetem Wechsel von aktiv zu abgeschlossen kann wieder
auslösen – nach Abkühlung und 30 Sekunden stabilen Sicherheitsbedingungen.
Die Impulsdauer ist getrennt von dieser Sicherheitswartezeit konfigurierbar.
In der App kannst du den Anzeigenamen beispielsweise **Safe Auto Turn Off** nennen;
der technische Property-Code bleibt `bambu_off`.

Die Automation aktivierst/deaktivierst du in Smart Life. Kein zusätzlicher
Freigabeschalter und kein direkter Steckdosenzugriff durch unsere App nötig.
Keine zusätzliche Zeitverzögerung einbauen: Die 30 Sekunden prüft bereits der
Dienst vor dem Statuswechsel. Eine verzögerte Cloud-Aktion könnte erst bei
einem inzwischen neu gestarteten Druck ausgeführt werden.

Offline kann ein zuletzt gemeldetes EIN in der App stehenbleiben. Das ist
**keine aktuelle Sicherheitsbestätigung**. Keine zeitgesteuerte Prüfung eines
alten EIN-Zustands verwenden und keine Automation manuell gegen diesen Wert
ausführen. Nach Reconnect meldet der Dienst zuerst AUS und wiederholt das
Ereignis des zuletzt bereits signalisierten Drucks nicht.

Quellen: [Function Definition](https://developer.tuya.com/en/docs/iot/Function-Definition?id=Kb4qgfeeshz58),
[Scene Linkage](https://developer.tuya.com/en/docs/iot/Scenario-connection-settings?id=Kbr989qepvih9),
[Device Binding](https://developer.tuya.com/en/docs/iot/Device-Binding-Configuration?id=Kbnhoxwibpyyr).
