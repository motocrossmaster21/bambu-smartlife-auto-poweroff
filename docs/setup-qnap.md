# QNAP und Container Station

## Projektordner vorbereiten

Container Station aus dem QNAP App Center installieren. CPU-Unterstützung und
freien Speicher prüfen. Projekt beispielsweise unter
`/share/Container/bambu-smartlife-auto-poweroff` ablegen. Das ganze Projekt
übertragen, nicht nur `compose.yaml`: die schreibgeschützten Dateimounts benötigen
die YAML-Dateien und den Ordner `homeassistant/custom_components/p1s_guard`.

Im Projektordner `.env.example` nach `.env` kopieren. `HA_BIND_IP` auf die LAN-IP
des NAS setzen. `HA_CONFIG_DIR` bezeichnet einen **neuen, dedizierten** HA-Ordner;
keine bestehende HA-Installation mit dieser Konfiguration überlagern.

Standardpfad:

```sh
python3 scripts/prepare.py
python3 scripts/install_integrations.py
```

Alternativer Pfad, zusätzlich so in `.env` setzen:

```sh
python3 scripts/prepare.py --config-dir /share/Container/bambu-homeassistant/config
python3 scripts/install_integrations.py --config-dir /share/Container/bambu-homeassistant/config
```

Die Vorbereitung erstellt nur fehlende Verzeichnisse und eine leere Datei für
UI-Automationen. Der Integrationsinstaller überschreibt nichts. Scheitert eine
Installation nach dem ersten Paket, das erfolgreich installierte Paket erhalten;
für den nächsten Versuch dessen Ordner vorher gesichert beiseitelegen oder die
fehlende Integration separat über HACS installieren.

Python muss nicht im laufenden HA-Container ergänzt werden. Falls auf dem NAS
kein Python vorhanden ist, Vorbereitung/Installation auf dem eigenen Rechner
ausführen und den frisch erzeugten Laufzeitordner ohne private Inhalte aufs NAS
übertragen. Nach Einrichtung enthält er Secrets und darf nicht mehr frei geteilt werden.

## Start über Compose

Per QNAP-Terminal/SSH im Projektordner:

```sh
docker compose config --quiet
docker compose up -d
docker compose ps
docker compose logs --tail=100 homeassistant
```

Die Anwendung anschließend in Container Station öffnen; HA liegt unter
`http://QNAP-IP:8123`. Keine Router-Portweiterleitung einrichten. NAS-Firewall
auf das lokale Netz begrenzen. HA-Onboarding durchführen, anschließend die
Integrationen konfigurieren und die echten Entity-IDs in `.env` übernehmen.

```sh
docker compose up -d --force-recreate
```

## Import in Container Station

Unter **Anwendungen → Erstellen** bietet Container Station einen Compose-YAML-
Editor mit Validierung. Beim Import müssen Projektverzeichnis, Dateimounts und
Umgebungsvariablen korrekt aufgelöst werden. Der Editor übernimmt eine neben
deiner ursprünglichen Datei liegende `.env` nicht in jeder Container-Station-
Version automatisch.

Deshalb zuerst die obige Compose-Variante verwenden. Für einen GUI-Import alle
Bind-Mount-Quellen auf absolute NAS-Pfade umstellen und die Variablen in der
Anwendungsumgebung setzen, soweit die installierte Version dies unterstützt.
Nicht geheime Einstellungen können alternativ im lokalen Import-YAML aufgelöst
werden. **Keine Passwörter oder Tokens in Import-YAML eintragen**; die
Integrationsanmeldung erfolgt erst in HA. Der sichere Loopback-Default bedeutet
bei nicht übernommenem `HA_BIND_IP`, dass HA aus dem LAN nicht erreichbar ist.

Nicht parallel zwei Anwendungen mit denselben Ports und demselben `/config`
starten. Nach Import Logs prüfen und kontrollieren, dass der Guard eingerichtet
wurde und mit Platzhaltern ausschließlich einen blockierten Zustand anzeigt.

## Netzwerk und Rechte

Docker-Bridge mit ausgehender HTTPS-/MQTT-TLS-Verbindung reicht für diesen Aufbau.
DNS und korrekte NAS-Zeit müssen funktionieren. Bambu Cloud, Tuya Cloud sowie
GitHub/Paketquellen für Installation und Updates müssen erreichbar sein.
Ein zusätzlicher MQTT-Broker ist für die Cloud-Verbindung nicht erforderlich.
HA Container besitzt keinen Supervisor/Add-on-Store; HA-OS-Anleitungen für
Terminal- oder File-Editor-Add-ons gelten hier nicht.

Laufzeitordner und `.env` mit QNAP-ACL auf den administrativen Benutzerkreis
beschränken. Keine pauschalen Schreibrechte für alle Benutzer vergeben. Die
offizielle HA-Container-Startumgebung wird beibehalten; ein willkürlich gesetztes
`user:` kann deren Initialisierung verhindern. Zusätzliche Geräte, Hostpfade oder
Capabilities werden nicht benötigt.

Quelle: [QNAP Container Station 3](https://www.qnap.com/en-in/how-to/tutorial/article/how-to-use-container-station-3).
