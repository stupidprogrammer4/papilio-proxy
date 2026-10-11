"""Build a locally signed APK with installed Android SDK tools when Gradle is offline."""

import argparse
import json
import os
import re
import shutil
import ssl
import subprocess
import zipfile
from pathlib import Path
from urllib.parse import urlsplit


def local_connection(args: argparse.Namespace, resources: Path, assets: Path) -> None:
    if not args.local_api_origin and not args.local_ca_certificate:
        return
    if not args.local_api_origin or not args.local_ca_certificate:
        raise ValueError(
            "Local HTTPS needs both an origin and its public CA certificate"
        )
    origin = urlsplit(args.local_api_origin)
    if (
        origin.scheme != "https"
        or origin.hostname != "localhost"
        or origin.username is not None
        or origin.password is not None
        or origin.path not in {"", "/"}
        or origin.query
        or origin.fragment
        or origin.port is None
        or not 0 < origin.port < 65536
    ):
        raise ValueError(
            "Local test origin must be https://localhost with an explicit port"
        )
    certificate = args.local_ca_certificate.read_text(encoding="ascii")
    if "PRIVATE KEY" in certificate or certificate.count("BEGIN CERTIFICATE") != 1:
        raise ValueError("Only one public CA certificate may be packaged")
    ssl.PEM_cert_to_DER_cert(certificate)
    (resources / "raw").mkdir(exist_ok=True)
    (resources / "raw/local_test_ca.pem").write_text(certificate, encoding="ascii")
    (resources / "xml/network_security_config.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<network-security-config><base-config cleartextTrafficPermitted="false">'
        '<trust-anchors><certificates src="system"/></trust-anchors></base-config>'
        '<domain-config cleartextTrafficPermitted="false">'
        '<domain includeSubdomains="false">localhost</domain>'
        '<trust-anchors><certificates src="@raw/local_test_ca"/>'
        "</trust-anchors></domain-config></network-security-config>\n"
    )
    defaults = assets / "defaults.json"
    values = json.loads(defaults.read_text())
    values["origin"] = args.local_api_origin.rstrip("/")
    defaults.write_text(json.dumps(values, ensure_ascii=False, indent=2) + "\n")


def build(args: argparse.Namespace) -> Path:
    project = Path(__file__).resolve().parents[1]
    app = project / "app"
    sdk = args.sdk.resolve()
    java = args.java_home.resolve()
    tools = sdk / "build-tools" / args.build_tools
    platform = sdk / "platforms" / args.platform / "android.jar"
    config = (app / "build.gradle.kts").read_text()

    def setting(name: str) -> str:
        match = re.search(rf'\b{re.escape(name)}\s*=\s*(?:"([^"]+)"|(\d+))', config)
        if match is None:
            raise ValueError(f"Missing literal Android build setting: {name}")
        return match.group(1) or match.group(2)

    application_id = setting("applicationId")
    minimum = setting("minSdk")
    target = setting("targetSdk")
    version_code = setting("versionCode")
    version_name = setting("versionName")
    if not platform.is_file():
        raise ValueError("The selected Android platform android.jar is missing")
    compile_sdk = setting("compileSdk")
    if not re.fullmatch(rf"android-{compile_sdk}(?:\.\d+)?", args.platform):
        raise ValueError("The selected platform must match compileSdk")
    work = app / "build" / "native-debug"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    resources = work / "res"
    assets = work / "assets"
    shutil.copytree(app / "src/main/res", resources)
    shutil.copytree(app / "src/main/assets", assets)
    local_connection(args, resources, assets)
    environment = dict(os.environ, JAVA_HOME=str(java))
    environment["PATH"] = str(java / "bin") + os.pathsep + environment["PATH"]

    def run(*command: str | Path) -> None:
        subprocess.run([str(part) for part in command], env=environment, check=True)

    run(
        tools / "aapt2",
        "compile",
        "--dir",
        resources,
        "-o",
        work / "resources.zip",
    )
    manifest = work / "AndroidManifest.xml"
    manifest.write_text(
        (app / "src/main/AndroidManifest.xml")
        .read_text()
        .replace("<manifest ", f'<manifest package="{application_id}" ', 1)
    )
    run(
        tools / "aapt2",
        "link",
        "-o",
        work / "base.apk",
        "-I",
        platform,
        "--manifest",
        manifest,
        "--min-sdk-version",
        minimum,
        "--target-sdk-version",
        target,
        "--version-code",
        version_code,
        "--version-name",
        version_name,
        "--java",
        work / "generated",
        "-A",
        assets,
        work / "resources.zip",
    )
    classes = work / "classes"
    classes.mkdir()
    run(
        java / "bin/javac",
        "-encoding",
        "UTF-8",
        "-source",
        "17",
        "-target",
        "17",
        "-classpath",
        platform,
        "-d",
        classes,
        *sorted((app / "src/main/java").rglob("*.java")),
        *sorted((work / "generated").rglob("*.java")),
    )
    with zipfile.ZipFile(work / "classes.jar", "w") as archive:
        for file in sorted(classes.rglob("*.class")):
            archive.write(file, file.relative_to(classes))
    dex = work / "dex"
    dex.mkdir()
    run(
        tools / "d8",
        "--min-api",
        minimum,
        "--lib",
        platform,
        "--output",
        dex,
        work / "classes.jar",
    )
    with zipfile.ZipFile(work / "base.apk", "a") as archive:
        for file in sorted(dex.glob("*.dex")):
            archive.write(file, file.name)
    run(tools / "zipalign", "-f", "4", work / "base.apk", work / "aligned.apk")
    key = args.debug_keystore.resolve()
    if not key.exists():
        key.parent.mkdir(parents=True, exist_ok=True)
        run(
            java / "bin/keytool",
            "-genkeypair",
            "-keystore",
            key,
            "-storepass",
            "android",
            "-alias",
            "androiddebugkey",
            "-keypass",
            "android",
            "-keyalg",
            "RSA",
            "-keysize",
            "2048",
            "-validity",
            "365",
            "-dname",
            "CN=Papilio Local Debug",
        )
    key.chmod(0o600)
    output = app / "build/outputs/apk/debug/app-debug.apk"
    output.parent.mkdir(parents=True, exist_ok=True)
    run(
        tools / "apksigner",
        "sign",
        "--ks",
        key,
        "--ks-pass",
        "pass:android",
        "--key-pass",
        "pass:android",
        "--out",
        output,
        work / "aligned.apk",
    )
    run(tools / "apksigner", "verify", "--verbose", output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--java-home", type=Path, required=True)
    parser.add_argument("--build-tools", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--debug-keystore", type=Path, required=True)
    parser.add_argument("--local-api-origin")
    parser.add_argument("--local-ca-certificate", type=Path)
    result = build(parser.parse_args())
    print(f"APK: {result}")


if __name__ == "__main__":
    main()
