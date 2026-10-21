"""Fetch the pinned, verified official Xray executable used by integration CI."""

import hashlib
import io
import os
import pathlib
import urllib.request
import zipfile

address = (
    "https://github.com/XTLS/Xray-core/releases/download/v26.3.27/Xray-linux-64.zip"
)
with urllib.request.urlopen(address, timeout=90) as response:
    content = response.read()
expected = "23cd9af937744d97776ee35ecad4972cf4b2109d1e0fe6be9930467608f7c8ae"
if hashlib.sha256(content).hexdigest() != expected:
    raise SystemExit("Official Xray archive checksum mismatch.")
target = pathlib.Path(os.environ["PAPILIO_XRAY_BINARY"])
target.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(io.BytesIO(content)) as archive:
    target.write_bytes(archive.read("xray"))
target.chmod(0o755)
