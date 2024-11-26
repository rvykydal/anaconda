#
# Copyright (C) 2024  Red Hat, Inc.
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
# Red Hat Author(s): Radek Vykydal <rvykydal@redhat.com>
#
import unittest

from dasbus.typing import *  # pylint: disable=wildcard-import

from pyanaconda.modules.common.constants.objects import CERTIFICATES
from pyanaconda.modules.common.structures.security import CertificateData
from pyanaconda.modules.security.certificates.certificates import CertificatesModule
from pyanaconda.modules.security.certificates.certificates_interface import CertificatesInterface
from tests.unit_tests.pyanaconda_tests import check_dbus_property


class CertificatesInterfaceTestCase(unittest.TestCase):
    """Test DBus interface of the Certificates module."""

    def setUp(self):
        """Set up the module."""
        self.certificates_module = CertificatesModule()
        self.certificates_interface = CertificatesInterface(self.certificates_module)

    def _check_dbus_property(self, *args, **kwargs):
        check_dbus_property(
            CERTIFICATES,
            self.certificates_interface,
            *args, **kwargs
        )

    def test_certificates_property(self):
        """Test the certificates property."""
        certs_value = [
            {
                'cert': get_variant(Str, '-----BEGIN CERTIFICATE-----\nMIIDazCCAlOgAwIBAgIJAJzQz1Zz1Zz1MA0GCSqGSIb3DQEBCwUAMIGVMQswCQYD\n-----END CERTIFICATE-----'),
                'name': get_variant(Str, 'rvtest.pem'),
                'path': get_variant(Str, '/etc/pki/ca-trust/extracted/pem')
            },
            {
                'cert': get_variant(Str, '-----BEGIN CERTIFICATE-----\nXIIBkTCCATegAwIBAgIUN6r4TjFJqP/TS6U25iOGL2Wt/6kwCgYIKoZIzj0EAwIw\n-----END CERTIFICATE-----'),
                'name': get_variant(Str, 'rvtest2.pem'),
                'path': get_variant(Str, '')
            }
        ]
        self._check_dbus_property(
            "Certificates",
            certs_value,
        )
