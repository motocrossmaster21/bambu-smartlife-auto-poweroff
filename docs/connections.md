# Cloud-Verbindungen und Fehlerdiagnose

## Bambu

`scripts/bambu_login.py` verwendet den Anmeldeablauf aus `ha-bambulab v2.2.26`:
Konto/Passwort, bei Bedarf E-Mail-Code oder TOTP-2FA mit CSRF/Cookie-Session,
anschließend Druckerauswahl. Die Eingabe erfolgt interaktiv auf deinem Rechner.
Das Skript speichert keine Passwörter. Ein bestehender Cloud-Token kann alternativ
direkt in `.env` eingetragen werden; MQTT-Benutzername ist `u_…`, nicht die E-Mail.

Die konkrete Bambu-Anmeldung wurde ohne dein Konto nicht live getestet. Bei
Captcha, geänderten Anmeldemethoden oder abgewiesenem Login keine wiederholten
Passwortversuche automatisieren. Die App stoppt/bleibt ohne Token gesperrt.
Abgelaufene Tokens mit dem Login-Skript erneuern und den Container neu erstellen.

Es wird ausschließlich `device/<Seriennummer>/report` über TLS/Port 8883
abonniert. Globaler Broker: `us.mqtt.bambulab.com`; China: `cn.mqtt.bambulab.com`.
Kein Request-/Steuer-Topic wird beschrieben. Der Drucker bleibt im Cloud-Modus;
Handy-App und Bambu Studio bleiben verwendbar.

Ausgewertet werden `gcode_state`, `subtask_id`, `mc_percent`, `nozzle_temper`,
`nozzle_target_temper`, `bed_temper`, `bed_target_temper`. Neuere gepackte
Temperaturfelder werden für genau einen Extruder unterstützt. Andere
Druckermodelle, mehrere Düsen und SD-Karten-Jobs ohne positive Cloud-Job-ID
sind nicht freigegeben.

Teilmeldungen werden innerhalb derselben Sitzung zusammengeführt. Status,
Job-ID, Fortschritt, Heizungsziele und Bett-Isttemperatur bleiben bis zur nächsten
Änderung erhalten. Deshalb muss `FINISH` während der Abkühlung nicht wiederholt
werden. Die Düsen-Isttemperatur muss hingegen tatsächlich innerhalb der letzten
`MAX_DATA_AGE_SECONDS` (Standard: 60 Sekunden) empfangen worden sein.
Andere Teilmeldungen frischen ihren Zeitstempel nicht auf.

Nach Verbindungsabbruch, neuer Job-ID oder mehr als 60 Sekunden ohne relevante
Druckerberichte wird der Cache samt Abschlussflanke verworfen. MQTT-Keepalives
allein zählen nicht als Druckerberichte. Nach Neustart/Reconnect sind neue
Pflichtwerte und ein beobachteter aktiver Druck vor `FINISH` erforderlich.
Fehlende Felder werden nie durch Standardwerte ersetzt. Es gibt keinen eigenen
`pushall`-Befehl; nach Start kann deshalb auf weitere Meldungen gewartet werden müssen.
Die Zusammenführung setzt voraus, dass Änderungen im laufenden Datenstrom
ankommen; unbemerkter Verlust einzelner Cloud-Meldungen lässt sich damit nicht ausschließen.

## TuyaLink

Direkte Geräteauthentifizierung: `tuyalink_<deviceId>` als Client-ID, HMAC-SHA256
über Device ID, Zeitpunkt, secureMode und accessType. Der Zeitstempel wird bei
jedem neuen Verbindungsversuch frisch erstellt. TLS-Zertifikate werden geprüft.
Die NAS-/PC-Uhr muss stimmen. Gerät und MQTT-Broker müssen zum selben Datenzentrum gehören.

Der Dienst sendet nur `tylink/<deviceId>/thing/property/report`, mit einem
Boolean-Wert, Zeitstempel und `sys.ack=1`. Erst die passende Tuya-Antwort mit
`code=0` bestätigt eine Meldung. Die initiale AUS-Bestätigung ist Voraussetzung
für das Sicherheitsfenster. Die Statusseite zeigt lokal berechneten Wert und
zuletzt bestätigten Cloud-Wert getrennt an.

QoS 0 mit Tuya-Anwendungsbestätigung vermeidet automatische MQTT-Wiederholungen
alter EIN-Werte. Bei Verbindungsverlust, 10 Sekunden ohne Bestätigung oder Fehler
wird der Client verworfen und neu aufgebaut. Ein bereits im Netz übertragener
Wert kann dadurch nicht zurückgerufen werden. Bei einer unsicheren/ungeklärten
EIN-Übermittlung bleibt der Druck als bereits verarbeitet gespeichert.

## Phasen

| Phase | Bedeutung |
|---|---|
| `CLOUD_DISCONNECTED` | Mindestens eine Verbindung/Subscription oder initiale Tuya-Bestätigung fehlt |
| `MISSING_OR_STALE_DATA` | Pflichtfelder fehlen oder die Düsen-Isttemperatur ist zu alt; siehe `missing_fields` / `stale_fields` |
| `WAITING_FOR_FINISH` | Druck läuft/pausiert/ist fehlgeschlagen oder Status ist unbekannt |
| `MISSING_CLOUD_JOB_ID` | Keine unterstützte eindeutige Cloud-Job-ID |
| `INCOMPLETE_PROGRESS` | Nicht 100 % |
| `INVALID_TEMPERATURE` | Fehlender, nicht numerischer oder unplausibler Wert |
| `WAITING_FOR_COOLDOWN` | Düse zu warm oder ein Heizungsziel nicht 0 |
| `STABILIZING` | Sicherer Zustand wird mindestens 30 Sekunden beobachtet |
| `SAFE` | Lokales EIN-Signal; Cloud-Bestätigung separat beachten |
| `PULSE_COMPLETE` | 30-Sekunden-Impuls abgelaufen, Wert AUS trotz weiterem FINISH |
| `WAITING_COMPLETION_EDGE` | Erst eine neue beobachtete Abschlussflanke kann auslösen |
| `ALREADY_SIGNALED` | Dieser Druck wurde schon signalisiert; kein Wiederholen |

`/health` prüft, ob die App-Schleife arbeitet; HTTP 200 beweist keine
Cloud-Verbindung. `/status` enthält keine Tokens, Geräte-ID oder Seriennummer.
Die Seite ist eine lokale Diagnoseansicht, kein öffentlich abgesicherter Dienst.

Logs mit `docker compose logs --tail=100 bambuoff` lesen. Keine Rohpayloads,
`.env` oder Login-Antworten veröffentlichen. Zugriffsfehler auf die Zustandsdatei
verhindern ein neues EIN-Signal; das Volume nicht einfach löschen, um dies zu umgehen.
