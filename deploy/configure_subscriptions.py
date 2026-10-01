"""Connect the private node socket and public subscription routes on the VPS.

Run as root from /opt/papilio-proxy after staging subscriptions.conf.
This script never prints or rewrites existing secret values.
"""

import subprocess
from pathlib import Path

ROOT = Path("/opt/papilio-proxy")
ENV = ROOT / ".env"
SITE = Path("/etc/nginx/sites-enabled/papilio-callback")
SNIPPET = Path("/etc/nginx/snippets/papilio-subscriptions.conf")
INCLUDE = "    include /etc/nginx/snippets/papilio-subscriptions.conf;\n"


def main() -> None:
    source = ROOT / "deploy/nginx/subscriptions.conf"
    if not source.is_file() or not ENV.is_file() or not SITE.is_file():
        raise SystemExit("Required deployment file is missing")
    snippet_contents = source.read_text()
    if not SNIPPET.exists() or SNIPPET.read_text() != snippet_contents:
        SNIPPET.write_text(snippet_contents)

    config = SITE.read_text()
    if INCLUDE not in config:
        marker = "    location / {\n        return 404;\n    }\n"
        if config.count(marker) != 1:
            raise SystemExit("Unexpected Nginx site layout")
        backup = Path("/etc/nginx/papilio-callback.before-subscriptions")
        if not backup.exists():
            backup.write_text(config)
        SITE.write_text(config.replace(marker, INCLUDE + "\n" + marker))

    subprocess.run(["nginx", "-t"], check=True)
    subprocess.run(["systemctl", "reload", "nginx"], check=True)

    contents = ENV.read_text()
    keys = {line.partition("=")[0] for line in contents.splitlines() if "=" in line}
    additions = {
        "XRAY_NODE_SOCKET": "/run/papilio/node.sock",
        "SUBSCRIPTION_PUBLIC_BASE_URL": "https://bot.amupouya.org",
    }
    for key, value in additions.items():
        if key not in keys:
            contents += f"\n{key}={value}\n"
    ENV.write_text(contents)
    print("Subscription routing and node wiring configured")


if __name__ == "__main__":
    main()
