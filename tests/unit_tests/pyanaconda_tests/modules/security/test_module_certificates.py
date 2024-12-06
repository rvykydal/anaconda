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
import os
import tempfile
import unittest

from textwrap import dedent

from dasbus.typing import *  # pylint: disable=wildcard-import

from pyanaconda.modules.common.constants.objects import CERTIFICATES
from pyanaconda.core.constants import PAYLOAD_TYPE_DNF, PAYLOAD_TYPE_LIVE_OS, \
    INSTALLATION_PHASE_PREINSTALL
from pyanaconda.core.path import join_paths
from pyanaconda.modules.common.structures.security import CertificateData
from pyanaconda.modules.common.errors.installation import SecurityInstallationError
from pyanaconda.modules.security.certificates.certificates import CertificatesModule
from pyanaconda.modules.security.certificates.certificates_interface import CertificatesInterface
from pyanaconda.modules.security.certificates.installation import ImportCertificatesTask, \
    CA_IMPORT_TOOL
from tests.unit_tests.pyanaconda_tests import check_dbus_property, check_task_creation, \
    patch_dbus_publish_object


CERT1_CERT = dedent("""-----BEGIN CERTIFICATE-----
MIIBjTCCATOgAwIBAgIUWR5HO3v/0I80Ne0jQWVZFODuWLEwCgYIKoZIzj0EAwIw
FDESMBAGA1UEAwwJUlZURVNUIENBMB4XDTI0MTEyMDEzNTk1N1oXDTM0MTExODEz
NTk1N1owFDESMBAGA1UEAwwJUlZURVNUIENBMFkwEwYHKoZIzj0CAQYIKoZIzj0D
AQcDQgAELghFKGEgS8+5/2nx50W0xOqTrKc2Jz/rD/jfL0m4z4fkeAslCOkIKv74
0wfBXMngxi+OF/b3Vh8FmokuNBQO5qNjMGEwHQYDVR0OBBYEFOJarl9Xkd13sLzI
mHqv6aESlvuCMB8GA1UdIwQYMBaAFOJarl9Xkd13sLzImHqv6aESlvuCMA8GA1Ud
EwEB/wQFMAMBAf8wDgYDVR0PAQH/BAQDAgEGMAoGCCqGSM49BAMCA0gAMEUCIAet
7nyre42ReoRKoyHWLDsQmQDzoyU3FQdC0cViqOtrAiEAxYIL+XTTp7Xy9RNE4Xg7
yNWXfdraC/AfMM8fqsxlVJM=
-----END CERTIFICATE-----""")

