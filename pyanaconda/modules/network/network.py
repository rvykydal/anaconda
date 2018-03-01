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
from pyanaconda.modules.network.network_interface import NetworkInterface, device_configuration_to_dbus
from pyanaconda.modules.network.network_kickstart import NetworkKickstartSpecification, \
    update_network_hostname_data, update_network_data_with_default_device, DEFAULT_DEVICE_SPECIFICATION
from pyanaconda.modules.network.device_configuration import DeviceConfigurations, supported_device_types
from pyanaconda.modules.network.nm_client import nm_client, get_device_name_from_network_data, \
    add_connection_from_ksdata, update_connection_from_ksdata, ensure_active_connection_for_device
from pyanaconda.modules.network.ifcfg import find_ifcfg_file_of_device

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

        self._original_network_data = []
        self._device_configurations = None
        self.configuration_changed = Signal()

        self._default_device_specification = DEFAULT_DEVICE_SPECIFICATION
        self._bootif = None

    def publish(self):
        """Publish the module."""
        DBus.publish_object(NetworkInterface(self), MODULE_NETWORK_PATH)
        DBus.register_service(MODULE_NETWORK_NAME)

    @property
    def kickstart_specification(self):
        """Return the kickstart specififcation."""
        return NetworkKickstartSpecification

    @property
    def default_device_specification(self):
        """Get the default specification for missing kickstart --device option."""
        return self._default_device_specification

    @default_device_specification.setter
    def default_device_specification(self, specification):
        """Set the default specification for missing kickstart --device option.

        :param specifiacation: device specification accepted by network --device option
        :type specification: str
        """
        self._default_device_specification = specification
        log.debug("default kickstart device specification set to %s", specification)

    def process_kickstart(self, data):
        """Process the kickstart data."""
        log.debug("kickstart to be processed:\n%s", str(data))

        # Handle default value for --device
        spec = self.default_device_specification
        if update_network_data_with_default_device(data.network.network, spec):
            log.debug("used '%s' for missing network --device options", spec)

        self._original_network_data = data.network.network
        if data.network.hostname:
            self.set_hostname(data.network.hostname)

        log.debug("processed kickstart:\n%s", str(data))

    def generate_kickstart(self):
        """Retrurn the kickstart string."""

        data = self.get_kickstart_data()
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

    def get_device_configurations(self):
        if not self._device_configurations:
            return []
        return [dev_cfg.get_values() for dev_cfg in self._device_configurations.get_all()]

    def device_configurations_changed_cb(self, old_dev_cfg, new_dev_cfg):
        log.debug("Configuration changed: %s -> %s", old_dev_cfg, new_dev_cfg)
        log.debug("%s", self._device_configurations)
        self.configuration_changed.emit([(device_configuration_to_dbus(old_dev_cfg),
                                          device_configuration_to_dbus(new_dev_cfg))])

    def consolidate_initramfs_connections(self):
        """Ensure devices configured in initramfs have no more than one NM connection.

        In case of multiple connections for device having ifcfg configuration from
        boot options, the connection should correspond to the ifcfg file.
        NetworkManager can be generating additional in-memory connection in case it
        fails to match device configuration to the ifcfg (#1433891).  By
        reactivating the device with ifcfg connection the generated in-memory
        connection will be deleted by NM.

        Don't enforce on slave devices for which having multiple connections can be
        valid (slave connection, regular device connection).
        """
        consolidated_devices = []

        for device in self.nm_client.get_devices():
            cons = device.get_available_connections()
            count = len(cons)
            iface = device.get_iface()

            if count < 2:
                continue

            # Ignore devices which are slaves
            for con in cons:
                if con.get_setting_connection().get_master():
                    log.debug("consolidate %d initramfs connections for %s: it is OK, device is a slave",
                              count, iface)
                    continue

            ifcfg_file = find_ifcfg_file_of_device(iface)
            if not ifcfg_file:
                log.error("consolidate %d initramfs connections for %s: no ifcfg file",
                          count, iface)
                continue
            else:
                # Handle only ifcfgs created from boot options in initramfs
                # (Kickstart based ifcfgs are handled when applying kickstart)
                if ifcfg_file.is_from_kickstart:
                    continue

            log.debug("consolidate %d initramfs connections for %s: ensure active ifcfg connection",
                      count, iface)

            ensure_active_connection_for_device(ifcfg_file.uuid, iface, only_replace=True)

            consolidated_devices.append(iface)

        return consolidated_devices

    def get_supported_devices(self):
        """Get names of existing supported devices on the system."""
        return [device.get_iface() for device in self.nm_client.get_devices()
                if device.get_device_type() in supported_device_types]

    @property
    def bootif(self):
        """Get the value of kickstart --bootif option."""
        return self._bootif

    @bootif.setter
    def bootif(self, specification):
        """Set the value of kickstart --bootif option.

        :param specifiacation: mac address specified in kickstart --bootif option
        :type specification: str
        """
        self._bootif = specification
        log.debug("bootif device specification is set to %s", specification)

    def apply_kickstart(self):
        """Apply kickstart configuration which has not already been applied.

        * Activate configurations created in initramfs if --activate is True.
        * Create configurations for %pre kickstart commands and activate eventually.

        :returns: list of devices to which kickstart configuration was applied
        """

        applied_devices = []

        if not self._original_network_data:
            log.debug("No kickstart data to apply.")
            return []

        for network_data in self._original_network_data:

            # Wireless is not supported
            if network_data.essid:
                continue

            supported_devices = self.get_supported_devices()
            device_name = get_device_name_from_network_data(network_data,
                                                            supported_devices,
                                                            self._bootif)
            if not device_name:
                log.warning("apply kickstart: --device %s not found", network_data.device)

            ifcfg_file = find_ifcfg_file_of_device(device_name)
            if ifcfg_file and ifcfg_file.is_from_kickstart:
                if network_data.activate:
                    if ensure_active_connection_for_device(ifcfg_file.uuid, device_name):
                        applied_devices.append(device_name)
                continue

            # If there is no kickstart ifcfg from initramfs the command was added
            # in %pre section after switch root, so apply it now
            applied_devices.append(device_name)
            if ifcfg_file:
                # if the device was already configured in initramfs update the settings
                con_uuid = ifcfg_file.uuid
                log.debug("pre kickstart - updating settings %s of device %s",
                          con_uuid, device_name)
                update_connection_from_ksdata(con_uuid, network_data, device_name=device_name)
                if network_data.activate:
                    connection = self.nm_client.get_connection_by_uuid(con_uuid)
                    device = self.nm_client.get_device_by_iface(device_name)
                    self.nm_client.activate_connection_async(connection, device, None, None)
                    log.debug("pre kickstart - activating connection %s with device %s",
                              con_uuid, device_name)
            else:
                log.debug("pre kickstart - adding connection for %s", device_name)
                add_connection_from_ksdata(network_data, device_name,
                                           activate=network_data.activate)

        return applied_devices

    def set_onboot_from_kickstart(self):
        """Update ifcfg ONBOOT values according to kickstart configuration.

        This is needed because when applying kickstart we can't set the autoconnect
        setting of connection to prevent activating the connection immediately.

        :return: list of devices for which ONBOOT was updated
        :rtype: list(str)
        """
