from pathlib import Path
import re


PROJECT = Path(__file__).resolve().parents[2]


def test_one_line_installer_defaults_to_release_version() -> None:
    version = (PROJECT / "VERSION").read_text(encoding="utf-8").strip()
    installer = (PROJECT / "install.sh").read_text(encoding="utf-8")
    match = re.search(r"^papilio_version=(.+)$", installer, re.MULTILINE)

    assert match is not None
    assert match.group(1) == version
