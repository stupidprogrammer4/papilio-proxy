# Installation evidence matrix

Candidate systems follow the approved plan, not a claim about every old/new OS.
Docker's own supported distributions are documented for
[Ubuntu](https://docs.docker.com/engine/install/ubuntu/) and
[Debian](https://docs.docker.com/engine/install/debian/); application support also
requires an actual complete Papilio installation test.

| OS | amd64 | arm64 | Exact evidence |
| --- | --- | --- | --- |
| Ubuntu 22.04 | Pending | Pending | Candidate only. |
| Ubuntu 24.04 | Clean-host sandbox installed | Pending | Disposable KVM VM, official 24.04.5 amd64 cloud image; initially no Docker. Public v0.1.0-alpha.1 bootstrap downloaded and verified the release artifact, installed Docker/Compose, built images, migrated PostgreSQL and observed both queues. Real browser setup/login, schedule edit, worker completion and session reload passed through the VM gateway. |
| Ubuntu 26.04 | Pending | Pending | Candidate only. |
| Debian 12 | Pending | Pending | Candidate only. |
| Debian 13 | Pending | Pending | Candidate only. |
| Windows / macOS / other versions | Planned expansion | Planned expansion | No bootstrap support claim. |

Local full Compose installation/backup/restore/stop/start were also exercised on
an Ubuntu 25.10 development host with an already installed Docker engine. That is
explicit development evidence outside the candidate OS matrix, not certification.

Repeating the public sandbox bootstrap after browser setup preserved the owner
and an edited 2-second delivery schedule, verified through a new authenticated
HTTP session. This demonstrates installation resume on that tested combination.

The CI installer job uses an Ubuntu runner with Docker already present; it proves
Compose/browser/recovery behavior and does not replace a clean-host bootstrap test.
Host Python compatibility has a separate 3.10/3.12/3.13 unit matrix; backend Python
is always 3.13 inside its container.

On main, the existing-Docker Compose gate additionally exercises production HTTP
on a browser-mapped non-localhost domain and sandbox HTTPS with a native local
Caddy CA, including custom-port redirects, cookies, actual workers, bot/node
onboarding, recovery and synthetic update. These fixtures do not prove public DNS
or ACME issuance and do not expand the clean-host OS certification above.

Public HTTPS issuance, each additional OS/architecture, and each environment's
clean bootstrap remain separate checks. Support is reported at the tested scope.
