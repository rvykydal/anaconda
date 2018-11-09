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
#  Author(s):  Vendula Poncova <vponcova@redhat.com>
#
import os
from abc import ABC
from enum import Enum

from pyanaconda.core.constants import ANACONDA_CONFIG_TMP, ANACONDA_CONFIG_DIR
from pyanaconda.core.configuration.base import create_parser, read_config, write_config, \
    get_option, set_option

__all__ = ["conf", "AnacondaConfiguration"]


class Section(ABC):
    """A base class for representation of a configuration section."""

    def __init__(self, section_name, parser):
        self._section_name = section_name
        self._parser = parser

    def _get_option(self, option_name, converter=None):
        """Get a converted value of the option.

        :param option_name: an option name
        :param converter: a function or None
        :return: a converted value
        """
        return get_option(self._parser, self._section_name, option_name, converter)

    def _set_option(self, option_name, value):
        """Set the option.

        :param option_name: an option name
        :param value: an option value
        """
        set_option(self._parser, self._section_name, option_name, value)


class AnacondaSection(Section):
    """The Anaconda section."""

    @property
    def debug(self):
        """Run Anaconda in the debugging mode."""
        return self._get_option("debug", bool)

    @property
    def addons_enabled(self):
        """Enable Anaconda addons."""
        return self._get_option("addons_enabled", bool)

    @property
    def kickstart_modules(self):
        """List of enabled kickstart modules."""
        return self._get_option("kickstart_modules").split()


class SystemType(Enum):
    """The type of the installation system."""
    BOOT_ISO = "BOOT_ISO"
    LIVE_OS = "LIVE_OS"
    UNKNOWN = "UNKNOWN"


class InstallationSystem(Section):
    """The Installation System section."""

    @property
    def _type(self):
        """Type of the installation system.

        FIXME: This is a temporary solution.
        """
        return self._get_option("type", SystemType)

    @property
    def _is_boot_iso(self):
        """Are we running in the boot.iso?"""
        return self._type is SystemType.BOOT_ISO

    @property
    def _is_live_os(self):
        """Are we running in the live OS?"""
        return self._type is SystemType.LIVE_OS

    @property
    def _is_unknown(self):
        """Are we running in the unknown OS?"""
        return self._type is SystemType.UNKNOWN

    @property
    def can_reboot(self):
        """Can we reboot the system?"""
        return self._is_boot_iso

    @property
    def can_switch_tty(self):
        """Can we change the foreground virtual terminal?"""
        return self._is_boot_iso

    @property
    def can_audit(self):
        """Can we run the audit daemon?"""
        return self._is_boot_iso

    @property
    def can_adjust_time(self):
        """Can we change the time?"""
        return self._is_boot_iso

    @property
    def can_adjust_time_live(self):
        """Can we change the time?

        FIXME: Conflict with can_adjust_time.
        """
        return self._is_boot_iso or self._is_live_os

    @property
    def can_synchronize_time(self):
        """Can we run the NTP daemon?"""
        return self._is_boot_iso

    @property
    def can_localize(self):
        """Can we change the localization?"""
        return self._is_boot_iso

    @property
    def can_localize_live(self):
        """Can we change the localization?

        FIXME: Conflict with can_localize.
        """
        return self._is_boot_iso or self._is_live_os

    @property
    def can_configure_syslog(self):
        """Can we modify syslog?

        FIXME: This rule is weird.
        """
        return self._is_boot_iso

    @property
    def can_modify_nvram(self):
        """Can we modify firmware NVRAM variables?

        FIXME: Isn't this target specific?
        """
        return self._is_boot_iso or self._is_live_os

    @property
    def can_disable_swap(self):
        """Can we call swapoff?

        FIXME: This should be safe to do on the boot.iso.
        FIXME: This rule seems to be too specific.
        """
        return self._is_live_os

    @property
    def can_copy_resolve_conf(self):
        """Can we copy /etc/resolv.conf to the target system?

        FIXME: Isn't this rule too specific?
        """
        return self._is_boot_iso

    @property
    def can_change_hostname(self):
        """Can we change the hostname?"""
        return self._is_boot_iso

    @property
    def can_change_hostname_live(self):
        """Can we change the hostname?

        FIXME: Conflict with can_change_hostname.
        """
        return self._is_boot_iso or self._is_live_os

    @property
    def can_configure_network(self):
        """Can we configure the network?"""
        return self._is_boot_iso

    @property
    def can_require_network_connection(self):
        """Can the system require network connection?"""
        return self._is_boot_iso

    @property
    def provides_user_interaction_config(self):
        """Can we read /etc/sysconfig/anaconda?

        FIXME: Is the name of this rule correct?
        FIXME: Isn't this target specific?
        """
        return self._is_boot_iso or self._is_live_os

    @property
    def provides_web_browser(self):
        """Can we redirect users to web pages?"""
        return self._is_live_os

    @property
    def can_write_network_config(self):
        """Should we pass network config to installed system?"""
        return self._is_boot_iso or self._is_live_os

