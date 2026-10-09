"""Generate private, editable native settings without starting services."""

import argparse
import getpass
import hashlib
import ipaddress
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "panel" / "backend"
if not (BACKEND / "config.yml.sample").is_file():
    BACKEND = Path("/app")
sys.path.insert(0, str(BACKEND))


def write_private(path: Path, content: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    if os.name != "nt" and os.fstat(descriptor).st_mode & 0o077:
        os.close(descriptor)
        path.unlink()
        raise ValueError("State filesystem must support private permissions")
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)


def read_private(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Missing or unsafe installation state file")
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise ValueError("Installation state files must be private (0600)")
    return path.read_text(encoding="utf-8")


def parse_env(content: str) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in content.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def env_text(values: dict[str, str]) -> str:
    if any("\n" in value or "\r" in value for value in values.values()):
        raise ValueError("Environment values cannot contain line breaks")
    return "".join(f"{key}={value}\n" for key, value in values.items())


def public_origin(value: str, bot: bool) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or any(char.isspace() for char in value)
    ):
        raise ValueError("Public URL must be an HTTP(S) origin")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not 1 <= port <= 65535:
        raise ValueError("Public URL port is invalid")
    try:
        loopback = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        loopback = parsed.hostname == "localhost"
    if parsed.scheme == "http" and (not loopback or bot):
        raise ValueError("HTTP is supported only for local panel mode")
    if bot and (
        parsed.scheme != "https" or loopback or port not in {443, 8443, 80, 88}
    ):
        raise ValueError(
            "Bot requires public HTTPS on a Telegram webhook port"
        )
    if parsed.scheme == "https" and (
        loopback
        or not re.fullmatch(
            r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", parsed.hostname
        )
    ):
        raise ValueError("Public HTTPS requires a DNS hostname")
    host = parsed.hostname
    if ":" in host:
        raise ValueError("This deployment supports IPv4 and DNS origins")
    default_port = 443 if parsed.scheme == "https" else 80
    suffix = f":{port}" if port != default_port else ""
    return f"{parsed.scheme}://{host}{suffix}"


def validate_settings(raw: dict) -> None:
    from src.config.settings import PapilioSettings

    settings = PapilioSettings.model_validate(raw)
    if (
        settings.core_runtime is None
        or settings.core_runtime.allow_start
        or settings.core_provisioning is None
        or settings.core_provisioning.mode != "disabled"
        or settings.core_usage is None
        or settings.core_usage.mode != "disabled"
        or settings.managed_adapter is not None
        and settings.managed_adapter.enabled
    ):
        raise ValueError(
            "Deployment installation must keep proxy cores disabled"
        )


def bot_values(raw: dict, origin: str, enabled: bool) -> dict[str, str]:
    sample = ROOT / "bot" / ".env.example"
    if not sample.is_file():
        sample = Path(__file__).with_name("bot.env.example")
    values = parse_env(sample.read_text())
    values.update(
        PAPILIO_API_URL="http://api:8000",
        PAPILIO_BOT_KEY=raw["security"]["bot_service_key"],
        BOT_LISTEN_HOST="0.0.0.0",
        BOT_LISTEN_PORT="8020",
        TELEGRAM_WEBHOOK_PUBLIC_URL=origin + "/telegram/webhook"
        if enabled
        else "",
        TELEGRAM_WEBHOOK_SECRET=secrets.token_urlsafe(32),
    )
    if enabled:
        token = getpass.getpass("Telegram bot token: ")
        if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
            raise ValueError("Invalid Telegram bot token format")
        values["TELEGRAM_BOT_TOKEN"] = token
    return values


def owner_password(username: str) -> str:
    from pydantic import SecretStr
    from src.modules.accounts.staff.domain.dtos import StaffCredentials

    password = getpass.getpass("Owner password: ")
    if getpass.getpass("Confirm owner password: ") != password:
        raise ValueError("Owner passwords do not match")
    StaffCredentials(username=username, password=SecretStr(password))
    return password


