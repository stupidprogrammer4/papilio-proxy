"""Build a locally signed APK with installed Android SDK tools when Gradle is offline."""

import argparse
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path


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
    environment = dict(os.environ, JAVA_HOME=str(java))
    environment["PATH"] = str(java / "bin") + os.pathsep + environment["PATH"]

    def run(*command: str | Path) -> None:
        subprocess.run([str(part) for part in command], env=environment, check=True)

    run(
        tools / "aapt2",
        "compile",
        "--dir",
        app / "src/main/res",
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
        "-A",
        app / "src/main/assets",
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
    result = build(parser.parse_args())
    print(f"APK: {result}")


if __name__ == "__main__":
    main()
