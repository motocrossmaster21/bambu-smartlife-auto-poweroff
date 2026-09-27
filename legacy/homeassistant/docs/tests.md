# Tests und Abnahme

## Lokal durchgeführt am 20.09.2026

- 33 automatisierte Tests bestanden: echte Policy, Stabilitätsfenster, YAML-
  Struktur und der echte Guard-Ablauf mit simulierten HA-Diensten/Zuständen.
- `docker compose --env-file .env.example config --quiet` erfolgreich.
- Der Installationshelfer hat beide Integrationen erfolgreich in den ignorierten
  Laufzeitordner installiert und beide SHA-256-Prüfsummen bestätigt.
- Python-Dateien erfolgreich kompiliert, `git diff --check` ohne Fehler;
  `.env`, `.env.production`, `.storage`, Laufzeitordner, Secrets, DBs und Logs
  per `git check-ignore` als ausgeschlossen bestätigt. Kein Commit/Push erfolgt.

**Nicht lokal ausgeführt:** HA-Konfigurationsprüfung im Container und echter
HA-Start. Der Docker-Client ist vorhanden, aber kein Docker-Daemon erreichbar.
Die Python-Tests ersetzen nicht Home Assistants eigene Schema-/Laufzeitprüfung.
GitHub Actions ist vorbereitet, wurde in dieser Arbeit aber nicht gestartet.
QNAP, Bambu-Cloud-Anmeldung, Smart-Life-Kopplung und reale Steckdosenreaktion
können ohne Geräte/Konten nicht geprüft werden.

## Testmatrix

Bei allen positiven Beispielen zusätzlich: Drucker online, Bridge verbunden,
Steckdose `on`, gültige frische Daten, Fortschritt 100 %, Düsen- und Bettziel 0,
keine Fehlersperre. `finish` ist der tatsächlich erwartete HA-Rohwert.

| Nr. | Situation | Erwartung |
|---|---|---|
| 1 | Freigabe aus, finish, Düse 30 °C | Steckdose bleibt an |
| 2 | Freigabe an, running, Düse 30 °C | Bleibt an |
| 3 | Freigabe an, finish, Düse 80 °C | Bleibt an |
| 4 | Freigabe an, finish, 49 °C, Ziele 0, 30 s stabil | Aus; Freigabe erst nach `off`-Bestätigung aus |
| 5 | Freigabe an, failed, 30 °C | Bleibt an |
| 6 | Status unavailable | Bleibt an |
| 7 | Düse unavailable | Bleibt an |
| 8 | Kurz 49 °C, dann 52 °C | Wartezeit verworfen, bleibt an |
| 9 | finish, 45 °C, Düsen-Ziel 60 °C | Bleibt an |
| 10 | HA-Neustart während Abkühlen | Neue Berichte und neues vollständiges Zeitfenster nötig |
| 11 | prepare, pause, idle, unknown, offline oder anderer Erfolgsname | Bleibt an |
| 12 | Bettziel 60 °C, fehlende Werte, NaN, unendlich, negative Temperatur, °F | Bleibt an |
| 13 | Meldungen veraltet, nur vor Neustart vorhanden oder als restored markiert | Bleibt an |
| 14 | Tuya Bridge getrennt, HA-Eintrag fehlt oder Adapter inkompatibel | Bleibt an |
| 15 | Steckdose unavailable oder bereits off | Kein neuer Schaltversuch |
| 16 | Dienstaufruf scheitert oder kein neues off innerhalb 20 s | Freigabe bleibt; Fehlersperre und lokale Meldung |
| 17 | Freigabe erst bei bereits kaltem finish aktiviert | Trotzdem neue 30 s |
| 18 | Neuer Druck unmittelbar vor Befehl | Letzte Prüfung verhindert Befehl |
| 19 | Paralleler/direkter Dienstaufruf | Keine Umgehung von Sperre und Zeitfenster |
| 20 | HA-Absturz während Versuch | Gespeicherte Fehlersperre verhindert Wiederholung |
| 21 | Ereignisschleife länger als 3 s unterbrochen | Neues Beobachtungsfenster |

## Durchführung auf dem NAS

1. Erst die Konfiguration prüfen (Befehl in README). HA starten und Logs auf
   Fehler der drei Integrationen prüfen. `.env` vollständig zuordnen.
2. Zunächst ungefährliche Teststeckdose oder separate Test-HA-Instanz verwenden.
   Simulierte Zustände niemals bei angeschlossenem, druckendem P1S eintragen.
3. Smart Life → HA und HA → Smart Life testen, reale Steckdose dabei unverändert.
4. Offline-/Wiederverbindungstest: Bridge neu laden und Bambu-Verbindung unterbrechen.
   Beim Ausfall blockiert die Logik nach Erkennung; Wiederverbindung beginnt neu.
5. Negativfälle 1–3 und 5–9 beobachten. Kein `switch.turn_off` darf ausgelöst werden.
6. Positivfall 4 bei beaufsichtigtem, erfolgreich abgeschlossenem Druck testen:
   `finish`, 100 %, Ist-/Solltemperaturen, Zeitfenster, Steckdose, One-Shot-Reset.
7. HA während Cooldown neu starten. Freigabe muss erhalten bleiben, der Safe-Sensor
   darf nicht aus einem gespeicherten `on` starten.
8. Unbestätigte Ausschaltung an einer Teststeckdose prüfen. Nicht nur den Dienstaufruf,
   sondern die neue `off`-Meldung und den Fehler-Quittierweg kontrollieren.

Erst nach diesen Tests unbeaufsichtigt verwenden. Keine neue Druck-/Heizaktion
starten, während eine Abschaltung freigegeben ist. Cloud-Befehle können nicht
atomar mit dem Druckerstatus ausgeführt werden.