def runtime_values(args, origin: str, state: Path) -> dict[str, str]:
    host_state = args.host_state_dir or str(state)
    project = args.project_name or (
        "papilio-" + hashlib.sha256(host_state.encode()).hexdigest()[:12]
    )
    if (
        not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", project)
        or len("deployment-" + project) > 128
    ):
        raise ValueError("Invalid Compose project name")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.owner_username):
        raise ValueError("Owner username cannot contain environment syntax")
    if any(char in host_state for char in "\n\r$#'\""):
        raise ValueError("State path contains unsupported environment syntax")
    try:
        address = ipaddress.ip_address(args.bind_address)
        if address.version != 4:
            raise ValueError("This Compose mapping currently supports IPv4")
    except ValueError:
        raise ValueError("Bind address must be an IPv4 address") from None
    network = ipaddress.ip_network(args.network_subnet, strict=True)
    if network.version != 4 or network.num_addresses - 3 < 8:
        raise ValueError(
            "Compose network requires IPv4 /28 or a larger address pool"
        )
    if (
        hasattr(os, "geteuid")
        and os.geteuid() != 0
        and (args.run_uid != os.getuid() or args.run_gid != os.getgid())
    ):
        raise ValueError("Non-root configuration must use its own UID/GID")
    https_port = (
        args.https_port
        or (
            urlsplit(origin).port
            if urlsplit(origin).scheme == "https"
            else None
        )
        or 443
    )
    if urlsplit(origin).scheme == "http" and args.http_port != (
        urlsplit(origin).port or 80
    ):
        raise ValueError("HTTP bind port must match the public URL")
    if args.http_port == https_port:
        raise ValueError("HTTP and HTTPS bind ports must differ")
    if urlsplit(origin).scheme == "https" and https_port != (
        urlsplit(origin).port or 443
    ):
        raise ValueError("HTTPS bind port must match the public URL")
    numbers = {
        "HTTP_PORT": args.http_port,
        "HTTPS_PORT": https_port,
        "WORKER_COUNT": args.worker_count,
        "WORKER_CONCURRENCY": args.worker_concurrency,
        "SCHEDULER_INTERVAL": args.scheduler_interval,
        "START_TIMEOUT": args.start_timeout,
        "RUN_UID": args.run_uid,
        "RUN_GID": args.run_gid,
    }
    if (
        min(
            value
            for key, value in numbers.items()
            if key not in {"RUN_UID", "RUN_GID"}
        )
        <= 0
        or min(args.run_uid, args.run_gid) < 0
        or max(numbers["HTTP_PORT"], numbers["HTTPS_PORT"]) > 65535
    ):
        raise ValueError("Ports and operational capacities must be positive")
    return {
        "STATE_DIR": host_state,
        "PUBLIC_URL": origin,
        "OWNER_USERNAME": args.owner_username,
        "BOT_ENABLED": "true" if args.enable_bot else "false",
        "BIND_ADDRESS": args.bind_address,
        "PROJECT_NAME": project,
        "PUBLIC_HOST": urlsplit(origin).hostname or "",
        "NETWORK_SUBNET": str(network),
        "CADDY_IPV4": str(network.broadcast_address - 1),
        **{name: str(value) for name, value in numbers.items()},
    }


def validate_existing(state: Path, requested: dict[str, str]) -> None:
    metadata = json.loads(read_private(state / "installation.json"))
    if metadata != {"version": 1}:
        raise ValueError("Unexpected installation state version")
    runtime = parse_env(read_private(state / "compose.env"))
    image_overrides = {
        "PYTHON_IMAGE",
        "NODE_IMAGE",
        "CADDY_IMAGE",
        "MYSQL_IMAGE",
        "REDIS_IMAGE",
    }
    if (
        any(runtime.get(key) != value for key, value in requested.items())
        or set(runtime) - set(requested) - image_overrides
    ):
        raise ValueError(
            "Existing installation options differ; edit existing settings "
            "explicitly and reuse their Compose options"
        )
    raw = yaml.safe_load(read_private(state / "config.yml"))
    validate_settings(raw)
    mysql = read_private(state / "secrets/mysql-password").strip()
    redis = read_private(state / "secrets/redis-password").strip()
    read_private(state / "secrets/mysql-root-password")
    read_private(state / "secrets/owner-password")
    if (
        raw["db"]["dsn"]
        != f"mysql+aiomysql://papilio:{mysql}@mysql:3306/papilio"
        or raw["redis"]["url"] != f"redis://:{redis}@redis:6379/0"
        or raw["tasks"]["scheduler"]["url"] != raw["redis"]["url"]
    ):
        raise ValueError(
            "Database/Redis settings do not match persisted secrets"
        )
    bot = parse_env(read_private(state / "bot.env"))
    read_private(state / "Caddyfile")
    if bot["PAPILIO_BOT_KEY"] != raw["security"]["bot_service_key"]:
        raise ValueError("Bot and API service keys differ")
    if requested["BOT_ENABLED"] == "true" and (
        not bot["TELEGRAM_BOT_TOKEN"]
        or bot["TELEGRAM_WEBHOOK_PUBLIC_URL"]
        != requested["PUBLIC_URL"] + "/telegram/webhook"
    ):
        raise ValueError("Enabled bot configuration is incomplete")


