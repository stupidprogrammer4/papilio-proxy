#!/usr/bin/env bash
set -euo pipefail

# The bootstrap owns prerequisites; Python owns private instance configuration.
papilio_version=0.1.0-alpha.3
papilio_environment=production
papilio_instance=default
papilio_home=/opt/papilio
papilio_command_path=/usr/local/bin/papilio
papilio_source=
papilio_release_source=false
papilio_has_image_mode=false
papilio_allow_unverified=false
papilio_has_host=false
papilio_has_node_options=false
papilio_interactive=auto
papilio_update=false
papilio_update_arguments=()
papilio_install_arguments=()
papilio_configuration_arguments=()
while (($#)); do
    case "$1" in
        --version) papilio_version=${2:?version required}; shift 2 ;;
        --environment) papilio_environment=${2:?environment required}; shift 2 ;;
        --instance) papilio_instance=${2:?instance required}; shift 2 ;;
        --home) papilio_home=${2:?installation home required}; shift 2 ;;
        --command-path) papilio_command_path=${2:?command path required}; shift 2 ;;
        --source) papilio_source=${2:?release source directory required}; shift 2 ;;
        --update) papilio_update=true; shift ;;
        --interactive) papilio_interactive=true; shift ;;
        --non-interactive) papilio_interactive=false; shift ;;
        --image-mode)
            case "${2:?image mode required}" in auto|prebuilt|build) ;; *) echo 'Choose auto, prebuilt or build.' >&2; exit 2 ;; esac
            papilio_has_image_mode=true
            papilio_install_arguments+=(--image-mode "$2")
            papilio_configuration_arguments+=(--image-mode "$2")
            papilio_update_arguments+=(--image-mode "$2")
            shift 2 ;;
        --allow-unverified-host)
            papilio_allow_unverified=true
            papilio_install_arguments+=(--allow-unverified-host)
            shift ;;
        --scheme)
            case "${2:?scheme required}" in http|https) ;; *) echo 'Choose http or https.' >&2; exit 2 ;; esac
            papilio_install_arguments+=(--scheme "$2")
            papilio_configuration_arguments+=(--scheme "$2")
            shift 2 ;;
        --local-node|--no-local-node)
            papilio_has_node_options=true
            papilio_install_arguments+=("$1")
            papilio_configuration_arguments+=("$1")
            shift ;;
        --host|--bind|--port|--https-port|--node-port)
            if [[ "$1" == --host ]]; then papilio_has_host=true; fi
            if [[ "$1" == --node-port ]]; then papilio_has_node_options=true; fi
            papilio_install_arguments+=("$1" "${2:?value required}")
            papilio_configuration_arguments+=("$1" "$2")
            shift 2 ;;
        --help)
            printf '%s\n' 'Usage: install.sh [--update] [--environment dev|test|sandbox|production] [--host DOMAIN_OR_IP] [--scheme http|https] [--image-mode auto|prebuilt|build] [--interactive|--non-interactive] [--instance NAME] [--port PORT] [--home PATH]'
            printf '%s\n' 'Current-source local runtime: [--local-node|--no-local-node] [--node-port PORT]'
            exit 0 ;;
        *) printf 'Unknown installer option: %s\n' "$1" >&2; exit 2 ;;
    esac
done
[[ "$papilio_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[a-z0-9.]+)?$ ]] || { echo 'Invalid release version.' >&2; exit 2; }
[[ "$papilio_instance" =~ ^[a-z0-9][a-z0-9-]{0,39}$ ]] || { echo 'Invalid instance name.' >&2; exit 2; }
case "$papilio_environment" in dev|test|sandbox|production) ;; *) echo 'Invalid environment.' >&2; exit 2 ;; esac
if $papilio_update; then papilio_interactive=false; fi
if $papilio_update && $papilio_has_node_options; then
    echo 'Update preserves local runtime settings; use install options for a new installation.' >&2
    exit 2
fi
if [[ "$papilio_interactive" == auto ]]; then
    if (: </dev/tty) 2>/dev/null; then papilio_interactive=true; else papilio_interactive=false; fi
fi
if $papilio_interactive && ! (: </dev/tty) 2>/dev/null; then
    echo 'Interactive installation requires a controlling terminal.' >&2
    exit 2
fi
if ! $papilio_update && ! $papilio_interactive && [[ "$papilio_environment" == production ]] && ! $papilio_has_host; then
    echo 'Unattended production installation requires --host DOMAIN_OR_IP.' >&2
    exit 2
fi
[[ -f /etc/os-release && $(uname -s) == Linux ]] || { echo 'This alpha bootstrap targets Linux.' >&2; exit 1; }
# This is the operating system's trusted release metadata, not an instance file.
. /etc/os-release
case "${ID:-}:${VERSION_ID:-}:$(uname -m)" in
    ubuntu:22.04:x86_64|ubuntu:24.04:x86_64|ubuntu:26.04:x86_64|debian:12:x86_64|debian:13:x86_64|ubuntu:22.04:aarch64|ubuntu:24.04:aarch64|ubuntu:26.04:aarch64|debian:12:aarch64|debian:13:aarch64) ;;
    *) $papilio_allow_unverified || { echo 'OS/architecture outside the candidate matrix.' >&2; exit 1; } ;;
esac
if ! command -v python3 >/dev/null || ! command -v curl >/dev/null || [[ ! -s /etc/ssl/certs/ca-certificates.crt ]]; then
    [[ $EUID == 0 ]] || { echo 'Run the bootstrap with sudo to install prerequisites.' >&2; exit 1; }
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3 curl ca-certificates
fi
python3 -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10 or newer is required"'
papilio_download=$(mktemp -d)
trap 'rm -rf -- "$papilio_download"' EXIT

