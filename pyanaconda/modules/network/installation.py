#
# Copyright (C) 2018 Red Hat, Inc.
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
import shutil

from pyanaconda.core import util
from pyanaconda.modules.common.errors.installation import NetworkInstallationError
from pyanaconda.modules.common.task import Task
from pyanaconda.anaconda_loggers import get_module_logger
from pyanaconda.network import IfcfgFile

log = get_module_logger(__name__)

# TODO:
# handle errors
# fill arguments in install_network_with_task
# set_hostname at the end of the ^^^
# ? get network_devices in the task?
# move ifcfg functionality into a network module submodule
# nmclient module?
# add logging
# remove stuff from pyanaconda/network.py
# update ksdata
# - temporarily at the end
# - then via DeviceConfigurations from UI etc


class NetworkInstallationTask(Task):
    """Installation task for the network configuration."""

    HOSTNAME_CONF_FILE_PATH = "/etc/hostname"
    SYSCONF_NETWORK_FILE_PATH = "/etc/sysconfig/network"
    ANACONDA_SYSCTL_FILE_PATH = "/etc/sysctl.d/anaconda.conf"
    RESOLV_CONF_FILE_PATH = "/etc/resolv.conf"
    NETWORK_SCRIPTS_DIR_PATH = "/etc/sysconfig/network-scripts"
    DEVICE_CONFIG_FILE_PREFIXES = ("ifcfg-", "keys-", "route-")
    DHCLIENT_FILE_TEMPLATE = "/etc/dhcp/dhclient-{}.conf"

    def __init__(self, sysroot, hostname, disable_ipv6, overwrite,
                 onboot_yes_ifcfg_files, network_devices):
        """Create a new task,

        :param sysroot: a path to the root of installed system
        :param fcoe_nics: list of network device names used by FCoE
        :param disable_ipv6: disable ipv6 on target system
        # TODO: update
        """
        super().__init__()
        self._sysroot = sysroot
        self._hostname = hostname
        self._disable_ipv6 = disable_ipv6
        self._overwrite = overwrite
        self._onboot_yes_ifcfg_files = onboot_yes_ifcfg_files
        self._network_devices = network_devices

    @property
    def name(self):
        return "Configure network"

    def run(self):
        self._write_hostname(self._sysroot, self._hostname, self._overwrite)
        self._write_sysconfig_network(self._sysroot, self._overwrite)
        if self._disable_ipv6:
            self._disable_ipv6_on_system(self._sysroot)
        self._copy_device_config_files(self._sysroot)
        self._copy_dhclient_config_files(self._sysroot, self._network_devices)
        self._copy_resolv_conf(self._sysroot, self._overwrite)
        self._set_onboot_to_yes(self._sysroot, self._onboot_yes_ifcfg_files)

    def _write_hostname(self, root, hostname, overwrite):
        """Write static hostname to the target system configuration file.

        :param hostname: static hostname
        :param overwrite: overwrite existing configuration file
        :param root: path to the root of the target system
        """
        return self._write_config_file(root, self.HOSTNAME_CONF_FILE_PATH,
                                       "{}\n".format(hostname),
                                       "Cannot write hostname configuration file",
                                       overwrite)

    def _write_sysconfig_network(self, root, overwrite):
        """Write empty /etc/sysconfig/network target system configuration file.

        :param overwrite: overwrite existing configuration file
        :param root: path to the root of the target system
        """
        return self._write_config_file(root, self.SYSCONF_NETWORK_FILE_PATH,
                                       "# Created by anaconda\n",
                                       "Cannot write {} configuration file".format(
                                           self.SYSCONF_NETWORK_FILE_PATH),
                                       overwrite)

    def _write_config_file(self, path, content, error_msg, overwrite):
        fpath = os.path.normpath(self._sysroot + path)
        if os.path.isfile(fpath) and not overwrite:
            return False
        try:
            with open(fpath, "w") as fobj:
                fobj.write(content)

        except IOError as ioerr:
            msg = "{}: {}".format(error_msg, ioerr.strerror)
            raise NetworkInstallationError(msg)
        return True

    def _disable_ipv6_on_system(self, root):
        """Disable ipv6 on target system."""
        fpath = os.path.normpath(root + self.ANACONDA_SYSCTL_FILE_PATH)
        try:
            with open(fpath, "a") as f:
                f.write("# Anaconda disabling ipv6 (noipv6 option)\n")
                f.write("net.ipv6.conf.all.disable_ipv6=1\n")
                f.write("net.ipv6.conf.default.disable_ipv6=1\n")

        except IOError as ioerr:
            msg = "Cannot disable ipv6 on the system: {}".format(ioerr.strerror)
            raise NetworkInstallationError(msg)
        return True

    def _copy_resolv_conf(self, root, overwrite):
        self._copy_file_to_root(root, self.RESOLV_CONF_FILE_PATH)

    def _copy_file_to_root(self, root, config_file, overwrite=False):
        if not os.path.isfile(config_file):
            return False
        fpath = os.path.normpath(root + config_file)
        if os.path.isfile(fpath) and not overwrite:
            return False
        if not os.path.isdir(os.path.dirname(fpath)):
            util.mkdirChain(os.path.dirname(fpath))
        shutil.copy(config_file, fpath)
        return True

    def _copy_device_config_files(self, root):
        config_files = os.listdir(self.NETWORK_SCRIPTS_DIR_PATH)
        for config_file in config_files:
            if config_file.startswith(self.DEVICE_CONFIG_FILE_PREFIXES):
                self._copy_file_to_root(root, config_file)

    def _copy_dhclient_config_files(self, root, network_devices):
        for device_name in network_devices:
            dhclient_file = self.DHCLIENT_FILE_TEMPLATE.format(device_name)
            self._copy_file_to_root(root, dhclient_file)

    def _set_onboot_to_yes(self, root, ifcfg_files):
        for ifcfg_file in ifcfg_files:
            ifcfg_path = os.path.normpath(root + os.path.join(self.NETWORK_SCRIPTS_DIR_PATH, ifcfg_file))
            ifcfg = IfcfgFile(ifcfg_path)
            ifcfg.read()
            ifcfg.set(('ONBOOT', 'yes'))
            ifcfg.write()
