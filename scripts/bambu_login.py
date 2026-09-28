"""Interactive Bambu login; credentials are never command-line arguments/logs.

Endpoints follow ha-bambulab v2.2.26.
This is not an official Bambu public API.
"""

import base64
from getpass import getpass
from http.cookiejar import CookieJar
import json
from pathlib import Path
import re
import urllib.request


def save_env(values, path=Path(".env")):
    text = (
        path.read_text(encoding="utf-8-sig")
        if path.exists()
        else ""
    )

    lines = [
        line
        for line in text.splitlines()
        if line.split("=", 1)[0].strip() not in values
    ]

    for key, value in values.items():
        # Single-quoted dotenv values prevent interpolation.
        if any(char in value for char in "\r\n'\0"):
            raise ValueError("Invalid credential format")

        lines.append(f"{key}='{value}'")

    path.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8"
    )

    try:
        path.chmod(0o600)
    except OSError:
        # Windows does not fully support POSIX file permissions.
        pass


class Login:
    def __init__(self, region):
        suffix = "cn" if region == "china" else "com"

        self.api = f"https://api.bambulab.{suffix}"
        self.web = f"https://bambulab.{suffix}"

        self.cookies = CookieJar()

        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookies)
        )

    def request(
        self,
        url,
        data=None,
        headers=None
    ):
        request = urllib.request.Request(
            url,
            data=(
                json.dumps(data).encode()
                if data is not None
                else None
            ),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "BambuOff/1.0",
                **(headers or {})
            }
        )

        with self.opener.open(
            request,
            timeout=20
        ) as response:
            payload = response.read()

            return (
                json.loads(payload)
                if payload
                else {}
            )

    def authenticate(
        self,
        account,
        password
    ):
        url = (
            self.api
            + "/v1/user-service/user/login"
        )

        data = self.request(
            url,
            {
                "account": account,
                "password": password,
                "apiError": ""
            }
        )

        token = data.get("accessToken")

        if (
            not token
            and data.get("loginType") == "verifyCode"
        ):
            # Request only during an explicitly invoked interactive login.
            self.request(
                self.api
                + "/v1/user-service/user/sendemail/code",
                {
                    "email": account,
                    "type": "codeLogin"
                }
            )

            data = self.request(
                url,
                {
                    "account": account,
                    "code": getpass(
                        "Bambu E-Mail-Code: "
                    )
                }
            )

            token = data.get("accessToken")

        elif (
            not token
            and data.get("loginType") == "tfa"
        ):
            self.request(
                self.web
                + "/api/sign-in/csrf"
            )

            csrf = next(
                (
                    cookie.value
                    for cookie in self.cookies
                    if cookie.name
                    == "bbl_csrf_token"
                ),
                None
            )

            if not csrf:
                raise ValueError(
                    "CSRF unavailable"
                )

            self.request(
                self.web
                + "/api/sign-in/tfa",
                {
                    "tfaKey": data["tfaKey"],
                    "tfaCode": getpass(
                        "2FA-Code: "
                    )
                },
                {
                    "x-bbl-csrf-token": csrf
                }
            )

            token = next(
                (
                    cookie.value
                    for cookie in self.cookies
                    if cookie.name == "token"
                ),
                None
            )

        if not token:
            raise ValueError(
                "No access token received"
            )

        username = None

        if token.count(".") == 2:
            try:
                encoded = token.split(".")[1]

                decoded = (
                    base64.urlsafe_b64decode(
                        encoded
                        + "="
                        * (-len(encoded) % 4)
                    )
                )

                username = (
                    json.loads(decoded)
                    .get("username")
                )

            except (
                ValueError,
                KeyError,
                json.JSONDecodeError
            ):
                pass

        headers = {
            "Authorization":
                f"Bearer {token}"
        }

        if not username:
            preference = self.request(
                self.api
                + "/v1/design-user-service/my/preference",
                headers=headers
            )

            uid = preference.get("uid")

            if uid is not None:
                username = f"u_{uid}"

        if (
            not isinstance(username, str)
            or not re.fullmatch(
                r"u_[A-Za-z0-9_-]+",
                username
            )
        ):
            raise ValueError(
                "MQTT username missing"
            )

        response = self.request(
            self.api
            + "/v1/iot-service/api/user/bind",
            headers=headers
        )

        devices = response.get(
            "devices",
            []
        )

        return (
            token,
            username,
            devices
        )


