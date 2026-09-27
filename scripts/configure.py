"""Add missing example settings to local .env, preserving all existing values."""
from pathlib import Path


def prepare(path=Path(".env"), example=Path(".env.example")):
    text = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    existing = {line.split("=", 1)[0].strip() for line in text.splitlines()
                if "=" in line and not line.lstrip().startswith("#")}
    additions = [line for line in example.read_text(encoding="utf-8").splitlines()
                 if "=" in line and not line.startswith("#") and line.split("=", 1)[0] not in existing]
    if additions:
        with path.open("a", encoding="utf-8") as stream:
            stream.write("\n# BambuOff settings\n" + "\n".join(additions) + "\n")
        path.chmod(0o600)
    print("Local .env prepared; existing values preserved.")


if __name__ == "__main__":
    prepare()
