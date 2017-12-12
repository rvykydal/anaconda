#
# Distributing kickstart to anaconda modules.
#
# Copyright (C) 2017  Red Hat, Inc.  All rights reserved.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

from pydbus.error import map_error
from pydbus.auto_names import auto_object_path

from pyanaconda.dbus import DBus
from pyanaconda.dbus.constants import DBUS_BOSS_ANACONDA_NAME

from pyanaconda.kickstart_dispatcher.parser import SplitKickstartParser, VALID_SECTIONS_ANACONDA
from pykickstart.version import makeVersion
from pykickstart.errors import KickstartError, KickstartParseError

from pyanaconda.anaconda_loggers import get_module_logger
log = get_module_logger(__name__)


__all__ = ['KickstartManager', 'SplitKickstartError']


@map_error("{}.SplitKickstartError".format(DBUS_BOSS_ANACONDA_NAME))
class SplitKickstartError(Exception):
    """Error when parsing kickstart for splitting."""
    pass


class SplitKickstartUnknownSectionError(SplitKickstartError):
    """Unknown section was found in kickstart."""
    pass


class SplitKickstartMissingIncludeError(SplitKickstartError):
    """File included in kickstart was not found."""
    pass


class KickstartManager(object):
    """Distibutes kickstart to modules and collects it back."""

    def __init__(self):
        self._kickstart_path = None
        self._elements = None
        self._module_errors = []

    @property
    def elements(self):
        """Return all elements of split kickstart."""
        return self._elements

    @property
    def module_errors(self):
        """Return all errors from distribution of kickstart to modules."""
        return self._module_errors

    @property
    def unprocessed_kickstart(self):
        """Return kickstart not processed by any module."""
        return self._elements.get_kickstart_from_elements(self._elements.unprocessed_elements)

    def split(self, path):
        """Split the kickstart given by path into elements."""
        self._elements = None
        self._kickstart_path = path
        handler = makeVersion()
        ksparser = SplitKickstartParser(handler, valid_sections=VALID_SECTIONS_ANACONDA)
        try:
            result = ksparser.split(path)
        except KickstartParseError as e:
            raise SplitKickstartUnknownSectionError(e)
        except KickstartError as e:
            raise SplitKickstartMissingIncludeError(e)
        log.info("split {}: {}".format(path, result))
        self._elements = result

    def distribute(self, module_services):
        """Distribute elements to modules synchronously.

        :returns: an error occured in a module when distributing kickstart
        :rtype: bool
        """
        self._module_errors = []

        for service in module_services:

            module = DBus.get_proxy(service, auto_object_path(service))
            commands = module.KickstartCommands()
            sections = module.KickstartSections()
            addons = module.KickstartAddons()
            log.info("distribute kickstart: {} handles commands {} sections {} addons {}".format(
                service, commands, sections, addons))

            elements = self._elements.get_and_process_elements(commands=commands,
                                                               sections=sections,
                                                               addons=addons)
            kickstart = self._elements.get_kickstart_from_elements(elements)
            log.info("distribute kickstart: {} will get kickstart elements: {}".format(
                service, elements))

            lines_mapping = self._elements.get_references_from_elements(elements)
            module_error_lineno, msg = module.ConfigureWithKickstart(kickstart)
            if module_error_lineno != 0:
                error_reference = lines_mapping[module_error_lineno]
                self._module_errors.append((service, error_reference, msg))
        return not self._module_errors

    def collect(self):
        """Collect kickstarts from configured modules."""
        pass
