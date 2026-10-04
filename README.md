# registry-deploy

A small OCI registry deployment package from **Apollo Deploy**, released under
[MIT](LICENSE).

Run **CNCF Distribution 3.1.2** on a Linux VPS with **Cloudflare R2** for durable
storage. Includes HTTPS, bcrypt authentication, hardened systemd supervision,
health checks, and updates with rollback.

```text
BuildKit / OCI clients → HTTPS → Distribution → Cloudflare R2
```

Use it for remote BuildKit cache and OCI artifacts. Apollo clients receive registry
credentials only; R2 credentials stay on the registry server. The package runs
independently of Apollo services and requires no Docker engine.

## Get started

Prepare a dedicated Debian 12/13 or Ubuntu 24.04 VPS with systemd and an x86_64 or
arm64 CPU. Start with 2 vCPU, 2 GB RAM, and 20–40 GB SSD.

Before installing, you need:

- DNS pointing to the VPS, using a DNS-only Cloudflare record.
- A private R2 bucket and a bucket-scoped Object Read & Write token.
- A valid full-chain TLS certificate and root-owned `0600` private key.
- Root access, a management CIDR for SSH, and a fresh UFW configuration.

See the [operator guide](docs/operations.md#requirements-and-dns) for preparation.
Certificate issuance uses your existing CA or ACME setup.

On the VPS, from the repository root:

```sh
sudo install -m 0600 templates/env.example /root/registry-settings.json
sudoedit /root/registry-settings.json
sudo --preserve-env=SSH_CONNECTION ./install.sh /root/registry-settings.json
```

The [settings template](templates/env.example) is JSON. Replace every placeholder,
including the TLS paths, SSH settings, and registry password. Keep the file private.
Repeat installation with identical settings preserves existing credentials and data.

## Use the registry

Authenticate through your OCI client's credential store. The initial account can
read and write every repository; use it only with trusted clients.

BuildKit cache settings:

```text
export: type=registry,ref=registry.example.com/apollo/build-cache/project,mode=max
import: type=registry,ref=registry.example.com/apollo/build-cache/project
```

Store final artifacts in `registry.example.com/apollo/artifacts/project` and consume
immutable digest references. Cache and artifacts need separate retention policies.

See [client integration](docs/operations.md#authentication-and-client-integration)
for authentication and BuildKit examples.

## Operate

```sh
sudo /opt/apollo-registry/deploy/healthcheck.sh --json
```

Run the [live qualification suite](docs/operations.md#production-qualification)
before production use. Live VPS/R2/BuildKit qualification has not been recorded for
this package. Qualification restarts the registry and prunes a dedicated BuildKit
worker's local cache.

The [operator guide](docs/operations.md) covers updates, rollback, TLS renewal,
logs, backups, removal, and troubleshooting. Uninstall never deletes R2 data.

## Contribute

Focused fixes and documentation improvements are welcome. Keep changes small,
preserve the credential boundary, and include the checks you ran. See
[development checks](docs/operations.md#development-and-contributions).

Report vulnerabilities privately to Apollo Deploy maintainers through the hosting
platform's private reporting channel when available. Never include secrets in
public issues.

## License

Copyright © 2026 Apollo-Deploy. [MIT licensed](LICENSE). Third-party tools retain
their own licenses.
