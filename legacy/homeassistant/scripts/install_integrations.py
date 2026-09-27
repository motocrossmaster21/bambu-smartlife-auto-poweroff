"""Install checksum-pinned upstream integrations; never overwrite an installation."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import urllib.request
import zipfile


def install(config_dir):
    lock = Path(__file__).resolve().parents[1] / "integrations.lock.json"
    for item in json.loads(lock.read_text(encoding="utf-8")):
        target = Path(config_dir) / "custom_components" / item["domain"]
        if target.exists():
            raise SystemExit(f"Refusing to overwrite {target}. Back up and move it aside first.")
        with urllib.request.urlopen(item["url"], timeout=60) as response:
            payload = response.read()
        if hashlib.sha256(payload).hexdigest() != item["sha256"]:
            raise SystemExit(f"Checksum mismatch for {item['domain']}; no files installed for it.")
        selected = []
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for entry in archive.infolist():
                if entry.is_dir() or not entry.filename.startswith(item["prefix"]):
                    continue
                name = entry.filename[len(item["prefix"]):]
                path = PurePosixPath(name)
                if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
                    raise SystemExit("Unsafe archive path")
                selected.append((path, entry))
            if not any(str(path) == "manifest.json" for path, _ in selected):
                raise SystemExit("Integration manifest missing from archive")
            for path, entry in selected:
                destination = target.joinpath(*path.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(entry))
        print(f"Installed {item['domain']} {item['version']} (SHA-256 verified).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", default="runtime/homeassistant")
    install(parser.parse_args().config_dir)
