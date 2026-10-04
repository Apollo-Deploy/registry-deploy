# registry-deploy

[MIT license](LICENSE) · [Installation](#install) · [Client integration](#authentication-and-client-integration) · [Qualification](#production-qualification) · [Contributing](#development-and-contributions)

A small, standalone OCI registry deployment package from **Apollo Deploy**.
Run **CNCF Distribution 3.1.2** on a Linux VPS with **Cloudflare R2** for durable
storage, HTTPS, authentication, and systemd supervision.

Use it for BuildKit remote cache and OCI artifact distribution. The deployment
uses Bash, Python, and standard Linux packages. No Docker engine or Apollo daemon
is required to run the registry.

## Architecture

```text
apollo-buildd / BuildKit ── HTTPS + registry credentials ──┐
                                                        ├─ Distribution ── S3 ── private R2 bucket
apollo-artifactd ────────── HTTPS + registry credentials ─┘
```

Apollo clients receive only the hostname, repository names, and registry credentials.
R2 credentials remain on the registry VPS. There are no Apollo code dependencies.
Distribution can be replaced with any compatible OCI registry.

## What is included

| Capability | Implementation |
| --- | --- |
| Durable storage | Private R2 bucket through Distribution's S3 driver |
| Transport | Direct HTTPS with an operator-provided certificate |
| Authentication | Bcrypt Basic auth compatible with OCI clients and BuildKit |
| Service management | Dedicated account, hardened systemd units, automatic restart |
| Network access | HTTPS and management-CIDR-restricted SSH through UFW |
| Installation | Pinned release checksums and repeatable configuration |
| Updates | Binary verification, health checks, and rollback on failure |
| Verification | Authenticated OCI push/pull, R2 checks, and live BuildKit qualification |

**Production status:** local checks do not qualify a deployment. Run the full
[qualification suite](#production-qualification) on the target VPS with its actual
R2 bucket before admitting production traffic. Live VPS/R2/BuildKit qualification
has not been recorded for this package.

The initial account has registry-wide access. Scoped authorization, certificate
issuance, and artifact retention policies are operator responsibilities; their
boundaries are documented below.

## Package layout

Root scripts are operator entry points. Implementation is grouped by responsibility:

```text
install.sh          # install and verify the registry
update.sh           # verify and activate a reviewed release
uninstall.sh        # remove the service or explicitly purge local files
healthcheck.sh      # machine-readable service, HTTPS, auth, OCI, and R2 checks
qualify.sh          # real registry/R2 and BuildKit qualification
renew-tls.sh        # apply renewed certificates with rollback
templates/          # Distribution, systemd, journal, and settings templates
lib/
├── core/           # shared paths, errors, operation lock and staging
├── deployment/     # host setup, release installation, auth, TLS, firewall
├── configuration/  # inert settings CLI, validation, private YAML generation
├── runtime/        # registry supervision and scheduled upload maintenance
├── storage/        # server-side R2 access
├── verification/   # OCI client and health checks
└── qualification/  # live workload, upload recovery, and BuildKit tests
```

Shell entry points source their dependencies explicitly. Python runs as package
modules from the deployment root; neither imports nor installed systemd units
depend on the operator's current directory. Runtime maintenance depends on storage,
not on qualification code. The OCI client does not import R2 access.

## Requirements and DNS

- Dedicated Debian 12/13 or Ubuntu 24.04 VPS, systemd, amd64 or arm64.
- Starting capacity: 2 vCPU, 2 GB RAM, 20–40 GB SSD; measure workload before sizing.
- Root installation access; working public DNS and outbound HTTPS to R2/GitHub.
- A public-CA full-chain certificate and matching unencrypted key for the hostname.
- A private, existing R2 bucket in the default jurisdiction.
- Fresh UFW configuration; another firewall manager or extra existing rules require
  operator reconciliation first. The installer never resets them silently.

Point the hostname's A record at the VPS. Publish AAAA only with working IPv6.
Use **DNS-only** Cloudflare records: the proxied HTTP service imposes upload limits
and is outside this package's qualification boundary. Port 443 serves direct TLS;
there is no external HTTP listener. Port 5001 is loopback-only debug/health.

Obtain certificates through your existing CA/ACME process. For Let's Encrypt,
DNS-01 avoids opening port 80. This package accepts operator-provided certificates;
it does not install an ACME client or operate a reverse proxy.

## R2 bucket and credentials

Create a private bucket, disable public/r2.dev access, and create a token with
**Object Read & Write → Apply to specific buckets only**, selecting this bucket.
Do not use an account-wide administrative token. Registry uploads need listing,
get/put/delete objects, multipart listing/parts, and multipart abort permissions;
client manifest deletion is disabled independently.

Use the S3 key/secret from that token. The endpoint is
`https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com`, region `auto`, SigV4, path style,
TLS. Jurisdiction-specific endpoints are not supported by this package.

Keep R2's incomplete-multipart lifecycle cleanup enabled as a backstop (normally
seven days). **Do not apply object expiration to the registry prefix.** Deleting
blobs by bucket age breaks manifests and shared layers.

## Install

On the VPS, from this directory:

```sh
sudo install -m 0600 templates/env.example /root/registry-settings.json
sudoedit /root/registry-settings.json
sudo --preserve-env=SSH_CONNECTION ./install.sh /root/registry-settings.json
```

The settings template is **JSON**, despite its `env.example` filename. It is never
sourced as shell code. Replace every placeholder. Required fields are shown in
[the template](templates/env.example).
Use a random registry password of 24–72 UTF-8 bytes (bcrypt's limit), a management
CIDR that covers your SSH source, and your actual SSH port. Preserve
`SSH_CONNECTION` through sudo so the lockout check can validate the live session;
a local console installation has no remote session to check. The key target must be
root-owned mode 0600. The full-chain certificate must cover the hostname and have
at least seven days remaining. Chain trust is checked by the HTTPS health probe.

Installation supports only the reviewed versions in
[`lib/deployment/distribution.sh`](lib/deployment/distribution.sh). Both release
archives have hardcoded official SHA-256 digests. Downloads use HTTPS and
only the executable is extracted. No source compilation or unpinned installer runs.
Hashes protect the reviewed release selection; upstream provenance/signature
verification is not additionally implemented.

The installer installs signed OS packages, generates bcrypt authentication,
persists an upload-signing secret, installs the service, enables a cleanup timer,
and starts the registry. It checks HTTPS, anonymous denial, authenticated OCI
push/pull and digest integrity, R2 object presence, and the internal storage health.
It prints the requested success block only after these checks pass. Large/concurrent
workloads and BuildKit are separate qualification gates, not install claims.

Repeat installation with identical settings preserves credentials, configuration,
R2 objects, TLS copies, and the selected binary. A partial initial configuration
can recover missing files using its persisted signing secret. Changed input is
rejected; installation is not a credential-rotation interface. Existing UFW state
is retained on repeat installs; verify it after any external firewall changes.
First-install failure leaves local diagnostic state and does not delete remote data.

Installed tools live in `/opt/apollo-registry/deploy`. Host-side settings,
config, auth, TLS, and probe credentials live under `/etc/apollo-registry`, owned
by root with mode 0600 inside a mode 0700 directory. The original input file is
also sensitive: keep it on the registry host or in a controlled secret backup.

## Authentication and client integration

Initial bcrypt Basic authentication protects all registry operations. Anonymous
reads, writes, and deletes receive 401. Manifest/blob DELETE is disabled even for
authenticated clients. Upload cancellation remains available for cleanup.

**Each initial account can read/write every repository.** This is suitable for
trusted infrastructure clients, not untrusted tenant isolation. The auth module
and Distribution auth stanza can be replaced by a scoped token issuer later.
Keep health-probe credentials aligned when replacing authentication.

Pass registry credentials through a client credential store or password stdin,
never through command arguments. A normal BuildKit client's Docker-compatible
credential file contains only registry auth, not R2 keys. For example, with an
operator-created protected password file:

```sh
cat /run/secrets/registry-password | oras login registry.example.com \
  --username registry-client --password-stdin
```

For BuildKit (`buildctl` uses `$DOCKER_CONFIG/config.json`):

```sh
buildctl build --frontend dockerfile.v0 \
  --local context=. --local dockerfile=. \
  --export-cache type=registry,ref=registry.example.com/apollo/build-cache/project,mode=max \
  --import-cache type=registry,ref=registry.example.com/apollo/build-cache/project
```

Provide artifactd an HTTPS registry URL, registry credential reference, and an
artifact repository such as `registry.example.com/apollo/artifacts/project`.
Use normal OCI push/pull; final artifact references should be immutable digests.

Cache and artifact names are logically separate, but share one physical CAS.
Cache is rebuildable; final artifacts require stricter retention. **No automatic
manifest deletion or GC is scheduled.** Before enabling deletion, adopt reviewed
repository-specific retention and registry-aware offline GC. Never run raw R2
prefix/age deletion to implement cache retention. A common blob may serve both.

## Service, health, and logging

```sh
sudo systemctl status apollo-registry.service
sudo /opt/apollo-registry/deploy/healthcheck.sh --json
sudo journalctl --namespace=apollo-registry -u apollo-registry.service
sudo systemctl list-timers apollo-registry-upload-cleanup.timer
```

Health emits JSON in both modes and exits nonzero on any failure. It needs root
on the registry host because it reads private probe/R2 configuration. A fixed tiny
health artifact avoids unbounded health-data growth. It verifies TLS with the OS
trust store; it never disables verification or follows blob redirects.

Distribution runs as a non-login user. systemd credentials give it private
snapshots of config/auth/TLS; the user cannot read the root config directory.
Only `CAP_NET_BIND_SERVICE` is granted for 443. The unit uses a private runtime
and restricted filesystem, kernel, device, privilege, and address-family settings.
Automatic restart is limited to five starts per 120 seconds; fix faults before
`systemctl reset-failed` after a restart storm. Shutdown drains for 60 seconds;
systemd allows 90 seconds before forced termination.

The v3.1.2 HTTP configuration exposes drain timeout, but no general configurable
request/header deadline. This direct-TLS package does not invent unsupported YAML
options. For hostile public workloads, separately qualify a proxy with header/body
and upstream timeouts, plus revised listener/firewall rules before admission.

`supervise.py` forwards shutdown signals and sanitizes logs before journald.
It redacts configured secrets, auth/header fields, and URI/URL queries. Unstructured
upstream messages are suppressed because they can contain YAML or signed requests.
JSON status, operation errors, and storage-health logs remain available. Debug S3
logging and tracing export are disabled. The dedicated journal namespace is limited
to 100 MB persistent / 32 MB runtime and seven-day retention. No client request
bodies or raw BuildKit diagnostic output are printed by the probes.

The Distribution purger removes uploads older than 24 hours, checking hourly after
a randomized startup delay. Its S3 driver does not abort orphan multipart sessions
when deleting upload objects. The companion hourly root oneshot aborts only sessions
older than 25 hours matching `/registry/.../repositories/.../_uploads/<uuid>/data`.
It never deletes completed R2 objects. Uploads lasting a full day must be split or
retried under this policy. Small local state stores firewall ownership only; blobs
and upload state reside in R2. No large local blob volume is provisioned.

## Production qualification

Install an official, pinned `buildctl` and a matching **dedicated** local BuildKit
worker separately. BuildKit is a test tool, not a registry runtime dependency.
Use an isolated worker with no other builds/cache; qualification prunes **all** its
local cache. The scripts require a local Unix socket. No Docker engine is required.

```sh
sudo env \
  BUILDKIT_HOST=unix:///run/buildkit-qualification/buildkitd.sock \
  BUILDKIT_BASE_IMAGE='docker.io/library/busybox@sha256:<reviewed-digest>' \
  QUALIFY_LARGE_MIB=128 \
  /opt/apollo-registry/deploy/qualify.sh \
  --allow-restart --allow-buildkit-prune
```

Choose a real reviewed digest for a Linux image with `/bin/sh`. The example is not
a runnable image pin. Public base-image pull credentials, if required, must be
provisioned separately; the generated qualification credential store contains only
the target registry credentials. Do not qualify during production builds.

The suite checks anonymous push/delete denial, authenticated access, small OCI
push/pull and digests, direct R2 blob presence, restart persistence, 128 MiB large
blobs (64–1024 MiB configurable), four concurrent pulls/pushes, accepted multipart
parts from Distribution visible in R2, a dropped PATCH connection, restart during
an unfinished upload, accepted-chunk resume after restart, retry/resume and final digest, upload cancel,
S3 multipart commit/delete/abort, and real scheduled upload purging.

Only its own upload's `startedat` metadata is aged for the scheduled purge probe.
The suite then runs the same production multipart cleaner against that exact UUID
with a zero age threshold, and verifies no pending session remains. Other uploads
are untouched. A dropped response can leave R2 ahead of the last signed upload
offset; the probe retries a fresh session when Distribution rejects that stale
offset, rather than claiming arbitrary interrupted chunks can always resume. Waiting for the real purger takes up to two hours; there is a
125-minute deadline with progress JSON every 30 seconds.

BuildKit exports a cache after a unique RUN step, verifies the remote manifest,
prunes the isolated worker, verifies no local records remain, imports the remote
cache, and requires that exact RUN step to report `CACHED`. A missing tool, failed
probe, nonempty worker, missing import hit, or storage discrepancy fails the suite;
no required gate is skipped. It prints production PASS only when both suites pass.

Measurements report sampled peak/end registry-process RSS, service CPU consumption,
local deployment/config/state disk bytes, large payload transfer rates, and concurrency.
RSS samples are once per second, not exhaustive peaks. Journal/OS disk and host NIC
throughput need separate monitoring. This is qualification at the recorded workload,
not a promise of fleet scale or a hardware ceiling.

OCI probes are retained under unique `qualification/*` repositories because deletion
is disabled. Record those names/costs; remove through a later reviewed registry
retention process. Direct S3 probes use a unique `qualification-s3/*` key and clean
up only that key/session. Redirects are intentionally disabled, so presigned
redirect qualification is inapplicable.

## Updates, rollback, and certificates

Add a new **reviewed v3 release and both archive digests** to the release table after
checking release notes, storage compatibility, and upstream provenance. A version
outside the table is refused. No arbitrary hash or `latest` override is accepted.

```sh
sudo ./update.sh 3.1.2
```

The command above revalidates the pinned baseline; replace the version only after
extending the table. Updates require a healthy current release, download/verify
before stopping, preserve config/credentials/R2, switch binaries atomically, and
run health + OCI probes. Any restart/probe failure restores the previous binary,
restarts it, and verifies rollback. Both versions remain available in
`/opt/apollo-registry/releases`. No schema migration or remote deletion is run.
Binary rollback cannot undo incompatible upstream storage changes: qualify every
new version against a disposable dedicated bucket before upgrading production.

Certificate updates need a restart to refresh systemd credential snapshots:

```sh
sudo /opt/apollo-registry/deploy/renew-tls.sh
```

This validates the persisted source paths, copies the new certificate/key, restarts,
checks health, and restores the old pair on failure. Configure your ACME client's
successful renewal deploy hook to invoke it; monitor expiry independently. Root-only
key targets behind trusted root-owned symlinks are supported. Ordinary repeat
installation does not rotate a live certificate or credentials.

## Backup, removal, and troubleshooting

R2 contains the durable OCI data. Protect it with an independently tested storage
backup/export policy. Back up `/etc/apollo-registry` (settings, config, bcrypt auth,
TLS, client probe credentials), your certificate renewal configuration, and the
reviewed deployment package/release pins. Encrypt and restrict these backups.
**A VPS backup does not contain the registry blob store.**

```sh
sudo ./uninstall.sh --service-only
sudo ./uninstall.sh --purge-local
```

Service-only removal stops/disables the registry and cleanup timer and removes
units, retaining local binaries/config/state for reinstall. Local purge additionally
requires typing `DELETE LOCAL REGISTRY CONFIG`; it removes the three managed local
directories. Neither path invokes R2 or removes remote data. The non-login account,
UFW rules, and bounded journal configuration remain for explicit operator review.
Remote deletion is always a separate manual storage action.

If health fails: verify DNS/443, certificate chain/expiry, the Basic auth account,
private bucket token scope, endpoint, and the sanitized service journal. The JSON
probe names identify protocol assertion failures; exception bodies stay suppressed.
A 401 before authentication is expected. R2 403 commonly means token/bucket scope;
never solve it by giving R2 credentials to Apollo clients. Failed installation is
not a deployment success. A failed rollback requires operator intervention.

## Development and contributions

Bug reports, documentation fixes, and focused pull requests are welcome. Describe
the expected behavior, observed failure, and the relevant platform or release.
Keep examples reproducible and redact host-specific details and secrets.

Keep changes small and preserve the registry/consumer credential boundary. Avoid
new runtime dependencies when existing Linux tools or the current modules suffice.
Document operational changes alongside their implementation. Release updates must
include reviewed checksums for both supported architectures.

For local checks, use Python 3.11 or newer, PyYAML, ShellCheck, and shfmt. Live R2
probes additionally use boto3. Black and Ruff check Python formatting and imports.
Run these commands from the repository root:

```sh
shellcheck -x -P . ./*.sh lib/*/*.sh
shfmt -d -i 4 -bn ./*.sh lib/*/*.sh
black --check --line-length 100 lib
ruff check --select I,F lib
```

These static checks validate shell correctness, formatting, and Python imports.
They do not verify VPS, HTTPS, R2, restart recovery, or BuildKit behavior. Use the
live qualification suite for deployment evidence.

For deployment changes, include live qualification results from a disposable VPS,
dedicated bucket, and isolated BuildKit worker. State which checks ran and which
remain unverified. Do not commit credentials, certificate keys, settings files,
private logs, or registry data.

Report vulnerabilities privately to the Apollo Deploy maintainers through the
hosting platform's private reporting channel when available. Do not publish
credentials or exploit details in public issues.

## License

Copyright © 2026 Apollo-Deploy. This deployment package is released under the
[MIT license](LICENSE). Contributions to this package are provided under the same
license.

CNCF Distribution and other third-party tools retain their own licenses. The MIT
license covers this repository's deployment code and documentation.

## References

Primary references: [Distribution release](https://github.com/distribution/distribution/releases/tag/v3.1.2),
[configuration](https://distribution.github.io/distribution/about/configuration/),
[S3 driver](https://github.com/distribution/distribution/blob/v3.1.2/docs/content/storage-drivers/s3.md),
[R2 token scope](https://developers.cloudflare.com/r2/api/tokens/),
[R2 S3 compatibility](https://developers.cloudflare.com/r2/api/s3/api/),
[BuildKit registry cache](https://github.com/moby/buildkit#export-cache).
