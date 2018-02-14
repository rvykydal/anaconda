#
# Kickstart handler for network and hostname settings
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
from pykickstart.commands.network import F27_Network, F27_NetworkData
from pykickstart.version import F28
from pyanaconda.modules.base_kickstart import KickstartSpecification

DEFAULT_DEVICE_SPECIFICATION = "link"

class Network(F27_Network):
    def parse(self, args):
        hostname_only_command = is_hostname_only_network_args(args)
        # call the overridden command to do it's job first
        retval = F27_Network.parse(self, args)

        if hostname_only_command:
            retval.bootProto = ""

        return retval


class NetworkKickstartSpecification(KickstartSpecification):

    version = F28
    commands = {
        "network": Network,
    }
    data = {
        "NetworkData": F27_NetworkData,
    }


# TODO force moving hostname data into separate line?
def update_network_hostname_data(network_data_list, hostname_data):
    hostname_found = False
    for nd in network_data_list:
        if nd.hostname:
            nd.hostname = hostname_data.hostname
            hostname_found = True
    if not hostname_found:
        network_data_list.append(hostname_data)

def update_network_data_with_default_device(network_data_list, device_specification):
    updated = False
    for nd in network_data_list:
        if not nd.device and not is_hostname_only_network_data(nd):
            nd.device = device_specification
            updated = True
    return updated

def is_hostname_only_network_args(args):
    return (len(args) == 1 and args[0].startswith("--hostname") or
            len(args) == 2 and "--hostname" in args)

def is_hostname_only_network_data(network_data):
    return network_data.bootProto == ""

def default_ks_vlan_interface_name(parent, vlanid):
    return "%s.%s" % (parent, vlanid)
