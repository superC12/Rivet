import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Tests get their own config directory, seeded from the shipped
# templates. Pointing them at ./config would mean any test that saves
# settings rewrites the developer's live configuration, and would leave
# results depending on whatever that developer happened to have set.
TEST_ROOT = ROOT / "data" / "test"
TEST_CONFIG = TEST_ROOT / "config"

shutil.rmtree(TEST_CONFIG, ignore_errors=True)
TEST_CONFIG.mkdir(parents=True, exist_ok=True)
for template in (ROOT / "config").glob("*.yaml.example"):
    shutil.copyfile(template, TEST_CONFIG / template.name)

os.environ.setdefault("RIVET_DATA_DIR", str(TEST_ROOT))
os.environ.setdefault("RIVET_CONFIG_DIR", str(TEST_CONFIG))
