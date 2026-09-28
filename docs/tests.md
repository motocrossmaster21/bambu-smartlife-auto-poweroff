# Teststand BambuOff

Die aktive Implementierung ist der eigenständige Dienst im Projektstamm.
Das Home-Assistant-Archiv wird nicht gestartet oder in das Image eingebaut.

## Automatisierte Prüfungen

Sicherheitsergänzung am 28.09.2026: 56 Tests bestanden und Compose-Konfiguration
validiert. Die zusätzlichen Tests verwenden echte lokale TCP-Verbindungen:
inaktive Clients, langsam nachgelieferte Header, Ablehnung überzähliger
Verbindungen und erfolgreiche Statusabfragen nach Freigabe der Kapazität.
Auch ein Fehler beim Thread-Start sowie bereinigte Login-Fehlerausgaben werden
geprüft. Die neuen Container-Ressourcenlimits sind konfiguriert; ihre Durchsetzung
auf dem QNAP und ein erneuter Container-Smoke-Test sind noch zu prüfen.

Lokal am 27.09.2026: 49 Tests bestanden, Compose validiert und Docker-Image
erfolgreich gebaut. Der Demo-Container startet ohne Zugangsdaten und meldet
einen gesunden Zustand. Der HTTP-Smoke-Test ist ebenfalls bestanden: 30 Sekunden
Stabilisierung, etwa 30 Sekunden EIN und automatisches AUS bei weiterem FINISH.
Eine Messung im Demo-Betrieb zeigte rund 35 MiB RAM;
das ist keine garantierte Obergrenze für den Live-Betrieb.

Die Tests verwenden den tatsächlichen Zustandsautomaten und simulierte
MQTT-Schnittstellen. Abgedeckt sind insbesondere:

- Erfolgreicher Druck, 100 %, sichere Ist-/Solltemperaturen, 30 Sekunden stabil.
- RUNNING/PREPARE/PAUSE/FAILED/IDLE, fehlende und veraltete Teilwerte.
- Einmalige FINISH-Teilmeldung nach altem RUNNING, zehn Minuten Abkühlung
  mit ausschließlich Düsentemperaturmeldungen, danach genau ein 30-Sekunden-Impuls.
- Alte Düsenmessung trotz anderer Updates, Sendepause bei verbundenem MQTT,
  Jobwechsel und neue Heizungs-/Status-Teilmeldungen während der Wartezeit.
- Ungültige Zahlen, negative Temperaturen, NaN, mehrere/ungültige Extruder.
- Verbindungsverlust, Neustart, verzögerte Verarbeitung und Retain-Nachrichten.
- Kein Auslösen bei bereits anstehendem FINISH nach Programmstart.
- Beobachtete aktive Druckphase → FINISH-Flanke; Job-ID-Wechsel allein genügt nicht.
- Automatisches AUS nach 30 Sekunden EIN bei unverändertem FINISH.
- Kein Wiederholen bei weiterem FINISH; erneuter Impuls beim nächsten Druck.
- Frühzeitiges AUS bei unsicheren Bedingungen.
- Persistierte Wiederholungssperre und Fehler beim Schreiben der Zustandsdatei.
- Initiales Tuya-AUS muss bestätigt sein; falsche/fehlgeschlagene Bestätigungen.
- Keine Bambu-Publishes, keine Steckdosensteuerung und kein Replay alter Publishes.
- ENV-Validierung und Ausschluss von Secrets aus dem Docker-Build-Kontext.
- HTTP-Verbindungsreset beim Start wird erneut versucht; dauerhafte Fehler
  führen weiterhin zum Timeout. Eine unterbrochene Impulsbeobachtung zählt
  nicht als vollständig beobachteter Impuls; Live-Modus wird sofort abgewiesen.

```powershell
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -v
docker compose --env-file .env.example config --quiet
docker compose -f compose.yaml -f compose.build.yaml --env-file .env.example up -d --build
python scripts/smoke_demo.py
```

Der Smoke-Test beobachtet über HTTP einen vollständigen Demo-Impuls. Er prüft
mindestens 30 Sekunden Stabilisierung, ungefähr 30 Sekunden EIN und den Reset
bei **weiterhin FINISH**, noch bevor der nächste simulierte Druck beginnt.
Es werden keine Cloud-Verbindungen hergestellt.

GitHub Actions wartet vor dem Smoke-Test mit `--wait --wait-timeout 90` auf
den gesunden Container. Der Test versucht vorübergehend fehlgeschlagene
HTTP-Verbindungen innerhalb seines 180-Sekunden-Limits erneut. Bei Fehlern
gibt der Workflow Containerstatus und Logs aus. Der Runner ist auf Ubuntu 24.04
festgelegt; Checkout und Python-Setup verwenden Actions mit Node.js 24.

## Noch erforderliche Live-Abnahme

Mit deinem Tuya-Konto muss geprüft werden, dass das angelegte TuyaLink-Gerät
gekoppelt werden kann und `bambu_off` in Smart Life als Szenenbedingung erscheint.
Mit deinem Bambu-Konto sind Login, regelmäßige P1S-Pflichtfelder und die reale
Abschlussflanke zu prüfen. Diese Konten-/Geräteprüfungen werden nicht durch
Demo- oder Unit-Tests ersetzt.

Zunächst nur eine harmlose Smart-Life-Testaktion verwenden. Beobachten:

1. Während des Drucks kein EIN-Signal.
2. Nach Abschluss und Abkühlung volle Sicherheitswartezeit.
3. EIN-Signal als Smart-Life-Auslöser verfügbar.
4. Nach rund 30 Sekunden AUS, sofern die Cloud erreichbar bleibt.
5. Bei dauerhaft abgeschlossenem Druck keine Wiederholung.
6. Erst beim nächsten abgeschlossenen Druck erneut ein Impuls.

Bei Cloud-Ausfall kann die App das AUS nicht zustellen; ein alter Cloud-Wert
ist keine aktuelle Freigabe. Keine verzögerten Abschaltaktionen anlegen.
