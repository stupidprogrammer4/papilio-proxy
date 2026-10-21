#!/usr/bin/env bash
set -euo pipefail

# The bootstrap owns prerequisites; Python owns private instance configuration.
papilio_version=0.1.0-alpha.1
papilio_environment=sandbox
papilio_instance=default
papilio_home=/opt/papilio
papilio_source=
papilio_allow_unverified=false
papilio_has_host=false
papilio_install_arguments=()
while (($#)); do
    case "$1" in
        --version) papilio_version=${2:?version required}; shift 2 ;;
        --environment) papilio_environment=${2:?environment required}; shift 2 ;;
        --instance) papilio_instance=${2:?instance required}; shift 2 ;;
        --home) papilio_home=${2:?installation home required}; shift 2 ;;
        --source) papilio_source=${2:?release source directory required}; shift 2 ;;
        --allow-unverified-host)
            papilio_allow_unverified=true
            papilio_install_arguments+=(--allow-unverified-host)
            shift ;;
        --host|--bind|--port|--https-port)
            if [[ "$1" == --host ]]; then papilio_has_host=true; fi
            papilio_install_arguments+=("$1" "${2:?value required}")
            shift 2 ;;
        --help)
            printf '%s\n' 'Usage: install.sh --environment dev|test|sandbox|production --host DOMAIN [--instance NAME] [--port PORT] [--home PATH]'
            exit 0 ;;
        *) printf 'Unknown installer option: %s\n' "$1" >&2; exit 2 ;;
    esac
done
[[ "$papilio_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[a-z0-9.]+)?$ ]] || { echo 'Invalid release version.' >&2; exit 2; }
[[ "$papilio_instance" =~ ^[a-z0-9][a-z0-9-]{0,39}$ ]] || { echo 'Invalid instance name.' >&2; exit 2; }
case "$papilio_environment" in dev|test|sandbox|production) ;; *) echo 'Invalid environment.' >&2; exit 2 ;; esac
if [[ "$papilio_environment" == production ]] && ! $papilio_has_host; then
    if [[ -r /dev/tty ]]; then
        read -r -p 'Public domain pointing to this server: ' papilio_domain </dev/tty
        papilio_install_arguments+=(--host "$papilio_domain")
    else
        echo 'Production requires --host DOMAIN.' >&2
        exit 2
    fi
fi
[[ -f /etc/os-release && $(uname -s) == Linux ]] || { echo 'This alpha bootstrap targets Linux.' >&2; exit 1; }
# This is the operating system's trusted release metadata, not an instance file.
. /etc/os-release
case "${ID:-}:${VERSION_ID:-}:$(uname -m)" in
    ubuntu:22.04:x86_64|ubuntu:24.04:x86_64|ubuntu:26.04:x86_64|debian:12:x86_64|debian:13:x86_64|ubuntu:22.04:aarch64|ubuntu:24.04:aarch64|ubuntu:26.04:aarch64|debian:12:aarch64|debian:13:aarch64) ;;
    *) $papilio_allow_unverified || { echo 'OS/architecture outside the candidate matrix.' >&2; exit 1; } ;;
esac
if ! command -v python3 >/dev/null || ! command -v curl >/dev/null; then
    [[ $EUID == 0 ]] || { echo 'Run the bootstrap with sudo to install prerequisites.' >&2; exit 1; }
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3 curl ca-certificates
fi
python3 -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10 or newer is required"'

if [[ -z "$papilio_source" ]]; then
    papilio_source="$papilio_home/releases/papilio-$papilio_version"
    if [[ ! -d "$papilio_source" ]]; then
        papilio_download=$(mktemp -d)
        trap 'rm -rf -- "$papilio_download"' EXIT
        papilio_asset="papilio-$papilio_version.tar.gz"
        papilio_url="https://github.com/stupidprogrammer4/papilio-proxy/releases/download/v$papilio_version"
        curl --fail --location --show-error --connect-timeout 15 --max-time 900 "$papilio_url/$papilio_asset" --output "$papilio_download/$papilio_asset"
        curl --fail --location --show-error --connect-timeout 15 --max-time 60 "$papilio_url/SHA256SUMS" --output "$papilio_download/SHA256SUMS"
        (
            cd "$papilio_download"
            sha256sum --check --strict SHA256SUMS
        )
        # Validate paths and types before extracting any source archive member.
        python3 - "$papilio_download/$papilio_asset" "$papilio_home/releases" "$papilio_version" <<'PY'
