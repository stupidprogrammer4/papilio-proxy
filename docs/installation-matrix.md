# Installation evidence matrix

Candidate systems follow the approved plan, not a claim about every old/new OS.
Docker's own supported distributions are documented for
[Ubuntu](https://docs.docker.com/engine/install/ubuntu/) and
[Debian](https://docs.docker.com/engine/install/debian/); application support also
requires an actual complete Papilio installation test.

| OS | amd64 | arm64 | Exact evidence |
| --- | --- | --- | --- |
| Ubuntu 22.04 | Pending | Pending | Candidate only. |
| Ubuntu 24.04 | Clean-host sandbox installed | Pending | Disposable KVM VM, official 24.04.5 cloud image; initially no Docker. Bootstrap installed Docker/Compose, built images, migrated PostgreSQL and observed both worker queues. Published-artifact and expanded browser/recovery gates remain open. |
| Ubuntu 26.04 | Pending | Pending | Candidate only. |
| Debian 12 | Pending | Pending | Candidate only. |
| Debian 13 | Pending | Pending | Candidate only. |
| Windows / macOS / other versions | Planned expansion | Planned expansion | No bootstrap support claim. |

Local full Compose installation/backup/restore/stop/start were also exercised on
an Ubuntu 25.10 development host with an already installed Docker engine. That is
explicit development evidence outside the candidate OS matrix, not certification.

The CI installer job uses an Ubuntu runner with Docker already present; it proves
Compose/browser/recovery behavior and does not replace a clean-host bootstrap test.
Host Python compatibility has a separate 3.10/3.12/3.13 unit matrix; backend Python
is always 3.13 inside its container.

Production HTTPS issuance, each additional OS/architecture, and each environment's
clean bootstrap remain separate checks. Support is reported at the tested scope.
