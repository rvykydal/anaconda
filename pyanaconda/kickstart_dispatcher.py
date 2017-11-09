#
# kickstart_dispatcher.py: Anaconda kickstart dispatching for modules
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

from collections import namedtuple

from pykickstart.version import returnClassForVersion
from pykickstart.parser import KickstartParser
from pykickstart.sections import Section

from pyanaconda.anaconda_loggers import get_module_logger
log = get_module_logger(__name__)

# TODO
# - doc texts
# - commands and sections as sets?
# - excluding?
# - unify commands and sections?

# QUESTIONS
# - error checking and handling -> expect syntactically correct ks?
# - are we actually able to split on kickstart level or are there some hidden dependencies?
# - move to ks package?
# - kickstart_from_result as result object method?

# ISSUES
# + bootloader appears there if all handleCommand is pass
#   because it has some default value
# + pykickstart PR for NullSection formatting (newlines)
#   - not needed because not inherining NullSection

# TODONOW
# - ks with all sections (including %anaconda and %addon)
# - pylint

KickstartCommandOrSection = namedtuple('KickstartCommandOrSection', ['content', 'lineno', 'filename'])


class FilterSection(Section):
    """Section which optionally stores section content and header line references.

	Similarly as NullSection defines a section that parser will recognize (ie
    will not raise an error) and optionally store the content and file origin
    reference (line number of section header) for later use.

    """

    allLines = True

    def __init__(self, *args, **kwargs):
        """Create a new FilterSection instance.

        You must pass a sectionOpen parameter (including a leading '%') for the
        section to be just ignored. If you want to store the content supply a
        list in store parameter. The content will be appended to the list.

        Required kwargs:

        sectionOpen - section name, including '%' starting character

        Optional kwargs:

        store - a list to which KickstartCommandOrSection object containing content
                of the section and the header line reference will be appended
        """
        super().__init__(*args, **kwargs)
        self.sectionOpen = kwargs.get("sectionOpen")
        self._store = kwargs.get("store", None)
        self._header_lineno = 0
        self._args = []
        self._body = []

    def handleHeader(self, lineno, args):
        self._header_lineno = lineno
        self._args = args

    def handleLine(self, line):
        self._body.append(line)

    @property
    def current_ks_filename(self):
        return getattr(self.handler, "_current_ksfile", "")

    def finalize(self):
        if self._store is not None:
            body = "".join(self._body)
            if body:
                s = "{}\n{}%end\n".format(" ".join(self._args), body)
            else:
                s = "{}\n%end\n".format(" ".join(self._args))
            section = KickstartCommandOrSection(s, self._header_lineno, self.current_ks_filename)
            self._store.append(section)
        self._header_lineno = 0
        self._args = []
        self._body = []


class FilterKickstartParser(KickstartParser):
    """Kickstart parser for filtering specific commands and sections.

    Filters specified commands and sections. Does not do any actual command
    or section parsing (ie command syntax checking).
    """

    unknown_filename = "<MAIN>"

    def __init__(self, handler, valid_sections=None, missing_include_is_fatal=True):
        """Initialize the filter.

        :param valid_sections: list of valid kickstart sections
        :type valid_sections: list(str)
        :param missing_include_is_fatal: raise error if included file is not found
        :type missing_include_is_fatal: bool
        """

        self._valid_sections = valid_sections or []
        self._accepted_sections = []
        self._filtered_sections = []
        # calls setupSections
        super().__init__(handler, missingIncludeIsFatal=missing_include_is_fatal)
        self._accepted_commands = []
        self._filtered_commands = []
        self.current_ks_filename = self.unknown_filename

    @property
    def valid_sections(self):
        """List of valid kickstart sections"""
        return list(self._valid_sections)

    @valid_sections.setter
    def valid_sections(self, value):
        self._valid_sections = value

    def filter(self, filename, commands=None, sections=None):
        """Filter commands and sections from kickstart given by filename.

        :param filename: name of kickstart file
        :type filename: str
        :param commands: list of accepted commands
        :type commands: list(str)
        :param sections: list of accepted sections (including % starting character)
        :type sections: list(str)

        :return: List of objects containing filtered commands and sections.
                 For command it contains the line, line number and kickstart filename
                 For section it contains the section, section header line number
                 and kickstart filename.
                 The list preservers the order of commands and sections.
        :rtype: list(KickstartCommandOrSection)
        """
        with open(filename, "r") as f:
            kickstart = f.read()
        return self.filter_from_string(kickstart, commands=commands, sections=sections,
                                       filename=filename)

    def filter_from_string(self, kickstart, commands=None, sections=None, filename=None):
        """Filter commands and sections from kickstart given by string

        :param kickstart: string containing kickstart
        :type kickstart: str
        :param commands: list of accepted commands
        :type commands: list(str)
        :param sections: list of accepted sections (including % starting character)
        :type sections: list(str)
        :param filename: filename to be used as file reference in the result
        :type filename: str

        :return: List of objects containing filtered commands and sections.
                 For command it contains the line, line number and kickstart filename
                 For section it contains the section, section header line number
                 and kickstart filename.
                 The list preservers the order of commands and sections.
        :rtype: list(KickstartCommandOrSection)
        """
        self._reset()
        self._accepted_commands = commands or []
        self._accepted_sections = sections or []
        self._current_ks_filename = filename or self.unknown_filename
        self.readKickstartFromString(kickstart)
        result = self._filtered_commands + self._filtered_sections
        return result

    @staticmethod
    def kickstart_from_result(result):
        """Returns kickstart generated from the filtering result."""
        return "".join(element.content for element in result)

    @property
    def _current_ks_filename(self):
        """Filename of currently parsed kickstart"""
        return self.handler._current_ksfile

    @_current_ks_filename.setter
    def _current_ks_filename(self, value):
        self.handler._current_ksfile = value

    def _reset(self):
        self._filtered_commands = []
        self._filtered_sections = []
        self.setupSections()

    def _handleInclude(self, filename):
        """Overrides parent to keep track of kickstart filename following includes."""
        parent_file = self._current_ks_filename
        self._current_ks_filename = filename
        super()._handleInclude(filename)
        self._current_ks_filename = parent_file

    def handleCommand(self, lineno, args):
        """Overrides parent method to store filtered command."""
        if args[0] in self._accepted_commands:
            command = KickstartCommandOrSection(self._line, lineno, self._current_ks_filename)
            self._filtered_commands.append(command)

    def setupSections(self):
        """Overrides parent method to store content of filtered sections."""
        self._sections = {}
        for section in self._valid_sections:
            if section in self._accepted_sections:
                store = self._filtered_sections
            else:
                store = None
            self.registerSection(FilterSection(self.handler,
                                               sectionOpen=section,
                                               store = store))

def split_kickstart(filename, valid_sections, commands, sections):
    handlerclass = returnClassForVersion()
    handler = handlerclass()
    ksparser = FilterKickstartParser(handler, valid_sections)
    result = ksparser.filter(filename, commands, sections)
    print(result)
    print(ksparser.kickstart_from_result(result))

    print("#" * 60)
    result = ksparser.filter(filename, commands=["network", "firewall"], sections=["%packages", "%addon"])
    print(result)
    print(ksparser.kickstart_from_result(result))

    print("#" * 60)
    with open(filename) as f:
        kickstart = f.read()
    result = ksparser.filter_from_string(kickstart, commands, sections)
    print(result)
    print(ksparser.kickstart_from_result(result))