import pathlib, shutil, sys, tarfile, tempfile
archive_path, destination, version = sys.argv[1:]
destination = pathlib.Path(destination)
prefix = f"papilio-{version}"
with tarfile.open(archive_path, "r:gz") as archive:
    members = archive.getmembers()
    names = set()
    for member in members:
        path = pathlib.PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or path.parts[0] != prefix:
            raise SystemExit("Unsafe release path.")
        if not (member.isfile() or member.isdir()) or member.name in names:
            raise SystemExit("Unsafe release member.")
        names.add(member.name)
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination) as temporary:
        for member in members:
            target = pathlib.Path(temporary).joinpath(*pathlib.PurePosixPath(member.name).parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o755 if member.mode & 0o111 else 0o644)
        source = pathlib.Path(temporary) / prefix
        if (source / "VERSION").read_text().strip() != version:
            raise SystemExit("Release version mismatch.")
        source.rename(destination / prefix)
PY
    fi
fi
papilio_source=$(realpath "$papilio_source")
# Validate selected ports before installing or starting a container engine.
PYTHONPATH="$papilio_source/deployment" python3 - "$papilio_environment" --home "$papilio_home" --instance "$papilio_instance" "${papilio_install_arguments[@]}" <<'PY'
import argparse, sys
from pathlib import Path
from papilio_installer.configuration import InstallSettings
from papilio_installer.preflight import check_ports
parser = argparse.ArgumentParser()
parser.add_argument("environment")
parser.add_argument("--home", type=Path)
parser.add_argument("--instance")
parser.add_argument("--port", type=int)
parser.add_argument("--https-port", type=int)
parser.add_argument("--host")
parser.add_argument("--bind")
parser.add_argument("--allow-unverified-host", action="store_true")
args = parser.parse_args()
settings = InstallSettings(environment=args.environment, http_port=args.port or (80 if args.environment == "production" else 8080), https_port=args.https_port or (443 if args.environment == "production" else 8443), bind_address=args.bind or ("0.0.0.0" if args.environment == "production" else "127.0.0.1"))
settings.validate()
if not (args.home / args.environment / args.instance / "installation.json").exists():
    check_ports(settings)
PY
if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
    [[ $EUID == 0 ]] || { echo 'Run with sudo to install Docker prerequisites.' >&2; exit 1; }
    if ! command -v docker >/dev/null; then
        if dpkg-query -W -f='${Status}\n' docker.io podman-docker containerd runc 2>/dev/null | grep -q 'install ok installed'; then
            echo 'Existing container packages conflict with Docker Engine. Resolve the package conflict before retrying; no package was removed.' >&2
            exit 1
        fi
    fi
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl
    install -m 0755 -d /etc/apt/keyrings
    curl --fail --silent --show-error "https://download.docker.com/linux/$ID/gpg" --output /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    if [[ ! -f /etc/apt/sources.list.d/docker.sources ]]; then
        cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/$ID
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
    fi
    apt-get update
    if command -v docker >/dev/null; then
        DEBIAN_FRONTEND=noninteractive apt-get install -y docker-compose-plugin docker-buildx-plugin
    else
        DEBIAN_FRONTEND=noninteractive apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    fi
fi
exec python3 "$papilio_source/deployment/papilio.py" --home "$papilio_home" --environment "$papilio_environment" --instance "$papilio_instance" install --source "$papilio_source" --command-path /usr/local/bin/papilio "${papilio_install_arguments[@]}"