if [[ -z "$papilio_source" ]]; then
    papilio_release_source=true
    papilio_source="$papilio_home/releases/papilio-$papilio_version"
    if [[ ! -d "$papilio_source" ]]; then
        papilio_asset="papilio-$papilio_version.tar.gz"
        papilio_url="https://github.com/stupidprogrammer4/papilio-proxy/releases/download/v$papilio_version"
        curl --fail --location --show-error --connect-timeout 15 --max-time 900 "$papilio_url/$papilio_asset" --output "$papilio_download/$papilio_asset"
        curl --fail --location --show-error --connect-timeout 15 --max-time 60 "$papilio_url/SHA256SUMS" --output "$papilio_download/SHA256SUMS"
        (
            cd "$papilio_download"
            sha256sum --check --ignore-missing --strict SHA256SUMS
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
if $papilio_has_node_options && [[ ! -f "$papilio_source/deployment/compose.local-node.yml" ]]; then
    echo 'This release has no local node installer. Use a current source bundle or a later release.' >&2
    exit 2
fi
if $papilio_update; then
    python3 "$papilio_source/deployment/papilio.py" --home "$papilio_home" --environment "$papilio_environment" --instance "$papilio_instance" update --source "$papilio_source" "${papilio_update_arguments[@]}"
    exit 0
fi
if $papilio_release_source && ! $papilio_has_image_mode && [[ ! -f "$papilio_home/$papilio_environment/$papilio_instance/installation.json" ]]; then
    papilio_install_arguments+=(--image-mode prebuilt)
    papilio_configuration_arguments+=(--image-mode prebuilt)
fi
if $papilio_interactive; then
    if [[ -f "$papilio_home/$papilio_environment/$papilio_instance/installation.json" ]]; then
        papilio_configuration_arguments+=(--existing-root "$papilio_home/$papilio_environment/$papilio_instance")
    fi
    PYTHONPATH="$papilio_source/deployment" python3 -m papilio_installer.tui \
        --output "$papilio_download/settings.json" --environment "$papilio_environment" \
        --instance "$papilio_instance" "${papilio_configuration_arguments[@]}"
    papilio_install_arguments=(--settings-file "$papilio_download/settings.json")
    if $papilio_allow_unverified; then papilio_install_arguments+=(--allow-unverified-host); fi
fi
# Validate selected ports before installing or starting a container engine.
PYTHONPATH="$papilio_source/deployment" python3 - "$papilio_environment" --home "$papilio_home" --instance "$papilio_instance" "${papilio_install_arguments[@]}" <<'PY'
import argparse, sys
from pathlib import Path
from papilio_installer.configuration import Installation, InstallSettings, load_settings
from papilio_installer.preflight import check_ports
parser = argparse.ArgumentParser()
parser.add_argument("environment")
parser.add_argument("--home", type=Path)
parser.add_argument("--instance")
parser.add_argument("--port", type=int)
parser.add_argument("--https-port", type=int)
parser.add_argument("--local-node", action=argparse.BooleanOptionalAction, default=None)
parser.add_argument("--node-port", type=int)
parser.add_argument("--host")
parser.add_argument("--scheme", choices=("http", "https"))
parser.add_argument("--bind")
parser.add_argument("--settings-file", type=Path)
parser.add_argument("--image-mode", choices=("auto", "prebuilt", "build"), default="auto")
parser.add_argument("--allow-unverified-host", action="store_true")
args = parser.parse_args()
if args.settings_file is not None:
    settings = load_settings(args.settings_file)
else:
    options = dict(environment=args.environment, instance=args.instance, host=args.host or "localhost", scheme=args.scheme, http_port=args.port, https_port=args.https_port, bind_address=args.bind, image_mode=args.image_mode)
    existing = args.home / args.environment / args.instance
    if existing.exists():
        saved = Installation.load(existing).settings
        if hasattr(saved, "local_node"):
            options["local_node"] = saved.local_node
            options["node_port"] = saved.node_port
    if args.local_node is not None:
        options["local_node"] = args.local_node
    if args.node_port is not None:
        options["node_port"] = args.node_port
    settings = InstallSettings.from_options(**options)
settings.validate()
if not (args.home / settings.environment / settings.instance / "installation.json").exists():
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
    # Refresh the new repository without downloading unrelated distro indexes.
    # Preserve existing lists; resolve missing distro dependencies through APT below.
    apt-get update -o Dir::Etc::sourcelist=/etc/apt/sources.list.d/docker.sources \
        -o Dir::Etc::sourceparts=- -o APT::Get::List-Cleanup=0
    if command -v docker >/dev/null; then
        papilio_docker_packages=(docker-compose-plugin docker-buildx-plugin)
    else
        papilio_docker_packages=(docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin)
    fi
    if ! apt-get --simulate install "${papilio_docker_packages[@]}" >/dev/null 2>&1; then
        printf '%s\n' 'Refreshing system package indexes for missing Docker dependencies.'
        apt-get update
    fi
    DEBIAN_FRONTEND=noninteractive apt-get install -y "${papilio_docker_packages[@]}"
fi
python3 "$papilio_source/deployment/papilio.py" --home "$papilio_home" --environment "$papilio_environment" --instance "$papilio_instance" install --source "$papilio_source" --command-path "$papilio_command_path" "${papilio_install_arguments[@]}"
