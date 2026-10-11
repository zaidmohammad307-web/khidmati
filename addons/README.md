# Custom addons

Nine implemented addons are mounted at `/mnt/extra-addons`. Installing
`deep_manufacturing_dashboard` installs the complete dependency graph. See the
root README and ARCHITECTURE.md for responsibilities and dependency boundaries.

Native Odoo remains upstream-owned. Use model/view inheritance, manifests,
server-side role/state validation, company rules and transactional tests.
