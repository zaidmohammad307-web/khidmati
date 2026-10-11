# Repository structure and history

The source is organized into 16 Odoo add-ons with dependencies declared in each `__manifest__.py`. Each add-on keeps models, application services, transient wizards, ACL/rules, data, views, frontend assets and native tests in its own directory. Shared private workflow/audit helpers live in `deep_core`; native Odoo continues to own stock, MRP, identity and transactions.

`runtime` only bootstraps/configures the pinned upstream Odoo CLI and database role. `scripts/lib` handles host setup, lifecycle, authenticated encryption, PKI and consistent backup/restore. No live credentials, key files, downloaded upstream binaries, runtime databases, developer virtual environments or scratch test harnesses are included.

`source-history.bundle` carries the Git history. Use `git clone source-history.bundle drone-odoo-history`, then inspect `git log`. The bundle is produced after the final source commit and is intentionally outside Git tracking to avoid recursively storing itself.

See `FEATURES.md` for ownership, `VERIFICATION.md` for test evidence and `UPSTREAM.md` for the pinned runtime origin.
