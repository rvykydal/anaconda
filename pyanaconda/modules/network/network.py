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

from pyanaconda.dbus import DBus, SystemBus
from pyanaconda.dbus.constants import MODULE_NETWORK_NAME, MODULE_NETWORK_PATH
from pyanaconda.core.signal import Signal
from pyanaconda.modules.common.base import KickstartModule
from pyanaconda.modules.network.network_interface import NetworkInterface
from pyanaconda.modules.network.kickstart import NetworkKickstartSpecification, \
    update_network_hostname_data
from pyanaconda.modules.network.device_configuration import DeviceConfigurations
from pyanaconda.modules.network.nm_client import nm_client

import gi
gi.require_version("NM", "1.0")
from gi.repository import NM

HOSTNAME_SERVICE = "org.freedesktop.hostname1"
HOSTNAME_PATH = "/org/freedesktop/hostname1"
HOSTNAME_INTERFACE = "org.freedesktop.hostname1"

from pyanaconda.anaconda_loggers import get_module_logger
log = get_module_logger(__name__)


# TODO abstract out NetworkManager/client

class NetworkModule(KickstartModule):
    """The Network module."""

    def __init__(self):
        super().__init__()

        self.hostname_changed = Signal()
        self._hostname = "localhost.localdomain"

        self.current_hostname_changed = Signal()
        self._hostname_service = self._get_hostname_service_observer()

        self.connected_changed = Signal()
        # TODO fallback solution (no NM, limited environment)
        # TODO use Gio/GNetworkMonitor ?
        self.nm_client = nm_client
        self.nm_client.connect("notify::%s" % NM.CLIENT_STATE, self._nm_state_changed)
        initial_nm_state = self.nm_client.get_state()
        self.set_connected(self._nm_state_connected(initial_nm_state))

        self._original_network_data = []
        self._device_configurations = None

    def _get_hostname_service_observer(self):
        """Get an observer of the hostname service."""
        service = SystemBus.get_cached_observer(
            HOSTNAME_SERVICE, HOSTNAME_PATH, [HOSTNAME_INTERFACE])

        service.cached_properties_changed.connect(
            self._hostname_service_properties_changed)

        service.connect_once_available()
        return service

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
        log.debug("kickstart to be processed:\n%s", str(data))

        self._original_network_data = data.network.network
        if data.network.hostname:
            self.set_hostname(data.network.hostname)

        log.debug("processed kickstart:\n%s", str(data))

    def generate_kickstart(self):
        """Retrurn the kickstart string."""

        data = self.get_kickstart_handler()
        if self._device_configurations:
            device_data = self._device_configurations.get_kickstart_data(data.NetworkData)
            log.debug("using device configurations to generate kickstart")
        else:
            device_data = self._original_network_data
            log.debug("using original kickstart data to generate kickstart")
        data.network.network = device_data

        hostname_data = data.NetworkData(hostname=self.hostname, bootProto="")
        update_network_hostname_data(data.network.network, hostname_data)

        log.debug("generated kickstart:\n%s", str(data))
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

    def _hostname_service_properties_changed(self, observer, changed, invalid):
        if "Hostname" in changed:
            hostname = self._hostname_service.cache.Hostname
            self.current_hostname_changed.emit(hostname)
            log.debug("Current hostname changed to %s", hostname)

    def get_current_hostname(self):
        """Return current hostname of the system."""
        if self._hostname_service.is_service_available:
            return self._hostname_service.proxy.Hostname

        log.debug("Current hostname cannot be get.")
        return ""

    def set_current_hostname(self, hostname):
        """Set current system hostname."""
        if not self._hostname_service.is_service_available:
            log.debug("Current hostname cannot be set.")
            return

        self._hostname_service.proxy.SetHostname(hostname, False)
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
