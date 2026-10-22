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

## Alpha.2 cold-host finding and alpha.3 correction

A fresh Ubuntu 24.04 amd64 VM installed Docker29.9.2/containerd and downloaded/loaded
all five public alpha.2 images, then failed exact ID verification before database
startup. This is a reproduced release limitation; it does not add a supported row.
The native OCI and classic config IDs differ. Explicit build mode is its workaround.

The alpha.3 candidate records both native identities and requires the same OCI
archives through native classic/containerd CI consumers on both architectures.
A real tiny OCI archive already demonstrates correct native matching and rejected
tampered digests on both stores. Public alpha.3 clean-host production/HTTP
installation passed on the same
Ubuntu 24.04.5 amd64 base, with both worker queues observed and independent
Chromium owner setup/login, schedule editing and a new queued operation. Its
same-command resume retained owner/password, the edited 2 s schedule and runtime
credentials, verified through an independent login and unchanged runtime.env SHA.
The domain was browser-mapped to the disposable VM; this does not prove public
DNS or ACME. Other OS/architecture/environment cells remain pending.

## Cold installation timing

Both observations used the same official Ubuntu 24.04.5 amd64 cloud-image base,
2 vCPU / 4 GiB KVM, no installed Docker/Papilio or image cache, production/HTTP, and
actual public alpha.3 source/native image downloads. The new bootstrap uses
native APT repository selection and dependency resolution; no service was dropped.

| Observation | Duration | Scope |
| --- | --- | --- |
| Original public one-line command | 326795 ms | Included unconditional full system-index refresh and redundant prerequisite work. |
| Corrected bootstrap | 186883 ms | Corrected script staged by SCP before timing; actual public release downloads, Docker install, migrations, panel and both worker checks included. |

Corrected-run milestones: first application stage 40263 ms; image preparation
started 40400 ms and ended 150502 ms; migrations started 159144 ms; final startup
started 166736 ms. Image preparation therefore took 110102 ms. The measured total
reduction was 139912 ms. These are single observations, not a universal speed
guarantee; the script's own initial download is excluded from the corrected run.
PasarGuard was source-inspected, not benchmarked on this VM. Fast installation
remains in progress. Independent Chromium setup/login, edited schedule, actual
worker operation and session reload passed after the corrected cold run.
