#
# Copyright (C) 2024 Red Hat, Inc.
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# the GNU General Public License v.2, or (at your option) any later version.
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY expressed or implied, including the implied warranties of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License for more details.  You should have received a copy of the
# GNU General Public License along with this program; if not, write to the
# Free Software Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.  Any Red Hat trademarks that are incorporated in the
# source code or documentation are not subject to the GNU General Public
# License and may only be used or replicated with the express permission of
# Red Hat, Inc.
#
import os

from pyanaconda.anaconda_loggers import get_module_logger
from pyanaconda.modules.common.task import Task
from pyanaconda.modules.common.errors.installation import SecurityInstallationError
from pyanaconda.core import util
from pyanaconda.core.path import make_directories, join_paths
from pyanaconda.core.constants import PAYLOAD_TYPE_DNF, INSTALLATION_PHASE_PREINSTALL

log = get_module_logger(__name__)

CA_IMPORT_TOOL = "/usr/bin/trust"


class ImportCertificatesTask(Task):
    """Task for importing certificates into a system.

    Dump the certificate into the specified file and directory and/or
    import the certificate using a tool.
    """

    CERT_DIR_CATEGORY_GLOBAL = "/run/install/certificates/category/global"

    def __init__(self, sysroot, certificates, payload_type=None, phase=None):
        """Create a new certificates import task.

        :param str sysroot: a path to the root of the target system
        :param certificates: list of certificate data holders
        :param payload_type: a type of the payload
        :param phase: installation phase - INSTALLATION_PHASE_PREINSTALL or None for any other
        """
        super().__init__()
        self._sysroot = sysroot
        self._certificates = certificates
        self._payload_type = payload_type
        self._phase = phase

    @property
    def name(self):
        return "Import CA certificates"

    def _dump_certificate(self, cert, root, dir=None):
        """Dump the certificate into specified file and directory."""

        cert_dir = dir or cert.dir

        if not cert_dir:
            raise SecurityInstallationError(
                "Certificate destination is missing for {}".format(cert.filename)
            )

        dst_dir = join_paths(root, cert_dir)
        log.debug("Dumping certificate %s into %s.", cert.filename, dst_dir)
        if not os.path.exists(dst_dir):
            log.debug("Path %s for certificate does not exist, creating.", dst_dir)
            make_directories(dst_dir)

        dst = join_paths(dst_dir, cert.filename)

        if os.path.exists(dst):
            log.warning("Certificate file %s already exists, replacing.", dst)

        with open(dst, 'w') as f:
            f.write(cert.cert)
            f.write('\n')

    def _import_certificate(self, root, path):
        """Import the certificate into the global store."""
        log.debug("Importing certificate %s in root %s.", path, root)

        if not os.path.lexists(root + CA_IMPORT_TOOL):
            msg = "{} is missing. Cannot import certificate.".format(CA_IMPORT_TOOL)
            if self._phase != INSTALLATION_PHASE_PREINSTALL:
                raise SecurityInstallationError(msg)
            else:
                log.error(msg)
                return

        util.execWithRedirect(
            CA_IMPORT_TOOL,
            ["anchor", path],
            root=self._sysroot
        )

    def run(self):
        """Import CA certificates.

        Dump the certificates into specified files and directories
        and / or run the import tool depending on the specified category.

        Supported categories:
        global        - imports to the global CA trust store
        """
        if self._phase == INSTALLATION_PHASE_PREINSTALL:
            if self._payload_type != PAYLOAD_TYPE_DNF:
                log.debug("Not importing certificates in pre install for %s payload.",
                          self._payload_type)
                return

        for cert in self._certificates:
            log.debug("Importing certificate %s", cert)

            if not cert.category:
                self._dump_certificate(
                    cert,
                    self._sysroot
                )
            elif cert.category == "global":
                cert_dir = cert.dir or self.CERT_DIR_CATEGORY_GLOBAL
                self._dump_certificate(
                    cert,
                    self._sysroot, dir=cert_dir
                )
                self._import_certificate(
                    self._sysroot,
                    join_paths(cert_dir, cert.filename),
                )
            else:
                log.warning("Invalid category %s, skipping", cert.category)
