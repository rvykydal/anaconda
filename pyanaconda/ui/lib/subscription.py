#
# Subscription related helper functions.
#
# Copyright (C) 2020  Red Hat, Inc.  All rights reserved.
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

from enum import Enum

from pyanaconda.threading import threadMgr

from pyanaconda.core.constants import THREAD_WAIT_FOR_CONNECTING_NM, \
    SUBSCRIPTION_REQUEST_TYPE_USERNAME_PASSWORD, SUBSCRIPTION_REQUEST_TYPE_ORG_KEY, \
    SOURCE_TYPE_HDD, SOURCE_TYPE_CDN
from pyanaconda.core.i18n import _
from pyanaconda.ui.lib.payload import create_source, set_source, tear_down_sources
from pyanaconda.ui.lib.storage import unmark_protected_device

from pyanaconda.modules.common.constants.services import SUBSCRIPTION
from pyanaconda.modules.common import task
from pyanaconda.modules.common.structures.subscription import SubscriptionRequest
from pyanaconda.modules.common.structures.secret import SECRET_TYPE_HIDDEN, \
    SECRET_TYPE_TEXT
from pyanaconda.modules.common.errors.subscription import RegistrationError, \
    UnregistrationError, SubscriptionError

from pyanaconda.anaconda_loggers import get_module_logger
log = get_module_logger(__name__)

# The following secret types mean a secret has been set
# (and it is either in plaintext or hidden in the module).
SECRET_SET_TYPES = (SECRET_TYPE_TEXT, SECRET_TYPE_HIDDEN)

# Asynchronous subscription state tracking
class SubscriptionPhase(Enum):
    UNREGISTER = 1
    REGISTER = 2
    ATTACH_SUBSCRIPTION = 3
    DONE = 4

# temporary methods for Subscription/CDN related source switching


def _tear_down_existing_source(payload):
    """Tear down existing payload, so we can set a new one.

    :param payload: Anaconda payload instance
    """
    source_proxy = payload.get_source_proxy()

    if source_proxy.Type == SOURCE_TYPE_HDD and source_proxy.Partition:
        unmark_protected_device(source_proxy.Partition)

    tear_down_sources(payload.proxy)


def set_source_cdn(payload):
    """Switch to the CDN installation source.

    :param payload: Anaconda payload instance
    """
    _tear_down_existing_source(payload)

    new_source_proxy = create_source(SOURCE_TYPE_CDN)
    set_source(payload.proxy, new_source_proxy)


def check_cdn_is_installation_source(payload):
    """Check if Red Hat CDN is the current installation source.

    :param payload: Anaconda payload instance
    """
    source_proxy = payload.get_source_proxy()
    return source_proxy.Type == SOURCE_TYPE_CDN

# Asynchronous registration + subscription & unregistration handling
#
# The Red Hat subscription related tasks communicate over network and might
# take some time to finish (up to tens of seconds). We definitely don't want
# to block either automated installation or the UI before they finish.
#
# These tasks (register + attach subscription and unregister) need to run in
# threads and these threads need to be started from at least two places:
# - from early startup code for automated installations
# - from Subscription spoke based on user interaction
#
# Also in some cases, multiple individual DBus tasks will need to be run
# in sequence with any errors handled accordingly.
#
# Anaconda modularity is not yet advanced enough to handle this in a generic
# manner, so we need simple scheduler living in the context of the main Anaconda
# thread. The simple scheduler hosts the code that starts the respective subscription
# handling thread, which assures appropriate tasks are run.
#
# As the scheduler code than can be run either during early startup or in reaction to user
# interaction in the Subscription spoke we avoid code duplication.


def dummy_progress_callback(subscription_phase):
    """Dummy progress reporting function used if no custom callback is set."""
    pass


def dummy_error_callback(error_message):
    """Dummy error reporting function used if no custom callback is set."""
    pass


