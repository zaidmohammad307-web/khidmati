ARG ODOO_IMAGE=odoo:19.0-20260926
FROM ${ODOO_IMAGE}

# Odoo core, its Debian package, and its Python dependencies stay upstream-owned.
# The launcher only creates configuration and invokes the native Odoo CLI.
USER root
COPY --chown=odoo:odoo runtime /opt/drone-runtime
COPY --chown=odoo:odoo config/odoo.conf /opt/drone-runtime/odoo.conf
USER odoo

ENTRYPOINT ["python3", "/opt/drone-runtime/entrypoint.py"]
CMD ["serve"]