CERT2_CERT = dedent("""-----BEGIN CERTIFICATE-----
MIIBkTCCATegAwIBAgIUN6r4TjFJqP/TS6U25iOGL2Wt/6kwCgYIKoZIzj0EAwIw
FjEUMBIGA1UEAwwLUlZURVNUIDIgQ0EwHhcNMjQxMTIwMTQwMzIxWhcNMzQxMTE4
MTQwMzIxWjAWMRQwEgYDVQQDDAtSVlRFU1QgMiBDQTBZMBMGByqGSM49AgEGCCqG
SM49AwEHA0IABOtXBMEhtcH43dIDHkelODXrSWQQ8PW7oo8lQUEYTNAL1rpWJJDD
1u+bpLe62Z0kzYK0CpeKuXFfwGrzx7eA6vajYzBhMB0GA1UdDgQWBBStV+z7SZSi
YXlamkx+xjm/W1sMSTAfBgNVHSMEGDAWgBStV+z7SZSiYXlamkx+xjm/W1sMSTAP
BgNVHRMBAf8EBTADAQH/MA4GA1UdDwEB/wQEAwIBBjAKBggqhkjOPQQDAgNIADBF
AiEAkQjETC3Yx2xOkA+R0/YR+R+QqpR8p1fd/cGKWFUYxSoCIEuDJcfvPJfFYdzn
CFOCLuymezWz+1rdIXLU1+XStLuB
-----END CERTIFICATE-----""")


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
                'cert': get_variant(Str, CERT1_CERT),
                'filename': get_variant(Str, 'rvtest.pem'),
                'dir': get_variant(Str, '/etc/pki/ca-trust/extracted/pem'),
                'category': get_variant(Str, ''),
            },
            {
                'cert': get_variant(Str, CERT2_CERT),
                'filename': get_variant(Str, 'rvtest2.pem'),
                'dir': get_variant(Str, ''),
                'category': get_variant(Str, 'global'),
            }
        ]
        self._check_dbus_property(
            "Certificates",
            certs_value,
        )

    @patch_dbus_publish_object
    def test_import_with_task_default(self, publisher):
        """Test the ImportWithTask method"""
        task_path = self.certificates_interface.ImportWithTask()
        obj = check_task_creation(task_path, publisher, ImportCertificatesTask)
        assert obj.implementation._sysroot == "/"
        assert obj.implementation._certificates == []

    def _get_2_test_certs(self):
        cert1 = CertificateData()
        cert1.filename = "cert1.pem"
        cert1.cert = CERT1_CERT
        cert1.dir = "/cert/drop/directory1"
        cert2 = CertificateData()
        cert2.filename = "cert2.pem"
        cert2.cert = CERT2_CERT
        cert2.dir = "/cert/drop/directory2"
        return(cert1, cert2)

    @patch_dbus_publish_object
    def test_import_with_task_configured(self, publisher):
        """Test the ImportWithTask method"""
        cert1, cert2 = self._get_2_test_certs()

        self.certificates_interface.Certificates = CertificateData.to_structure_list(
            [cert1, cert2]
        )
        task_path = self.certificates_interface.ImportWithTask()
        obj = check_task_creation(task_path, publisher, ImportCertificatesTask)
        assert obj.implementation._sysroot == "/"
        assert len(obj.implementation._certificates) == 2
        c1, c2 = obj.implementation._certificates
        assert (c1.filename, c1.dir, c1.cert) == (cert1.filename, cert1.dir, cert1.cert)
        assert (c2.filename, c2.dir, c2.cert) == (cert2.filename, cert2.dir, cert2.cert)

    @patch_dbus_publish_object
    def test_install_with_task_default(self, publisher):
        """Test the InstallWithTask method"""
        task_path = self.certificates_interface.InstallWithTask()
        obj = check_task_creation(task_path, publisher, ImportCertificatesTask)
        assert obj.implementation._sysroot == "/mnt/sysroot"
        assert obj.implementation._certificates == []

    @patch_dbus_publish_object
    def test_install_with_task_configured(self, publisher):
        """Test the InstallWithTask method"""
        cert1, cert2 = self._get_2_test_certs()

        self.certificates_interface.Certificates = CertificateData.to_structure_list(
            [cert1, cert2]
        )
        task_path = self.certificates_interface.InstallWithTask()
        obj = check_task_creation(task_path, publisher, ImportCertificatesTask)
        assert obj.implementation._sysroot == "/mnt/sysroot"
        assert len(obj.implementation._certificates) == 2
        c1, c2 = obj.implementation._certificates
        assert (c1.filename, c1.dir, c1.cert) == (cert1.filename, cert1.dir, cert1.cert)
        assert (c2.filename, c2.dir, c2.cert) == (cert2.filename, cert2.dir, cert2.cert)

    @patch_dbus_publish_object
    def test_pre_install_with_task_default(self, publisher):
        """Test the PreInstallWithTask method"""
        task_path = self.certificates_interface.InstallWithTask()
        obj = check_task_creation(task_path, publisher, ImportCertificatesTask)
        assert obj.implementation._sysroot == "/mnt/sysroot"
        assert obj.implementation._certificates == []

    @patch_dbus_publish_object
    def test_pre_install_with_task_configured(self, publisher):
        """Test the PreInstallWithTask method"""
        cert1, cert2 = self._get_2_test_certs()

        self.certificates_interface.Certificates = CertificateData.to_structure_list(
            [cert1, cert2]
        )
        task_path = self.certificates_interface.InstallWithTask()
        obj = check_task_creation(task_path, publisher, ImportCertificatesTask)
        assert obj.implementation._sysroot == "/mnt/sysroot"
        assert len(obj.implementation._certificates) == 2
        c1, c2 = obj.implementation._certificates
        assert (c1.filename, c1.dir, c1.cert) == (cert1.filename, cert1.dir, cert1.cert)
        assert (c2.filename, c2.dir, c2.cert) == (cert2.filename, cert2.dir, cert2.cert)

    def test_import_certificates_task_files(self):
        """Test the ImportCertificatesTask task"""
        cert1, cert2 = self._get_2_test_certs()

        with tempfile.TemporaryDirectory() as sysroot:
            # cert1 has existing dir
            os.makedirs(sysroot+cert1.dir)
            # cert2 has non-existing dir

            ImportCertificatesTask(
                sysroot=sysroot,
                certificates=[cert1, cert2],
            ).run()

            self._check_cert_file(cert1, sysroot)
            self._check_cert_file(cert2, sysroot)

    def _check_cert_file(self, cert, sysroot, missing=False, dir=''):
        cert_dir = dir or cert.dir
        cert_file = sysroot + cert_dir + "/" + cert.filename
        if missing:
            assert os.path.exists(cert_file) is False
        else:
            with open(cert_file) as f:
                # Anaconda adds `\n` to the value when dumping it
                assert f.read() == cert.cert+'\n'

    def test_import_certificates_task_existing_file(self):
        """Test the ImportCertificatesTask task with existing file to be imported"""
        cert1, _ = self._get_2_test_certs()

        with tempfile.TemporaryDirectory() as sysroot:
            # certificate file to be dumped already exists
            os.makedirs(sysroot+cert1.dir)
            cert1_file = sysroot + cert1.dir + "/" + cert1.filename
            open(cert1_file, 'w')

            ImportCertificatesTask(
                sysroot=sysroot,
                certificates=[cert1],
            ).run()

            self._check_cert_file(cert1, sysroot)

    def test_import_certificates_missing_destination(self):
        """Test the ImportCertificatesTask task with missing destination"""
        cert1, _ = self._get_2_test_certs()
        cert1.dir = ''

        with tempfile.TemporaryDirectory() as sysroot:
            with self.assertRaises(SecurityInstallationError):
                ImportCertificatesTask(
                    sysroot=sysroot,
                    certificates=[cert1],
                ).run()

    def test_import_certificates_pre_nondnf_payload(self):
        """Test the ImportCertificatesTask in pre install with non-dnf payload"""
        cert1, cert2 = self._get_2_test_certs()

        with tempfile.TemporaryDirectory() as sysroot:

            # non pre-install phase => install
            ImportCertificatesTask(
                sysroot=sysroot,
                certificates=[cert1],
                payload_type=PAYLOAD_TYPE_LIVE_OS,
            ).run()
            self._check_cert_file(cert1, sysroot)

            # pre-install phase, payload dnf => don't install
            ImportCertificatesTask(
                sysroot=sysroot,
                certificates=[cert2],
                payload_type=PAYLOAD_TYPE_LIVE_OS,
                phase=INSTALLATION_PHASE_PREINSTALL
            ).run()
            self._check_cert_file(cert2, sysroot, missing=True)

            # pre-install phase, payload dnf => install
            ImportCertificatesTask(
                sysroot=sysroot,
                certificates=[cert2],
                payload_type=PAYLOAD_TYPE_DNF,
                phase=INSTALLATION_PHASE_PREINSTALL
            ).run()
            self._check_cert_file(cert2, sysroot)

    @patch('pyanaconda.core.util.execWithRedirect')
    def test_import_certificates_category_unknown(self, execWithRedirect):
        """Test the ImportCertificatesTask for unknown category"""
        cert = CertificateData()
        cert.cert = CERT1_CERT
        cert.filename = "cert.pem"
        cert.category = "unknown"
        cert.dir = "/dir/to/dump/cert"

        with tempfile.TemporaryDirectory() as sysroot:
            ImportCertificatesTask(
                sysroot=sysroot,
                certificates=[cert],
            ).run()
            # There is no exception
            # The certificate is not dumped
            self._check_cert_file(cert, sysroot, missing=True)
            # The tool is not called
            execWithRedirect.assert_not_called()

    @patch('pyanaconda.modules.security.certificates.installation.os.path.lexists')
    @patch('pyanaconda.core.util.execWithRedirect')
    def test_import_certificates_category_global(self, execWithRedirect, mock_lexists):
        """Test the ImportCertificatesTask for category global"""
        cert = CertificateData()
        cert.cert = CERT1_CERT
        cert.filename = "cert.pem"
        cert.category = "global"

        mock_lexists.return_value = True

        with tempfile.TemporaryDirectory() as sysroot:
            ImportCertificatesTask(
                sysroot=sysroot,
                certificates=[cert],
            ).run()
            cert_dir = ImportCertificatesTask.CERT_DIR_CATEGORY_GLOBAL
            # The certificate is dumped into runtime directory
            self._check_cert_file(cert, sysroot,
                                  dir=cert_dir)
            # The import tool is called
            cert_dir = join_paths(cert_dir, cert.filename)
            execWithRedirect.assert_called_once_with(
                CA_IMPORT_TOOL,
                ['anchor', cert_dir],
                root=sysroot,
            )

    @patch('pyanaconda.modules.security.certificates.installation.os.path.lexists')
    @patch('pyanaconda.core.util.execWithRedirect')
    def test_import_certificates_category_global_and_dir(self, execWithRedirect, mock_lexists):
        """Test the ImportCertificatesTask for category global with defined dir"""
        cert = CertificateData()
        cert.cert = CERT1_CERT
        cert.filename = "cert.pem"
        cert.category = "global"
        cert.dir = "/dir/to/dump/cert"

        mock_lexists.return_value = True

        with tempfile.TemporaryDirectory() as sysroot:
            ImportCertificatesTask(
                sysroot=sysroot,
                certificates=[cert],
            ).run()
            # The certificate is dumped accrding to --dir
            self._check_cert_file(cert, sysroot)
            # The import tool is called
            cert_dir = join_paths(cert.dir, cert.filename)
            execWithRedirect.assert_called_once_with(
                CA_IMPORT_TOOL,
                ['anchor', cert_dir],
                root=sysroot,
            )

    @patch('pyanaconda.modules.security.certificates.installation.os.path.lexists')
    @patch('pyanaconda.core.util.execWithRedirect')
    def test_import_certificates_category_global_missing_tool(self, execWithRedirect, mock_lexists):
        """Test the ImportCertificatesTask for category global when tool is missing"""
        cert = CertificateData()
        cert.cert = CERT1_CERT
        cert.filename = "cert.pem"
        cert.category = "global"
        cert.dir = "/dir/to/dump/cert"

        mock_lexists.return_value = False

        # pre-install phase: no exception, cert dumped
        with tempfile.TemporaryDirectory() as sysroot:
            ImportCertificatesTask(
                sysroot=sysroot,
                certificates=[cert],
                phase=INSTALLATION_PHASE_PREINSTALL,
                payload_type=PAYLOAD_TYPE_DNF,
            ).run()
            # The file is dumped
            self._check_cert_file(cert, sysroot)
            # The import tool is not called
            execWithRedirect.assert_not_called()

        # non pre-install phase: exception is raised
        with tempfile.TemporaryDirectory() as sysroot:
            with self.assertRaises(SecurityInstallationError):
                ImportCertificatesTask(
                    sysroot=sysroot,
                    certificates=[cert],
                ).run()

            # The file was dumped
            self._check_cert_file(cert, sysroot)
            # The import tool is not called
            execWithRedirect.assert_not_called()
