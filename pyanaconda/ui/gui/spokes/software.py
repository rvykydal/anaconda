# Software selection spoke classes
#
# Copyright (C) 2011-2013  Red Hat, Inc.
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
# Red Hat Author(s): Chris Lumens <clumens@redhat.com>
#
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Pango", "1.0")

from gi.repository import Gtk, Pango

from pyanaconda.flags import flags
from pyanaconda.i18n import _, C_, CN_
from pyanaconda.packaging import PackagePayload, payloadMgr, NoSuchGroup
from pyanaconda.threads import threadMgr, AnacondaThread
from pyanaconda import constants, iutil

from pyanaconda.ui.communication import hubQ
from pyanaconda.ui.gui.spokes import NormalSpoke
from pyanaconda.ui.gui.spokes.lib.detailederror import DetailedErrorDialog
from pyanaconda.ui.gui.utils import gtk_action_wait, escape_markup
from pyanaconda.ui.categories.software import SoftwareCategory
from pyanaconda.packaging import PayloadError

import logging
log = logging.getLogger("anaconda")

import sys

__all__ = ["SoftwareSelectionSpoke"]

class SoftwareSelectionSpoke(NormalSpoke):
    builderObjects = ["addonStore", "environmentStore", "softwareWindow"]
    mainWidgetName = "softwareWindow"
    uiFile = "spokes/software.glade"
    helpFile = "SoftwareSpoke.xml"

    category = SoftwareCategory

    icon = "package-x-generic-symbolic"
    title = CN_("GUI|Spoke", "_SOFTWARE SELECTION")

    # Add-on selection states
    # no user interaction with this add-on
    _ADDON_DEFAULT = 0
    # user selected
    _ADDON_SELECTED = 1
    # user de-selected
    _ADDON_DESELECTED = 2

    def __init__(self, *args, **kwargs):
        NormalSpoke.__init__(self, *args, **kwargs)
        self._errorMsgs = None
        self._tx_id = None
        self._selectFlag = False

        self._environmentListBox = self.builder.get_object("environmentListBox")
        self._addonListBox = self.builder.get_object("addonListBox")

        # Connect viewport scrolling with listbox focus events
        environmentViewport = self.builder.get_object("environmentViewport")
        addonViewport = self.builder.get_object("addonViewport")
        self._environmentListBox.set_focus_vadjustment(environmentViewport.get_vadjustment())
        self._addonListBox.set_focus_vadjustment(addonViewport.get_vadjustment())

        # Used to store how the user has interacted with add-ons for the default add-on
        # selection logic. The dictionary keys are group IDs, and the values are selection
        # state constants. See refreshAddons for how the values are used.
        self._addonStates = {}

        # Used for detecting whether anything's changed in the spoke.
        self._origAddons = []
        self._origEnvironment = None

        # Register event listeners to update our status on payload events
        payloadMgr.addListener(payloadMgr.STATE_PACKAGE_MD, self._downloading_package_md)
        payloadMgr.addListener(payloadMgr.STATE_GROUP_MD, self._downloading_group_md)
        payloadMgr.addListener(payloadMgr.STATE_FINISHED, self._payload_finished)
        payloadMgr.addListener(payloadMgr.STATE_ERROR, self._payload_error)

        # Add an invisible radio button so that we can show the environment
        # list with no radio buttons ticked
        self._fakeRadio = Gtk.RadioButton(group=None)
        self._fakeRadio.set_active(True)

        # are we taking values (group list) from a kickstart file?
        self._kickstarted = flags.automatedInstall and self.data.packages.seen

    # Payload event handlers
    def _downloading_package_md(self):
        hubQ.send_message(self.__class__.__name__, _("Downloading package metadata..."))

    def _downloading_group_md(self):
        hubQ.send_message(self.__class__.__name__, _("Downloading group metadata..."))

    @property
    def environment(self):
        """A wrapper for the environment specification in kickstart"""
        return self.data.packages.environment

    @environment.setter
    def environment(self, value):
        self.data.packages.environment = value

    @property
    def environmentid(self):
        """Return the "machine readable" environment id

        Alternatively we could have just "canonicalized" the
        environment description to the "machine readable" format
        when reading it from kickstart for the first time.
        But this could result in input and output kickstart,
        which would be rather confusing for the user.
        So we don't touch the specification from kickstart
        if it is valid and use this property when we need
        the "machine readable" form.
        """
        try:
            return self.payload.environmentId(self.environment)
        except NoSuchGroup:
            return None

    @property
    def environment_valid(self):
        """Return if the currently set environment is valid
        (represents an environment known by the payload)
        """
        # None means the environment has not been set by the user,
        # which means:
        # * set the default environment during interactive installation
        # * ask user to specify an environment during kickstart installation
        if self.environment is None:
            return True
        else:
            return self.environmentid in self.payload.environments

    def _payload_finished(self):
        if self.environment_valid:
            log.info("using environment from kickstart: %s", self.environment)
        else:
            log.error("unknown environment has been specified in kickstart and will be ignored: %s",
                      self.data.packages.environment)
            # False means that the environment has been set to an invalid value and needs to
            # be manually set to a valid one.
            self.environment = False

    def _payload_error(self):
        hubQ.send_message(self.__class__.__name__, payloadMgr.error)

    def _apply(self):
        # Environment needs to be set during a GUI installation, but is not required
        # for a kickstart install (even partial)
        if not self.environment:
            log.debug("Environment is not set, skip user packages settings")
            return

        if not self._kickstarted:
            addons = self._get_selected_addons()

            self._selectFlag = False
            self.payload.data.packages.groupList = []
            self.payload.selectEnvironment(self.environment)
            log.debug("Environment selected for installation: %s", self.environment)
            log.debug("Groups selected for installation: %s", addons)
            for group in addons:
                self.payload.selectGroup(group)

            # And then save these values so we can check next time.
            self._origAddons = addons
            self._origEnvironment = self.environment

        hubQ.send_not_ready(self.__class__.__name__)
        hubQ.send_not_ready("SourceSpoke")
        threadMgr.add(AnacondaThread(name=constants.THREAD_CHECK_SOFTWARE,
                                     target=self.checkSoftwareSelection))

    def apply(self):
        # user changed groups or/and environment, it is no longer kickstarted
        if self.environment:
            self._kickstarted = False

        self._apply()

    def checkSoftwareSelection(self):
        from pyanaconda.packaging import DependencyError
        hubQ.send_message(self.__class__.__name__, _("Checking software dependencies..."))
        try:
            self.payload.checkSoftwareSelection()
        except DependencyError as e:
            self._errorMsgs = "\n".join(sorted(e.message))
            hubQ.send_message(self.__class__.__name__, _("Error checking software dependencies"))
            self._tx_id = None
        else:
            self._errorMsgs = None
            self._tx_id = self.payload.txID
        finally:
            hubQ.send_ready(self.__class__.__name__, False)
            hubQ.send_ready("SourceSpoke", False)

    @property
    def completed(self):
        processingDone = bool(not threadMgr.get(constants.THREAD_CHECK_SOFTWARE) and
                              not threadMgr.get(constants.THREAD_PAYLOAD) and
                              not self._errorMsgs and self.txid_valid)

        # * we should always check processingDone before checking the other variables,
        #   as they might be inconsistent until processing is finished
        # * we can't let the installation proceed until a valid environment has been set
        if processingDone:
            if self.environment is not None:
                # if we have environment it needs to be valid
                return self.environment_valid
            # if we don't have environment we need to at least have the %packages
            # section in kickstart
            elif self._kickstarted:
                return True
            # no environment and no %packages section -> manual intervention is needed
            else:
                return False
        else:
            return False

    @property
    def changed(self):
        if not self.environment:
            return True

        addons = self._get_selected_addons()

        # Don't redo dep solving if nothing's changed.
        if self.environment == self._origEnvironment and set(addons) == set(self._origAddons) and \
           self.txid_valid:
            return False

        return True

    @property
    def mandatory(self):
        return True

    @property
    def ready(self):
        # By default, the software selection spoke is not ready.  We have to
        # wait until the installation source spoke is completed.  This could be
        # because the user filled something out, or because we're done fetching
        # repo metadata from the mirror list, or we detected a DVD/CD.

        return bool(not threadMgr.get(constants.THREAD_SOFTWARE_WATCHER) and
                    not threadMgr.get(constants.THREAD_PAYLOAD) and
                    not threadMgr.get(constants.THREAD_CHECK_SOFTWARE) and
                    self.payload.baseRepo is not None)

    @property
    def showable(self):
        return isinstance(self.payload, PackagePayload)

    @property
    def status(self):
        if self._errorMsgs:
            return _("Error checking software selection")

        if not self.ready:
            return _("Installation source not set up")

        if not self.txid_valid:
            return _("Source changed - please verify")

        # kickstart installation
        if flags.automatedInstall:
            if self._kickstarted:
                # %packages section is present in kickstart but environment is not set
                if self.environment is None:
                    return _("Custom software selected")
                # environment is set to an invalid value
                elif not self.environment_valid:
                    return _("Invalid environment specified in kickstart")
            # we have no packages section in the kickstart and no environment is selected
            elif not self.environment:
                return _("Nothing selected")
        else:
            if not self.environment_valid:
                # selected environment is not valid, this can happen when a valid environment
                # is selected (by default, manually or from kickstart) and then the installation
                # source is switched to one where the selected environment is no longer valid
                return _("Selected environment is not valid")
            elif not self.environment:
                return _("Nothing selected")

        try:
            return self.payload.environmentDescription(self.environment)[0]
        except NoSuchGroup:
            return _("Selected environment is not valid")

    def initialize(self):
        NormalSpoke.initialize(self)
        self.initialize_start()
        threadMgr.add(AnacondaThread(name=constants.THREAD_SOFTWARE_WATCHER,
                      target=self._initialize))

    def _initialize(self):
        threadMgr.wait(constants.THREAD_PAYLOAD)

        # Select groups which should be selected by kickstart
        try:
            for group in self.payload.selectedGroupsIDs():
                if self.environment and self.payload.environmentOptionIsDefault(self.environment, group):
                    self._addonStates[group] = self._ADDON_DEFAULT
                else:
                    self._addonStates[group] = self._ADDON_SELECTED
        except PayloadError as e:
            # Group translation is not supported
            log.warning(e)
            # It's better to have all or nothing selected from kickstart
            self._addonStates = {}

        if not self._kickstarted:
            # having done all the slow downloading, we need to do the first refresh
            # of the UI here so there's an environment selected by default.  This
            # happens inside the main thread by necessity.  We can't do anything
            # that takes any real amount of time, or it'll block the UI from
            # updating.
            if not self._first_refresh():
                return

        hubQ.send_ready(self.__class__.__name__, False)

        # If packages were provided by an input kickstart file (or some other means),
        # we should do dependency solving here.
        self._apply()

        # report that software spoke initialization has been completed
        self.initialize_done()

    @gtk_action_wait
    def _first_refresh(self):
        self.refresh()
        return True

    def _add_row(self, listbox, name, desc, button, clicked):
        row = Gtk.ListBoxRow()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        button.set_valign(Gtk.Align.START)
        button.connect("toggled", clicked, row)
        box.add(button)

        label = Gtk.Label(label="<b>%s</b>\n%s" % (escape_markup(name), escape_markup(desc)),
                          use_markup=True, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR,
                          hexpand=True, xalign=0, yalign=0.5)
        box.add(label)

        row.add(box)
        listbox.insert(row, -1)

    def refresh(self):
        NormalSpoke.refresh(self)

        threadMgr.wait(constants.THREAD_PAYLOAD)

        firstEnvironment = True

        self._clear_listbox(self._environmentListBox)

        # create rows for all valid environments
        for environmentid in self.payload.environments:
            (name, desc) = self.payload.environmentDescription(environmentid)

            # use the invisible radio button as a group for all environment
            # radio buttons
            radio = Gtk.RadioButton(group=self._fakeRadio)

            # automatically select the first environment if we are on
            # manual install and the install class does not specify one
            if firstEnvironment and not flags.automatedInstall:  # manual installation
                #
                # Note about self.environment being None:
                # =======================================
                # None indicates that an environment has not been set, which is a valid
                # value of the environment variable.
                # Only non existing environments are evaluated as invalid
                if not self.environment_valid or self.environment is None:
                    self.environment = environmentid
                firstEnvironment = False

            # check if the selected environment (if any) does match the current row
            # and tick the radio button if it does
            radio.set_active(self.environment_valid and self.environmentid == environmentid)

            self._add_row(self._environmentListBox, name, desc, radio, self.on_radio_button_toggled)

        self.refreshAddons()
        self._environmentListBox.show_all()
        self._addonListBox.show_all()

    def _addAddon(self, grp):
        (name, desc) = self.payload.groupDescription(grp)

        if grp in self._addonStates:
            # If the add-on was previously selected by the user, select it
            if self._addonStates[grp] == self._ADDON_SELECTED:
                selected = True
            # If the add-on was previously de-selected by the user, de-select it
            elif self._addonStates[grp] == self._ADDON_DESELECTED:
                selected = False
            # Otherwise, use the default state
            else:
                selected = self.payload.environmentOptionIsDefault(self.environment, grp)
        else:
            selected = self.payload.environmentOptionIsDefault(self.environment, grp)

        check = Gtk.CheckButton()
        check.set_active(selected)
        self._add_row(self._addonListBox, name, desc, check, self.on_checkbox_toggled)

    def refreshAddons(self):
        if self.environment and (self.environmentid in self.payload.environmentAddons):
            self._clear_listbox(self._addonListBox)

            # We have two lists:  One of addons specific to this environment,
            # and one of all the others.  The environment-specific ones will be displayed
            # first and then a separator, and then the generic ones.  This is to make it
            # a little more obvious that the thing on the left side of the screen and the
            # thing on the right side of the screen are related.
            #
            # If a particular add-on was previously selected or de-selected by the user, that
            # state will be used. Otherwise, the add-on will be selected if it is a default
            # for this environment.

            addSep = len(self.payload.environmentAddons[self.environmentid][0]) > 0 and \
                     len(self.payload.environmentAddons[self.environmentid][1]) > 0

            for grp in self.payload.environmentAddons[self.environmentid][0]:
                self._addAddon(grp)

            # This marks a separator in the view - only add it if there's both environment
            # specific and generic addons.
            if addSep:
                self._addonListBox.insert(Gtk.Separator(), -1)

            for grp in self.payload.environmentAddons[self.environmentid][1]:
                self._addAddon(grp)

        self._selectFlag = True

        if self._errorMsgs:
            self.set_warning(_("Error checking software dependencies.  <a href=\"\">Click for details.</a>"))
        else:
            self.clear_info()

    def _allAddons(self):
        return self.payload.environmentAddons[self.environmentid][0] + \
               [""] + \
               self.payload.environmentAddons[self.environmentid][1]

    def _get_selected_addons(self):
        retval = []
        addons = self._allAddons()

        for (ndx, row) in enumerate(self._addonListBox.get_children()):
            box = row.get_children()[0]

            if isinstance(box, Gtk.Separator):
                continue

            button = box.get_children()[0]
            if button.get_active():
                retval.append(addons[ndx])

        return retval

    def _mark_addon_selection(self, grpid, selected):
        # Mark selection or return its state to the default state
        if selected:
            if self.payload.environmentOptionIsDefault(self.environment, grpid):
                self._addonStates[grpid] = self._ADDON_DEFAULT
            else:
                self._addonStates[grpid] = self._ADDON_SELECTED
        else:
            if not self.payload.environmentOptionIsDefault(self.environment, grpid):
                self._addonStates[grpid] = self._ADDON_DEFAULT
            else:
                self._addonStates[grpid] = self._ADDON_DESELECTED

    def _clear_listbox(self, listbox):
        for child in listbox.get_children():
            listbox.remove(child)
            del(child)

    @property
    def txid_valid(self):
        return self._tx_id == self.payload.txID

    # Signal handlers
    def on_radio_button_toggled(self, radio, row):
        # If the radio button toggled to inactive, don't reactivate the row
        if not radio.get_active():
            return
        row.activate()

    def on_environment_activated(self, listbox, row):
        if not self._selectFlag:
            return

        box = row.get_children()[0]
        button = box.get_children()[0]

        button.handler_block_by_func(self.on_radio_button_toggled)
        button.set_active(True)
        button.handler_unblock_by_func(self.on_radio_button_toggled)

        # Mark the clicked environment as selected and update the screen.
        self.environment = self.payload.environments[row.get_index()]
        self.refreshAddons()
        self._addonListBox.show_all()

    def on_checkbox_toggled(self, button, row):
        # Select the addon. The button is already toggled.
        self._select_addon_at_row(row, button.get_active())

    def on_addon_activated(self, listbox, row):
        # Skip the separator.
        box = row.get_children()[0]
        if isinstance(box, Gtk.Separator):
            return

        # Select the addon. The button is not toggled yet.
        button = box.get_children()[0]
        self._select_addon_at_row(row, not button.get_active())

    def _select_addon_at_row(self, row, is_selected):
        # GUI selections means that packages are no longer coming from kickstart.
        self._kickstarted = False

        # Activate the row.
        listbox = row.get_parent()
        listbox.handler_block_by_func(self.on_addon_activated)
        row.activate()
        listbox.handler_unblock_by_func(self.on_addon_activated)

        # Activate the button.
        box = row.get_children()[0]
        button = box.get_children()[0]
        button.handler_block_by_func(self.on_checkbox_toggled)
        button.set_active(is_selected)
        button.handler_unblock_by_func(self.on_checkbox_toggled)

        # Mark the selection.
        addons = self._allAddons()
        group = addons[row.get_index()]
        self._mark_addon_selection(group, is_selected)

    def on_info_bar_clicked(self, *args):
        if not self._errorMsgs:
            return

        label = _("The software marked for installation has the following errors.  "
                  "This is likely caused by an error with your installation source.  "
                  "You can quit the installer, change your software source, or change "
                  "your software selections.")
        dialog = DetailedErrorDialog(self.data,
                buttons=[C_("GUI|Software Selection|Error Dialog", "_Quit"),
                         C_("GUI|Software Selection|Error Dialog", "_Modify Software Source"),
                         C_("GUI|Software Selection|Error Dialog", "Modify _Selections")],
                label=label)
        with self.main_window.enlightbox(dialog.window):
            dialog.refresh(self._errorMsgs)
            rc = dialog.run()

        dialog.window.destroy()

        if rc == 0:
            # Quit.
            iutil.ipmi_abort(scripts=self.data.scripts)
            sys.exit(0)
        elif rc == 1:
            # Send the user to the installation source spoke.
            self.skipTo = "SourceSpoke"
            self.window.emit("button-clicked")
        elif rc == 2:
            # Close the dialog so the user can change selections.
            pass
        else:
            pass