class ServicesSection(Section):
    """The Services section."""

    @property
    def selinux(self):
        """Enable SELinux usage in the installed system.

        Valid values:

         -1  The value is not set.
          0  SELinux is disabled (permissive).
          1  SELinux is enabled (enforcing).
        """
        value = self._get_option("selinux", int)

        if value not in (-1, 0, 1):
            raise ValueError("Invalid value: {}".format(value))

        return value


class StorageSection(Section):
    """The Storage section."""

    @property
    def dmraid(self):
        """Enable dmraid usage during the installation."""
        return self._get_option("dmraid", bool)

    @property
    def ibft(self):
        """Enable iBFT usage during the installation."""
        return self._get_option("ibft", bool)

    @property
    def gpt(self):
        """Do you prefer creation of GPT disk labels?"""
        return self._get_option("gpt", bool)

    @property
    def multipath_friendly_names(self):
        """Use user friendly names for multipath devices.

        Tell multipathd to use user friendly names when naming devices
        during the installation.
        """
        return self._get_option("multipath_friendly_names", bool)


class AnacondaConfiguration(object):
    """Representation of the Anaconda configuration."""

    @classmethod
    def from_defaults(cls):
        """Get the default Anaconda configuration.

        Read the current configuration from the temporary config file.
        Or load the configuration from the configuration directory.

        :return: an instance of AnacondaConfiguration
        """
        config = cls()

        # Read the temporary configuration file.
        config_path = os.environ.get("ANACONDA_CONFIG_TMP", ANACONDA_CONFIG_TMP)
        if config_path and os.path.exists(config_path):
            config.read(config_path)

        # Or use the defaults if it doesn't exist.
        else:
            config_path = os.path.join(ANACONDA_CONFIG_DIR, "anaconda.conf")
            config.read(config_path)

            config_dir = os.path.join(ANACONDA_CONFIG_DIR, "conf.d")
            for config_path in sorted(os.listdir(config_dir)):
                config.read(os.path.join(config_dir, config_path))

        # Validate the configuration.
        config.validate()
        return config

    def __init__(self):
        """Initialize the configuration."""
        self._sources = []
        self._parser = create_parser()

        self._anaconda = AnacondaSection("Anaconda", self.get_parser())
        self._system = InstallationSystem("Installation System", self.get_parser())
        self._storage = StorageSection("Storage", self.get_parser())
        self._services = ServicesSection("Services", self.get_parser())

    @property
    def anaconda(self):
        """The Anaconda section."""
        return self._anaconda

    @property
    def system(self):
        """The Installation System section."""
        return self._system

    @property
    def storage(self):
        """The Storage section."""
        return self._storage

    @property
    def services(self):
        """The Services section."""
        return self._services

    def get_parser(self):
        """Get the configuration parser.

        :return: instance of the ConfigParser
        """
        return self._parser

    def get_sources(self):
        """Get the configuration sources.

        :return: a list of file names
        """
        return self._sources

    def read(self, path):
        """Read a configuration file.

        :param path: a path to the file
        """
        read_config(self._parser, path)
        self._sources.append(path)

    def write(self, path):
        """Write a configuration file.

        :param path: a path to the file
        """
        write_config(self._parser, path)

    def validate(self):
        """Validate the configuration."""
        self._validate_members(self)

    def _validate_members(self, obj):
        """Validate members of the object.

        The main goal of this method is to check if all sections
        are accessible and all options readable and convertible.

        The implementation actually tries to access all public
        members of the given object and its sections.
        """
        for member_name in dir(obj):

            # Skip private members.
            if member_name.startswith("_"):
                continue

            # Try to get the value of the member.
            value = getattr(obj, member_name)

            # Validate the sections of the configuration object.
            if isinstance(obj, AnacondaConfiguration) and isinstance(value, Section):
                self._validate_members(value)

    def set_from_opts(self, opts):
        """Set the configuration from the Anaconda cmdline options.

        This code is too related to the Anaconda cmdline options, so it shouldn't
        be part of this class. We should find a better, more universal, way to change
        the Anaconda configuration.

        FIXME: This is a temporary solution.

        :param opts: a namespace of options
        """
        self.storage._set_option("dmraid", opts.dmraid)
        self.storage._set_option("ibft", opts.ibft)
        self.storage._set_option("gpt", opts.gpt)
        self.storage._set_option("multipath_friendly_names", opts.multipath_friendly_names)

        # Set the type of the installation system.
        if opts.liveinst:
            self.system._set_option("type", SystemType.LIVE_OS.value)
        elif opts.images or opts.dirinstall:
            self.system._set_option("type", SystemType.UNKNOWN.value)
        else:
            self.system._set_option("type", SystemType.BOOT_ISO.value)

        self.validate()


conf = AnacondaConfiguration.from_defaults()
