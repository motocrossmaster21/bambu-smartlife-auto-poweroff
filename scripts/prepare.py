"""Create missing runtime files without overwriting local configuration."""
from pathlib import Path
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--config-dir", default="runtime/homeassistant")
args = parser.parse_args()
root = Path(args.config_dir)
root.mkdir(parents=True, exist_ok=True)
(root / "custom_components").mkdir(exist_ok=True)
target = root / "automations.yaml"
if not target.exists():
    target.write_text("[]\n", encoding="utf-8")
print("Runtime directory prepared; existing files preserved.")