def org_keys_sufficient(subscription_request=None):
    """Report if sufficient credentials are set for org & keys registration attempt.

    :param subscription_request: an subscription request, if None a fresh subscription request
                                 will be fetched from the Subscription module over DBus
    :type subscription_request: SubscriptionRequest instance
    :return: True if sufficient, False otherwise
    :rtype: bool
    """
    if subscription_request is None:
        subscription_proxy = SUBSCRIPTION.get_proxy()
        subscription_request_struct = subscription_proxy.SubscriptionRequest
        subscription_request = SubscriptionRequest.from_structure(subscription_request_struct)
    organization_set = bool(subscription_request.organization)
    key_set = subscription_request.activation_keys.type in SECRET_SET_TYPES
    return organization_set and key_set


def username_password_sufficient(subscription_request=None):
    """Report if sufficient credentials are set for username & password registration attempt.

    :param subscription_request: an subscription request, if None a fresh subscription request
                                 will be fetched from the Subscription module over DBus
    :type subscription_request: SubscriptionRequest instance
    :return: True if sufficient, False otherwise
    :rtype: bool
    """
    if subscription_request is None:
        subscription_proxy = SUBSCRIPTION.get_proxy()
        subscription_request_struct = subscription_proxy.SubscriptionRequest
        subscription_request = SubscriptionRequest.from_structure(subscription_request_struct)
    username_set = bool(subscription_request.account_username)
    password_set = subscription_request.account_password.type in SECRET_SET_TYPES
    return username_set and password_set


def register_and_subscribe(payload, progress_callback=None, error_callback=None):
    """Try to register and subscribe the installation environment.

    :param payload: Anaconda payload instance
    :param progress_callback: progress callback function, takes one argument, subscription phase
    :type progress_callback: callable(subscription_phase)
    :param error_callback: error callback function, takes one argument, the error message
    :type error_callback: callable(error_message)
    """

    # assign dummy callback functions if none were provided by caller
    if progress_callback is None:
        progress_callback = dummy_progress_callback
    if error_callback is None:
        error_callback = dummy_error_callback

    # connect to the Subscription DBus module
    subscription_proxy = SUBSCRIPTION.get_proxy()

    # First make sure network connectivity is available
    # by waiting for the connectivity check thread
    # to finish, in case it is running, usually early
    # during Anaconda startup.
    threadMgr.wait(THREAD_WAIT_FOR_CONNECTING_NM)

    # Next we make sure to set RHSM config options
    # to be in sync with the current subscription request.
    task_path = subscription_proxy.SetRHSMConfigWithTask()
    task_proxy = SUBSCRIPTION.get_proxy(task_path)
    task.sync_run_task(task_proxy)

    # Then check if we are not already registered.
    #
    # In some fairly bizarre cases it is apparently
    # possible that registration & attach will succeed,
    # but the attached subscription will be incomplete
    # and/or invalid. These cases will be caught by
    # the subscription token check and marked as failed
    # by Anaconda.
    #
    # It is also possible that registration succeeds,
    # but attach fails.
    #
    # To make recovery and another registration attempt
    # possible, we need to first unregister the already
    # registered system, as a registration attempt on
    # an already registered system would fail.
    if subscription_proxy.IsRegistered:
        log.debug("subscription thread: system already registered, unregistering")
        progress_callback(SubscriptionPhase.UNREGISTER)
        task_path = subscription_proxy.UnregisterWithTask()
        task_proxy = SUBSCRIPTION.get_proxy(task_path)
        try:
            task.sync_run_task(task_proxy)
        except UnregistrationError as e:
            log.debug("subscription thread: unregistration failed: %s", e)
            # Failing to unregister the system is an unrecoverable error,
            # so we end there.
            error_callback(str(e))
            return
        log.debug("Subscription GUI: unregistration succeeded")

    # Try to register.
    #
    # If we got this far the system was either not registered
    # or was unregistered successfully.
    log.debug("subscription thread: attempting to register")
    progress_callback(SubscriptionPhase.REGISTER)
    # check authentication method has been set and credentials seem to be
    # sufficient (though not necessarily valid)
    subscription_request_struct = subscription_proxy.SubscriptionRequest
    subscription_request = SubscriptionRequest.from_structure(subscription_request_struct)
    task_path = None
    if subscription_request.type == SUBSCRIPTION_REQUEST_TYPE_USERNAME_PASSWORD:
        if username_password_sufficient():
            task_path = subscription_proxy.RegisterUsernamePasswordWithTask()
    elif subscription_request.type == SUBSCRIPTION_REQUEST_TYPE_ORG_KEY:
        if org_keys_sufficient():
            task_path = subscription_proxy.RegisterOrganizationKeyWithTask()

    if task_path:
        task_proxy = SUBSCRIPTION.get_proxy(task_path)
        try:
            task.sync_run_task(task_proxy)
        except RegistrationError as e:
            log.debug("subscription thread: registration attempt failed: %s", e)
            log.debug("subscription thread: skipping auto attach due to registration error")
            error_callback(str(e))
            return
        log.debug("subscription thread: registration succeeded")
    else:
        log.debug("subscription thread: credentials insufficient, skipping registration attempt")
        error_callback(_("Registration failed due to insufficient credentials."))
        return

    # try to attach subscription
    log.debug("subscription thread: attempting to auto attach an entitlement")
    progress_callback(SubscriptionPhase.ATTACH_SUBSCRIPTION)
    task_path = subscription_proxy.AttachSubscriptionWithTask()
    task_proxy = SUBSCRIPTION.get_proxy(task_path)
    try:
        task.sync_run_task(task_proxy)
    except SubscriptionError as e:
        log.debug("subscription thread: failed to attach subscription: %s", e)
        error_callback(str(e))
        return

    # parse attached subscription data
    log.debug("subscription thread: parsing attached subscription data")
    task_path = subscription_proxy.ParseAttachedSubscriptionsWithTask()
    task_proxy = SUBSCRIPTION.get_proxy(task_path)
    task.sync_run_task(task_proxy)

    # report attaching subscription was successful
    log.debug("subscription thread: auto attach succeeded")
    # set CDN as installation source now that we can use it
    log.debug("subscription thread: setting CDN as installation source")
    set_source_cdn(payload)
    # and done
    progress_callback(SubscriptionPhase.DONE)


