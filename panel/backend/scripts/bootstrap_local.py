import asyncio
import os
import secrets
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CONFIG = ROOT / "config.yml"
CREDENTIALS = ROOT.parents[1] / "data" / "local-admin-credentials"


def write_private(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = path.open("x", encoding="utf-8")
    path.chmod(0o600)
    with descriptor:
        descriptor.write(value)


def main() -> None:
    from scripts.create_owner import create

    sample = yaml.safe_load((ROOT / "config.yml.sample").read_text())
    if not CONFIG.exists():
        raw = sample
        required = (
            "PAPILIO_LOCAL_DB_DSN",
            "PAPILIO_LOCAL_REDIS_URL",
            "PAPILIO_LOCAL_ADMIN_ORIGIN",
            "PAPILIO_LOCAL_SUB_ORIGIN",
        )
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            raise RuntimeError(
                f"Set local configuration: {', '.join(missing)}"
            )
        raw["db"]["dsn"] = os.environ["PAPILIO_LOCAL_DB_DSN"]
        raw["db"]["test_dsn"] = raw["db"]["dsn"]
        raw["tasks"]["scheduler"]["url"] = os.environ[
            "PAPILIO_LOCAL_REDIS_URL"
        ]
        raw["public"]["admin_origin"] = os.environ[
            "PAPILIO_LOCAL_ADMIN_ORIGIN"
        ]
        raw["resellers"]["portal_origin"] = os.environ.get(
            "PAPILIO_LOCAL_RESELLER_ORIGIN", raw["public"]["admin_origin"]
        )
        raw["public"]["subscription_origin"] = os.environ[
            "PAPILIO_LOCAL_SUB_ORIGIN"
        ]
        raw["redis"]["url"] = raw["tasks"]["scheduler"]["url"]
        raw["crypto"] = {
            "encryption_key": secrets.token_urlsafe(32),
            "password_salt": secrets.token_urlsafe(32),
        }
        raw["public"]["additional_admin_origins"] = [
            value.strip()
            for value in os.environ.get(
                "PAPILIO_LOCAL_ADDITIONAL_ADMIN_ORIGINS", ""
            ).split(",")
            if value.strip()
        ]
        raw["security"] = {
            "admin_session_key": secrets.token_urlsafe(32),
            "sms_webhook_key": secrets.token_urlsafe(32),
            "bot_service_key": secrets.token_urlsafe(32),
        }
        write_private(CONFIG, yaml.safe_dump(raw, allow_unicode=True))
    else:
        raw = yaml.safe_load(CONFIG.read_text())
        operations = raw.setdefault("operations", {})
        missing_operations = {
            key: value
            for key, value in sample["operations"].items()
            if key not in operations
        }
        operations.update(missing_operations)
        ip_limits = raw.setdefault("ip_limits", {})
        ip_limits.update(
            {
                key: value
                for key, value in sample["ip_limits"].items()
                if key not in ip_limits
            }
        )
        raw.setdefault(
            "crypto",
            {
                "encryption_key": secrets.token_urlsafe(32),
                "password_salt": secrets.token_urlsafe(32),
            },
        )
        raw.setdefault(
            "redis",
            {**sample["redis"], "url": raw["tasks"]["scheduler"]["url"]},
        )
        raw.setdefault("rate_limit", sample["rate_limit"])
        for rule, definition in sample["rate_limit"].get("rules", {}).items():
            raw["rate_limit"].setdefault("rules", {}).setdefault(
                rule, definition
            )
        for section in (
            "fulfillment",
            "usage",
            "checkout",
            "customer_auth",
            "customers",
            "receipts",
            "qr_codes",
        ):
            configured = raw.setdefault(section, {})
            configured.update(
                {
                    key: value
                    for key, value in sample[section].items()
                    if key not in configured
                }
            )
            if "policy" in sample[section]:
                configured["policy"].update(
                    {
                        key: value
                        for key, value in sample[section]["policy"].items()
                        if key not in configured["policy"]
                    }
                )
        raw["public"].setdefault("additional_admin_origins", [])
        raw["public"].setdefault(
            "brand_title", sample["public"]["brand_title"]
        )
        raw["public"].setdefault(
            "customer_portal_origin",
            sample["public"]["customer_portal_origin"],
        )
        raw["public"].setdefault(
            "customer_link_rotation",
            sample["public"]["customer_link_rotation"],
        )
        if "resellers" not in raw:
            raw["resellers"] = {
                **sample["resellers"],
                "portal_origin": os.environ.get(
                    "PAPILIO_LOCAL_RESELLER_ORIGIN",
                    raw["public"]["admin_origin"],
                ),
            }
        if "loyalty" not in raw:
            raw["loyalty"] = sample["loyalty"]
        if "configuration_json" not in raw:
            raw["configuration_json"] = sample["configuration_json"]
        if "openvpn" not in raw:
            raw["openvpn"] = sample["openvpn"]
        CONFIG.write_text(yaml.safe_dump(raw, allow_unicode=True))
        CONFIG.chmod(0o600)
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        check=True,
    )
    if not CREDENTIALS.exists():
        username = os.environ.get("PAPILIO_LOCAL_OWNER_USERNAME")
        if not username:
            raise RuntimeError("Set PAPILIO_LOCAL_OWNER_USERNAME")
        password = secrets.token_urlsafe(20)
        asyncio.run(create(username, password))
        write_private(
            CREDENTIALS, f"username={username}\npassword={password}\n"
        )
    print("Local database and owner account are ready.")


if __name__ == "__main__":
    main()
