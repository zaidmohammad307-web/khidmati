# Protection and encryption

## What the code enforces

| Surface | Protection |
| --- | --- |
| Browser → application | TLS 1.2/1.3 at the HTTPS gateway; Secure/HttpOnly/SameSite=Lax session cookie; HSTS, same-origin framing and nosniff headers. Only the HTTPS port is published by the secure profile. |
| Gateway → Odoo | Loopback inside the same network namespace; Odoo binds 127.0.0.1 and its HTTP listener has no external port. This local hop is HTTP, not a separate network TLS channel. |
| Odoo → PostgreSQL | `verify-full` TLS with CA/hostname checks. The secure database rejects non-TLS TCP. No database host port is published. Local database maintenance sockets remain local. |
| Odoo → SAP | HTTPS only, trusted CA verification, bounded timeouts/retries, no redirects, no credential-bearing URLs and same-origin pagination. The VPN is an additional network control. |
| Stored application data | Encrypted host storage is required for PostgreSQL, Odoo filestore/sessions, private working directories and secrets. The app does not turn an unencrypted disk into an encrypted disk. |
| Backups | Random 256-bit key, fresh random nonce per backup, AES-256-GCM ciphertext with authenticated envelope/header. A wrong key, truncated file or tampering fails before database restore. Checksums and path checks then validate the authenticated payload. |
| Accounts | Native Odoo password hashing and TOTP second-factor support. Native 30-minute maximum session inactivity is configured at installation. Enable TOTP for every operational account and protect recovery codes. |
| Roles and company data | Server-side manufacturing role checks and company rules, approval locks, receiver/technician ownership, immutable posted results and private capabilities that cannot be forged with an RPC boolean. Native Odoo ACLs remain in force. |
| Secrets | Generated passwords and files use private owner permissions. SAP credentials are read from a private server file. Connection endpoints are bound to a server-approved list. No credentials are stored in connection records, source archives, frontend state or safe connector diagnostics. Runtime database configuration lives on RAM-backed `/tmp` in the secure profile. |
| Audit | Timestamped protected application workflow audit events. Database/platform administrators remain trusted and can alter the database; this is not an external tamper-proof audit ledger. |

This is implemented protection, not a promise that every machine or every future threat is covered. Disk encryption, trusted client certificates, actual MFA activation, OS updates and recovery-key custody must be verified on the target host. The source bundle contains no working secrets or encrypted business database.

## Encrypt the host storage before first startup

On Linux use a LUKS encrypted mounted volume for `DEEP_ENCRYPTED_DATA_DIR` and the project/secrets. Check the mount's backing device with `findmnt` and `lsblk -f`; an encrypted backing device should have a `crypto_LUKS` parent. Have a qualified administrator prepare a new dedicated volume if one does not already exist. Do not run formatting commands against an existing occupied drive.

On Windows use BitLocker for the drive containing the project, data directory and Docker Desktop virtual disk. Verify protection with `manage-bde -status`. Store its recovery key separately. For macOS use FileVault and keep Docker's disk image and bind directories on the protected volume. If Docker's own data root is outside encrypted storage, logs/container writable layers can remain exposed even if bind data is encrypted.

The secure Compose profile requires an explicit `DEEP_ENCRYPTED_DATA_DIR`; it cannot prove the underlying drive encryption from inside Docker. Do not describe at-rest encryption as verified until the host check has passed.

On Windows, restrict the project secret directory and `.env` with NTFS ACLs before putting real credentials in them. POSIX `chmod` does not enforce Windows ACLs. Give only the deployment owner, required Docker service identity and recovery administrators access; inspect the result with `icacls`. Use the Windows Security tab or an administrator-managed ACL policy so you retain service/recovery access. [Microsoft ACL command reference](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/icacls).

## Certificate trust and renewal

`setup` creates a 10-year private CA and 1-year web/database server certificates with explicit SANs. Host tools verify this CA; devices must trust its public `secrets/ca.crt` before browser access. The private CA signing key belongs in a protected encrypted/offline location. Only public CA certificates are mounted into Odoo.

Use `localhost` for a same-host pilot, or choose the actual VPN DNS name **before** certificate creation by writing it in `.env`. For a company-managed CA, replace the public CA/server certificate/key set with properly signed equivalents whose SANs match `DEEP_HOSTNAME` and `db`. Preserve key permissions. Do not disable certificate verification or install a private key as a trusted certificate.

Setup never replaces an existing key set. For renewal, stop the services, securely archive the old certificate set, obtain a replacement from your company CA or deliberately move the complete TLS set aside and rerun setup. Moving all six TLS files generates a new CA, which must be distributed to clients again. **Keep `backup.key` intact:** certificate renewal must not discard or regenerate the backup key. Start and verify TLS afterward. Review expiry before it reaches seven days.

## Accounts

Create named users under Settings and assign only their operational roles. Use a separate administrator account for administration. Enable two-factor authentication in the user's account security settings using an authenticator; store recovery codes offline. Installing the native TOTP module provides the complete MFA flow but does not automatically enroll users. Only an enrolled user has second-factor protection.

The initial generated login password is a bootstrap credential. After changing it, the old `.env` value is no longer a valid unattended authentication secret. Password-only `verify` should not be used to bypass an enabled second factor. An active session may still be used normally until expiry or revocation.

## Key and backup custody

Copy the 32-byte `secrets/backup.key` to a separate encrypted/offline recovery store. Keep it distinct from backup archives and restrict access to recovery administrators. New backups always encrypt, including if someone chooses a filename ending in `.zip`. Plaintext restore requires `--allow-plain-backup` solely for a deliberate legacy migration. Authentication completes before the decrypted file is published or any database command runs.

Private backup work is placed on the configured encrypted data mount. During encryption/decryption a private temporary plaintext file exists there; host disk encryption protects it at rest. Deleted files cannot be assumed securely erased on SSDs or unencrypted disks. The live DB and filestore use standard Odoo/PostgreSQL formats on encrypted storage so native searches, transactions and attachments work normally.

Encrypt operational exports when sharing or storing them outside the protected host. Screenshots can disclose production data even when the app transport is encrypted. The supplied captures use demonstration records only.

## Deployment checks

Verify the HTTPS certificate on the configured hostname without bypass flags, confirm `/web/database/manager` returns 403, inspect the session cookie flags, and run `manage.py verify` before MFA enrollment. Confirm PostgreSQL reports SSL and refuses non-TLS TCP, then test SAP with the authorized VPN profile. Test an encrypted backup restore to a new database, and verify MFA login, role limits, company isolation and inactive-session expiry with named users.

The code, TLS gateway, cookie/header policy, backup encryption and workflow restrictions were tested locally as recorded in `VERIFICATION.md`. No Docker engine, live VPN/SAP endpoint, host disk encryption or enrolled operator MFA was available in the development environment. The CI workflow additionally exercises the composed services when run on a Docker-capable runner.

Primary references: [Caddy TLS/gateway documentation](https://caddyserver.com/docs/caddyfile/directives/tls), [PostgreSQL TLS](https://www.postgresql.org/docs/16/ssl-tcp.html), [Cryptography AES-GCM primitives](https://cryptography.io/en/stable/hazmat/primitives/symmetric-encryption/).