def unregister(progress_callback=None, error_callback=None):
    """Try to unregister the installation environment.

    NOTE: Unregistering also removes any attached subscriptions

    :param progress_callback: progress callback function, takes one argument, subscription phase
    :type progress_callback: callable(subscription_phase)
    :param error_callback: error callback function, takes one argument, the error message
    :type error_callback: callable(error_message)
    """

    # assign dummy callback functions if none were provided by caller
    if progress_callback is None:
        progress_callback = dummy_progress_callback
    if error_callback is None:
        error_callback = dummy_error_callback

    # connect to the Subscription DBus module
    subscription_proxy = SUBSCRIPTION.get_proxy()

    if subscription_proxy.IsRegistered:
        log.debug("subscription thread: unregistering the system")
        # Make sure to set RHSM config options to be in sync
        # with the current subscription request in the unlikely
        # case of someone doing a valid change in the subscription
        # request since we registered.
        task_path = subscription_proxy.SetRHSMConfigWithTask()
        task_proxy = SUBSCRIPTION.get_proxy(task_path)
        task.sync_run_task(task_proxy)
        progress_callback(SubscriptionPhase.UNREGISTER)
        task_path = subscription_proxy.UnregisterWithTask()
        task_proxy = SUBSCRIPTION.get_proxy(task_path)
        try:
            task.sync_run_task(task_proxy)
        except UnregistrationError as e:
            log.debug("subscription thread: unregistration failed: %s", e)
            error_callback(str(e))
            return
        log.debug("Subscription GUI: unregistration succeeded")
        progress_callback(SubscriptionPhase.DONE)
    else:
        log.warning("subscription thread: not registered, so can't unregister")
        progress_callback(SubscriptionPhase.DONE)
        return