def select_region():
    print()
    print("Bambu Cloud Region")
    print("------------------")
    print(
        "1: Global "
        "(Europa, Schweiz, USA usw.)"
    )
    print(
        "2: China "
        "(nur für chinesische Bambu-Konten)"
    )
    print()

    selection = input(
        "Region auswählen "
        "[1=Global, 2=China, Standard=1]: "
    ).strip()

    if selection in ("", "1", "global"):
        return "global"

    if selection in ("2", "china"):
        return "china"

    raise ValueError(
        "Ungültige Region. "
        "Bitte 1 oder 2 eingeben."
    )


def select_device(devices):
    if not devices:
        raise ValueError(
            "Keine Bambu-Drucker "
            "für dieses Konto gefunden."
        )

    print()
    print("Gefundene Bambu-Drucker")
    print("-----------------------")

    for index, device in enumerate(
        devices,
        1
    ):
        name = device.get(
            "name",
            "Drucker"
        )

        model = device.get(
            "product_name",
            "Modell unbekannt"
        )

        serial = device.get(
            "dev_id",
            "Seriennummer unbekannt"
        )

        print(
            f"{index}: "
            f"{name} "
            f"({model})"
        )

        print(
            f"   Seriennummer: "
            f"{serial}"
        )

    print()

    selection = input(
        "Drucker auswählen "
        "(Listennummer oder Seriennummer): "
    ).strip()

    if not selection:
        raise ValueError(
            "Keine Druckerauswahl angegeben."
        )

    # Prefer a list index for simple numeric input.
    if selection.isdigit():
        choice = int(selection)

        if (
            1
            <= choice
            <= len(devices)
        ):
            return devices[
                choice - 1
            ]

    # Also allow selecting the printer by serial number.
    device = next(
        (
            device
            for device in devices
            if (
                str(
                    device.get(
                        "dev_id",
                        ""
                    )
                ).lower()
                == selection.lower()
            )
        ),
        None
    )

    if device:
        return device

    raise ValueError(
        "Drucker nicht gefunden. "
        "Bitte Listennummer oder "
        "Seriennummer verwenden."
    )


def main():
    region = select_region()

    print()
    print(
        f"Verwendete Bambu-Region: "
        f"{region}"
    )
    print()

    account = input(
        "Bambu-Konto (E-Mail): "
    ).strip()

    if not account:
        raise ValueError(
            "E-Mail-Adresse fehlt."
        )

    password = getpass(
        "Bambu-Passwort: "
    )

    token, username, devices = (
        Login(region)
        .authenticate(
            account,
            password
        )
    )

    device = select_device(
        devices
    )

    serial = device.get(
        "dev_id"
    )

    if not serial:
        raise ValueError(
            "Der ausgewählte Drucker "
            "enthält keine Device-ID."
        )

    save_env(
        {
            "BAMBU_REGION":
                region,
            "BAMBU_USERNAME":
                username,
            "BAMBU_ACCESS_TOKEN":
                token,
            "BAMBU_SERIAL":
                serial
        }
    )

    print()
    print(
        "Bambu-Anmeldung erfolgreich."
    )
    print(
        f"Drucker: "
        f"{device.get('name', 'Drucker')}"
    )
    print(
        f"Seriennummer: "
        f"{serial}"
    )
    print()
    print(
        "Zugangsdaten wurden lokal "
        "in .env gespeichert."
    )
    print(
        "Das Bambu-Passwort wurde "
        "nicht gespeichert."
    )
    print(
        "MODE wurde nicht verändert."
    )


def cli():
    try:
        main()
        return 0
    except KeyboardInterrupt:
        print("\nAnmeldung abgebrochen.")
        return 130
    except Exception:
        # Exceptions can contain credentials, URLs or server response bodies.
        print("\nBambu-Anmeldung fehlgeschlagen. Bitte Netzwerk, Region, "
              "Anmeldedaten und Schreibrechte fuer .env lokal pruefen.")
        return 1


if __name__ == "__main__":
    raise SystemExit(cli())
