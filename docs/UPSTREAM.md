# Official-source inspection

Inspected on 2026-10-01. The implementation uses the official Odoo image, rather
than copying server code into this repository. No Enterprise addons are mounted.

| Official source | Verified boundary used in the design |
| --- | --- |
| [Community mrp manifest](https://github.com/odoo/odoo/blob/19.0/addons/mrp/__manifest__.py) | Native dependencies include product, stock and resource; native work-order views exist |
| [mrp_workorder.py](https://github.com/odoo/odoo/blob/19.0/addons/mrp/models/mrp_workorder.py) | Native operation execution, predecessor links, calendar scheduling and expected duration |
| [mrp_bom.py](https://github.com/odoo/odoo/blob/19.0/addons/mrp/models/mrp_bom.py) | Native BOM and operation relationships; dependency/cycle and explosion behavior |
| [mrp_workcenter.py](https://github.com/odoo/odoo/blob/19.0/addons/mrp/models/mrp_workcenter.py) | Native setup/cleanup, capacity, alternatives and calendar-backed availability |
| [CLI server](https://github.com/odoo/odoo/blob/19.0/odoo/cli/server.py) | Native empty-database creation and module registry startup |
| [Configuration parser](https://github.com/odoo/odoo/blob/19.0/odoo/tools/config.py) | Odoo 19 CLI flags, including boolean `--without-demo=True` and `--no-http` |
| [Native session controller](https://github.com/odoo/odoo/blob/19.0/addons/web/controllers/session.py) | Authenticated session smoke-test endpoint uses native jsonrpc route |
| [Official Dockerfile](https://github.com/odoo/docker/blob/master/19.0/Dockerfile) | Official Odoo Debian distribution, user, data directory and addons mount |
| [Official entrypoint](https://github.com/odoo/docker/blob/master/19.0/entrypoint.sh) | Image launch/configuration assumptions inspected; our small launcher invokes native Odoo directly |
| [Official image listing](https://hub.docker.com/_/odoo) | Odoo 19 dated image tag availability |

The source files were fetched and examined. Their checksums are recorded in
`upstream-inspection.json`; this is provenance, not a vendored Odoo codebase.
The 19.0 Git branch can move independently of the dated Docker package. Revalidate
native adapters against the pinned runtime when installing each addon.

## Image lock

Registry index digests were obtained directly from Docker Hub for:

```text
odoo:19.0-20260926@sha256:77bac5cd1e065210828f34883a7f76740b7373d06dd3a5a55d3eeb31ee2f85cd
postgres:16-bookworm@sha256:efedf3595f1d6f415c08568ba171029bf54052e754cc9f030e3f2412b21f3d67
```

These are manifest-list/index digests, allowing the official image's supported
platform variants. They identify the requested versions and avoid an implicit
upgrade from `latest`. The real Compose parser used for validation was v2.39.4.

Further references:

- [Odoo 19 source installation](https://www.odoo.com/documentation/19.0/administration/on_premise/source.html)
- [Odoo 19 ORM API](https://www.odoo.com/documentation/19.0/developer/reference/backend/orm.html)
- [Compose startup dependencies](https://docs.docker.com/compose/how-tos/startup-order/)

Custom planning behavior described elsewhere is this project's architecture
decision. It is not claimed to be an existing native Odoo Community feature.
