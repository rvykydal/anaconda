#
# Kickstart module for network and hostname settings
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

import pydbus
from pyanaconda.dbus import DBus
from pyanaconda.dbus.constants import MODULE_NETWORK_NAME, MODULE_NETWORK_PATH
from pyanaconda.core.signal import Signal
from pyanaconda.modules.base import KickstartModule
from pyanaconda.modules.network.network_interface import NetworkInterface
from pyanaconda.modules.network.network_kickstart import NetworkKickstartSpecification
from pyanaconda.modules.network.device_configuration import DeviceConfigurations
from pyanaconda.modules.network.nm_client import nm_client

import gi
gi.require_version("NM", "1.0")
from gi.repository import NM

HOSTNAME_SERVICE = "org.freedesktop.hostname1"
HOSTNAME_PATH = "/org/freedesktop/hostname1"

from pyanaconda import anaconda_logging
log = anaconda_logging.get_dbus_module_logger(__name__)

# TODO abstract out NetworkManager/client

class NetworkModule(KickstartModule):
    """The Network module."""

    def __init__(self):
        super().__init__()

        self.hostname_changed = Signal()
        self._hostname = "localhost.localdomain"
        self.current_hostname_changed = Signal()
        # TODO fallback solution (no hostnamed) ?
        self._hostname_service_proxy = pydbus.SystemBus().get(HOSTNAME_SERVICE, HOSTNAME_PATH)
        self._hostname_service_proxy.PropertiesChanged.connect(self._hostname_service_properties_changed)

        self.connected_changed = Signal()
        # TODO fallback solution (no NM, limited environment)
        # TODO use Gio/GNetworkMonitor ?
        self.nm_client = nm_client
        self.nm_client.connect("notify::%s" % NM.CLIENT_STATE, self._nm_state_changed)
        initial_nm_state = self.nm_client.get_state()
        self.set_connected(self._nm_state_connected(initial_nm_state))

        self._device_configurations = None

    def publish(self):
        """Publish the module."""
        DBus.publish_object(NetworkInterface(self), MODULE_NETWORK_PATH)
        DBus.register_service(MODULE_NETWORK_NAME)

    @property
    def kickstart_specification(self):
        """Return the kickstart specififcation."""
        return NetworkKickstartSpecification

    def process_kickstart(self, data):
        """Process the kickstart data."""
        if data.network.hostname:
            self.set_hostname(data.network.hostname)

    def generate_kickstart(self):
        """Retrurn the kickstart string."""
        data = self.get_kickstart_data()
        data.network.network = []
        # hostname
        hostname_data = data.NetworkData(hostname=self.hostname, bootProto="")
        data.network.network.append(hostname_data)
        return str(data)

    @property
    def hostname(self):
        """Return the hostname."""
        return self._hostname

    def set_hostname(self, hostname):
        """Set the hostname."""
        self._hostname = hostname
        self.hostname_changed.emit()
        log.debug("Hostname is set to %s", hostname)

    def _hostname_service_properties_changed(self, interface, changed, invalidated):
        if interface == "org.freedesktop.hostname1" and "Hostname" in changed:
            hostname = changed["Hostname"]
            self.current_hostname_changed.emit(hostname)
            log.debug("Current hostname changed to %s", hostname)

    def get_current_hostname(self):
        """Return current hostname of the system."""
        return self._hostname_service_proxy.Hostname

    def set_current_hostname(self, hostname):
        """Set current system hostname."""
        self._hostname_service_proxy.SetHostname(hostname, False)
        log.debug("Current hostname is set to %s", hostname)

    @property
    def connected(self):
        """Is the system connected to the network?"""
        return self._connected

    def set_connected(self, connected):
        """Set network connectivity status."""
        self._connected = connected
        self.connected_changed.emit()
        log.debug("Connected to network: %s", connected)

    def is_connecting(self):
        """Is NM in connecting state?"""
        return self.nm_client.get_state() == NM.State.CONNECTING

    @staticmethod
    def _nm_state_connected(state):
        return state in (NM.State.CONNECTED_LOCAL, NM.State.CONNECTED_SITE, NM.State.CONNECTED_GLOBAL)

    def _nm_state_changed(self, *args):
        state = self.nm_client.get_state()
        log.debug("NeworkManager state changed to %s", state)
        self.set_connected(self._nm_state_connected(state))

    def create_device_configurations(self):
        # TODO use get_all_devices?, virtual configs? test this
        # TODO: idempotent?
        self._device_configurations = DeviceConfigurations(self.nm_client)
        self._device_configurations.configuration_changed.connect(self.device_configurations_changed_cb)
        self._device_configurations.reload()
        self._device_configurations.connect()

    def device_configurations_changed_cb(self, old_dev_cfg, new_dev_cfg):
        log.debug("Configuration changed: %s -> %s", old_dev_cfg, new_dev_cfg)
        log.debug("%s", self._device_configurations)
