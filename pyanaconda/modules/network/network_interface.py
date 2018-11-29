#
# DBus interface for the network module.
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

from pyanaconda.modules.common.constants.services import NETWORK
from pyanaconda.dbus.property import emits_properties_changed
from pyanaconda.dbus.typing import *  # pylint: disable=wildcard-import
from pyanaconda.modules.common.base import KickstartModuleInterface
from pyanaconda.dbus.interface import dbus_interface, dbus_signal


@dbus_interface(NETWORK.interface_name)
class NetworkInterface(KickstartModuleInterface):
    """DBus interface for Network module."""

    def connect_signals(self):
        super().connect_signals()
        self.implementation.hostname_changed.connect(self.changed("Hostname"))
        self.implementation.current_hostname_changed.connect(self.CurrentHostnameChanged)
        self.implementation.connected_changed.connect(self.changed("Connected"))
        self.implementation.disable_ipv6_changed.connect(self.changed("DisableIPv6"))

    @property
    def Hostname(self) -> Str:
        """Hostname the system will use."""
        return self.implementation.hostname

    @emits_properties_changed
    def SetHostname(self, hostname: Str):
        """Set the hostname.

        Sets the hostname of installed system.

        param hostname: a string with a hostname
        """
        self.implementation.set_hostname(hostname)

    @dbus_signal
    def CurrentHostnameChanged(self, hostname: Str):
        """Signal current hostname change."""
        pass

    def GetCurrentHostname(self) -> Str:
        """Current system hostname."""
        return self.implementation.get_current_hostname()

    def SetCurrentHostname(self, hostname: Str):
        """Set current system hostname.

        Sets the hostname of installer environment.

        param: hostname: a string with a hostname
        """
        self.implementation.set_current_hostname(hostname)

    @property
    def Connected(self) -> Bool:
        """Is the system connected to the network?

        The system is considered to be connected if being in one of the states
        NM_STATE_CONNECTED_LOCAL, NM_STATE_CONNECTED_SITE or NM_STATE_CONNECTED_GLOBAL.
        """
        return self.implementation.connected

    def IsConnecting(self) -> Bool:
        """Is NewtorkManager in connecting state?

        The connecting state can indicate that dhcp configuration is
        in progress.

        The state corresponds to NM_STATE_CONNECTING.

        Internal API used for networking initialization and synchronization.
        To be removed after reworking the synchronization.
        """
        return self.implementation.is_connecting()

    @property
    def DisableIPv6(self) -> Bool:
        """Disable IPv6 on target system."""
        return self.implementation.disable_ipv6

    @emits_properties_changed
    def SetDisableIPv6(self, disable: Bool):
        """Set disable IPv6 on target system.

        Disables IPv6 on target system if all the network devices have IPv6
        configuration set to Ignore (kickstart option --noipv6).

        param disable: True if IPv6 on target system should be disabled
        """
        self.implementation.set_disable_ipv6(disable)

    def InstallNetworkWithTask(self, sysroot: Str, fcoe_ifaces: List[Str]) -> ObjPath:
        """Install network with an installation task.

        :param sysroot: a path to the root of the installed system
        :param fcoe_ifaces: list of network interfaces used by FCoE
        :return: a DBus path of an installation task
        """
        return self.implementation.install_network_with_task(sysroot, fcoe_ifaces)