def enable_existing_bot(state: Path, requested: dict[str, str]) -> None:
    previous = {**requested, "BOT_ENABLED": "false"}
    validate_existing(state, previous)
    requested = {**parse_env(read_private(state / "compose.env")), **requested}
    values = parse_env(read_private(state / "bot.env"))
    if not values["TELEGRAM_BOT_TOKEN"]:
        token = getpass.getpass("Telegram bot token: ")
        if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
            raise ValueError("Invalid Telegram bot token format")
        values["TELEGRAM_BOT_TOKEN"] = token
    values["TELEGRAM_WEBHOOK_PUBLIC_URL"] = (
        requested["PUBLIC_URL"] + "/telegram/webhook"
    )
    # Runtime selection is committed last. An interrupted enable remains
    # disabled and can resume without replacing its existing secrets.
    for name, content in (
        ("bot.env", env_text(values)),
        ("Caddyfile", caddyfile(requested["PUBLIC_URL"], True)),
        ("compose.env", env_text(requested)),
    ):
        target = state / name
        descriptor, temporary = tempfile.mkstemp(prefix=".enable-", dir=state)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(content)
            if hasattr(os, "chown") and os.geteuid() == 0:
                os.chown(temporary, target.stat().st_uid, target.stat().st_gid)
            os.replace(temporary, target)
        finally:
            if Path(temporary).exists():
                Path(temporary).unlink()


def caddyfile(origin: str, enabled: bool) -> str:
    telegram = "reverse_proxy bot:8020" if enabled else "respond 404"
    routes = (
        "    root * /srv\n"
        "    handle /api/* {\n"
        "        uri strip_prefix /api\n"
        "        reverse_proxy api:8000\n"
        "    }\n"
        "    handle /v1/* {\n        reverse_proxy api:8000\n    }\n"
        "    handle /healthz {\n        reverse_proxy api:8000\n    }\n"
        f"    handle /telegram/webhook {{\n        {telegram}\n    }}\n"
        "    handle {\n"
        "        try_files {path} /index.html\n"
        "        file_server\n"
        "    }\n"
    )
    if urlsplit(origin).scheme == "http":
        return "http://:8080 {\n" + routes + "}\n"
    host = urlsplit(origin).hostname
    return (
        "{\n    http_port 8080\n    https_port 8443\n"
        "    auto_https disable_redirects\n}\n"
        f"https://{host} {{\n" + routes + "}\n"
        "http://:8080 {\n"
        "    handle /healthz {\n        reverse_proxy api:8000\n    }\n"
        f"    handle {{\n        redir {origin}{{uri}} 308\n    }}\n" + "}\n"
    )


def configure(args) -> None:
    state = Path(args.state_dir).expanduser().absolute()
    if state.is_symlink():
        raise ValueError("State directory cannot be a symlink")
    origin = public_origin(args.public_url, args.enable_bot)
    runtime = runtime_values(args, origin, state)
    if state.exists() and any(state.iterdir()):
        previous = parse_env(read_private(state / "compose.env"))
        if args.enable_bot and previous.get("BOT_ENABLED") == "false":
            enable_existing_bot(state, runtime)
            print("Bot configuration enabled; existing secrets preserved.")
            return
        validate_existing(state, runtime)
        print("Existing private configuration validated; nothing overwritten.")
        return
    raw = yaml.safe_load(
        (
            BACKEND / "config.yml.sample"
            if (BACKEND / "config.yml.sample").is_file()
            else Path(__file__).with_name("config.yml.sample")
        ).read_text()
    )
    mysql, redis = secrets.token_hex(32), secrets.token_hex(32)
    raw["db"]["dsn"] = f"mysql+aiomysql://papilio:{mysql}@mysql:3306/papilio"
    raw["db"]["test_dsn"] = (
        f"mysql+aiomysql://papilio:{mysql}@mysql:3306/papilio_test"
    )
    raw["redis"]["url"] = f"redis://:{redis}@redis:6379/0"
    raw["tasks"]["scheduler"]["url"] = raw["redis"]["url"]
    raw["crypto"] = {
        "encryption_key": secrets.token_urlsafe(32),
        "password_salt": secrets.token_urlsafe(32),
    }
    raw["security"] = {
        name: secrets.token_urlsafe(32)
        for name in ("admin_session_key", "sms_webhook_key", "bot_service_key")
    }
    raw["run"].update(mode="prod", port=8000)
    raw["storage"].update(path="/app/media", temp_dir="/app/tmp")
    raw["rate_limit"]["trusted_proxies"] = [runtime["CADDY_IPV4"]]
    raw["public"].update(
        admin_origin=origin,
        customer_portal_origin=origin,
        subscription_origin=origin,
        additional_admin_origins=[],
    )
    raw["resellers"]["portal_origin"] = origin
    raw["core_runtime"]["allow_start"] = False
    raw["core_provisioning"]["mode"] = "disabled"
    raw["core_usage"]["mode"] = "disabled"
    validate_settings(raw)
    password = owner_password(args.owner_username)
    bot = bot_values(raw, origin, args.enable_bot)
    state.parent.mkdir(parents=True, exist_ok=True)
    state.mkdir(mode=0o700, exist_ok=True)
    state.chmod(0o700)
    staging = Path(tempfile.mkdtemp(prefix=".papilio-config-", dir=state))
    published: list[Path] = []
    try:
        write_private(
            staging / "config.yml", yaml.safe_dump(raw, allow_unicode=True)
        )
        write_private(staging / "bot.env", env_text(bot))
        write_private(staging / "compose.env", env_text(runtime))
        write_private(
            staging / "Caddyfile", caddyfile(origin, args.enable_bot)
        )
        write_private(staging / "installation.json", '{"version":1}\n')
        write_private(staging / "secrets/mysql-password", mysql + "\n")
        write_private(
            staging / "secrets/mysql-root-password",
            secrets.token_hex(32) + "\n",
        )
        write_private(staging / "secrets/redis-password", redis + "\n")
        write_private(staging / "secrets/owner-password", password)
        (staging / "media").mkdir(mode=0o700)
        (staging / "tmp").mkdir(mode=0o700)
        if hasattr(os, "chown") and os.geteuid() == 0:
            for path in [staging, *staging.rglob("*")]:
                os.chown(path, args.run_uid, args.run_gid)
            os.chown(state, args.run_uid, args.run_gid)
        # All files are complete before publication. Marker is published last;
        # a terminated publication remains explicitly incomplete, never reused.
        names = [
            path.name
            for path in staging.iterdir()
            if path.name != "installation.json"
        ] + ["installation.json"]
        for name in names:
            target = state / name
            if target.exists():
                raise ValueError(
                    "Installation state changed during publication"
                )
            (staging / name).rename(target)
            published.append(target)
    except BaseException:
        for target in reversed(published):
            shutil.rmtree(target) if target.is_dir() else target.unlink()
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    print(
        "Private native configuration created; services have not been started."
    )


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--state-dir", required=True)
    cli.add_argument("--host-state-dir")
    cli.add_argument("--public-url", required=True)
    cli.add_argument("--owner-username", required=True)
    cli.add_argument("--enable-bot", action="store_true")
    cli.add_argument("--bind-address", default="127.0.0.1")
    cli.add_argument("--http-port", type=int, default=80)
    cli.add_argument("--https-port", type=int)
    cli.add_argument("--project-name")
    cli.add_argument("--network-subnet", default="172.30.58.0/24")
    cli.add_argument("--worker-count", type=int, default=1)
    cli.add_argument("--worker-concurrency", type=int, default=4)
    cli.add_argument("--scheduler-interval", type=int, default=1)
    cli.add_argument("--start-timeout", type=int, default=180)
    cli.add_argument(
        "--run-uid",
        type=int,
        default=os.getuid() if hasattr(os, "getuid") else 1000,
    )
    cli.add_argument(
        "--run-gid",
        type=int,
        default=os.getgid() if hasattr(os, "getgid") else 1000,
    )
    return cli


if __name__ == "__main__":
    try:
        configure(parser().parse_args())
    except (ValueError, OSError, KeyError, TypeError):
        raise SystemExit(
            "Configuration rejected. Check URL/options, complete private "
            "state, and native settings; no secrets printed."
        ) from None
