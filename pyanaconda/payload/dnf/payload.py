# DNF/rpm software payload management.
#
# Copyright (C) 2019  Red Hat, Inc.
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
from pyanaconda.core.path import join_paths
from pyanaconda.modules.common.errors.installation import NonCriticalInstallationError, \
    InstallationError
from pyanaconda.modules.common.errors.payload import UnknownRepositoryError, SourceSetupError
from pyanaconda.modules.common.structures.payload import RepoConfigurationData
from pyanaconda.modules.common.structures.packages import PackagesConfigurationData, \
    PackagesSelectionData
from pyanaconda.modules.common.structures.validation import ValidationReport
from pyanaconda.modules.payloads.base.initialization import SetUpSourcesTask, TearDownSourcesTask
from pyanaconda.modules.payloads.payload.dnf.initialization import configure_dnf_logging
from pyanaconda.modules.payloads.payload.dnf.installation import ImportRPMKeysTask, \
    SetRPMMacrosTask, DownloadPackagesTask, InstallPackagesTask, PrepareDownloadLocationTask, \
    CleanUpDownloadLocationTask, ResolvePackagesTask, UpdateDNFConfigurationTask, \
    WriteRepositoriesTask
from pyanaconda.modules.payloads.payload.dnf.repositories import \
    generate_driver_disk_repositories, update_treeinfo_repositories
from pyanaconda.modules.payloads.payload.dnf.tear_down import ResetDNFManagerTask
from pyanaconda.modules.payloads.payload.dnf.utils import get_kernel_version_list, \
    calculate_required_space
from pyanaconda.modules.payloads.payload.dnf.dnf_manager import DNFManager, DNFManagerError, \
    MetadataError
from pyanaconda.modules.payloads.payload.dnf.validation import CheckPackagesSelectionTask, \
    VerifyRepomdHashesTask
from pyanaconda.modules.payloads.source.harddrive.initialization import SetUpHardDriveSourceTask
from pyanaconda.modules.payloads.source.mount_tasks import TearDownMountTask
from pyanaconda.modules.payloads.source.nfs.nfs import NFSSourceModule
from pyanaconda.modules.payloads.source.utils import verify_valid_repository, MountPointGenerator
from pyanaconda.anaconda_loggers import get_packaging_logger
from pyanaconda.core import constants
from pyanaconda.core.configuration.anaconda import conf
from pyanaconda.core.constants import INSTALL_TREE, ISO_DIR, PAYLOAD_TYPE_DNF, SOURCE_TYPE_URL, \
    SOURCE_REPO_FILE_TYPES, SOURCE_TYPE_REPO_PATH, SOURCE_TYPE_CDN, MULTILIB_POLICY_ALL, \
    REPO_ORIGIN_SYSTEM, SOURCE_TYPE_CLOSEST_MIRROR, REPO_ORIGIN_TREEINFO, DRACUT_REPO_DIR, \
    SOURCE_TYPE_CDROM, SOURCE_TYPE_NFS, SOURCE_TYPE_HDD, SOURCE_TYPE_HMC
from pyanaconda.core.i18n import _
from pyanaconda.core.payload import parse_hdd_url
from pyanaconda.errors import errorHandler as error_handler, ERROR_RAISE
from pyanaconda.modules.common.constants.services import SUBSCRIPTION
from pyanaconda.modules.common.util import is_module_available
from pyanaconda.payload.base import Payload
from pyanaconda.modules.payloads.payload.dnf.tree_info import LoadTreeInfoMetadataTask
from pyanaconda.ui.lib.payload import get_payload, get_source, create_source, set_source, \
    set_up_sources, tear_down_sources

__all__ = ["DNFPayload"]

log = get_packaging_logger()


class DNFPayload(Payload):

    def __init__(self, data):
        super().__init__()
        self.data = data

        # Validation report from the payload setup.
        self._report = ValidationReport()

        # Get a DBus payload to use.
        self._payload_proxy = get_payload(self.type)

        self._software_validation_required = True

        self._dnf_manager = DNFManager()

        # List of internal mount points and sources.
        self._mount_points = []
        self._internal_sources = []

        # Generate mount points in a different interval to
        # avoid conflicts with mount points generated in
        # the DBus module. This is a temporary workaround.
        MountPointGenerator._counter = 1000

        # Configure the DNF logging.
        configure_dnf_logging()

    @property
    def dnf_manager(self):
        """The DNF manager."""
        return self._dnf_manager

    @property
    def _base(self):
        """Return a DNF base.

        FIXME: This is a temporary property.
        """
        return self._dnf_manager._base

    @property
    def report(self):
        """The latest report from the payload setup."""
        return self._report

    def set_from_opts(self, opts):
        """Set the payload from the Anaconda cmdline options.

        :param opts: a namespace of options
        """
        self._set_default_source(opts)
        self._set_source_configuration_from_opts(opts)
        self._set_additional_repos_from_opts(opts)
        self._generate_driver_disk_repositories()
        self._set_packages_from_opts(opts)

    def _set_default_source(self, opts):
        """Set the default source.

        Set the source based on opts.method if it isn't already set
        - opts.method is currently set by command line/boot options.

        Otherwise, use the source provided at a specific mount point
        by Dracut if there is any.

        Otherwise, use the default source specified in the Anaconda
        configuration files as a fallback.

        In summary, the installer chooses a default source of the DNF
        payload based on data processed in this order:

        1. Kickstart file
        2. Boot options or command line options
        3. Installation image mounted by Dracut
        4. Anaconda configuration file

        """
        if self.proxy.Sources:
            log.debug("The DNF source is already set.")

        elif opts.method:
            log.debug("Use the DNF source from opts.")
            source_proxy = self._create_source_from_url(opts.method)
            set_source(self.proxy, source_proxy)

        elif verify_valid_repository(DRACUT_REPO_DIR):
            log.debug("Use the DNF source from Dracut.")
            source_proxy = create_source(SOURCE_TYPE_REPO_PATH)
            source_proxy.Path = DRACUT_REPO_DIR
            set_source(self.proxy, source_proxy)

        else:
            log.debug("Use the DNF source from the Anaconda configuration file.")
            source_proxy = create_source(conf.payload.default_source)
            set_source(self.proxy, source_proxy)

    @staticmethod
    def _create_source_from_url(url):
        """Create a new source for the specified URL.

        :param str url: the URL of the source
        :return: a DBus proxy of the new source
        :raise ValueError: if the URL is unsupported
        """
        if url.startswith("cdrom"):
            return create_source(SOURCE_TYPE_CDROM)

        if url.startswith("hmc"):
            return create_source(SOURCE_TYPE_HMC)

        if url.startswith("nfs:"):
            source_proxy = create_source(SOURCE_TYPE_NFS)

            source_proxy.Configuration = \
                RepoConfigurationData.to_structure(
                    RepoConfigurationData.from_url(url)
                )

            return source_proxy

        if url.startswith("hd:"):
            source_proxy = create_source(SOURCE_TYPE_HDD)
            device, path = parse_hdd_url(url)
            source_proxy.Partition = device
            source_proxy.Directory = path
            return source_proxy

        if any(map(url.startswith, ["http:", "https:", "ftp:", "file:"])):
            source_proxy = create_source(SOURCE_TYPE_URL)

            source_proxy.Configuration = \
                RepoConfigurationData.to_structure(
                    RepoConfigurationData.from_url(url)
                )

            return source_proxy

        raise ValueError("Unknown type of the installation source: {}".format(url))

    def _set_source_configuration_from_opts(self, opts):
        """Configure the source based on the Anaconda options."""
        source_proxy = self.get_source_proxy()

        if source_proxy.Type == SOURCE_TYPE_URL:
            # Get the repo configuration.
            repo_configuration = RepoConfigurationData.from_structure(
                source_proxy.Configuration
            )

            if opts.proxy:
                repo_configuration.proxy = opts.proxy

            if not conf.payload.verify_ssl:
                repo_configuration.ssl_verification_enabled = conf.payload.verify_ssl

            # Update the repo configuration.
            source_proxy.Configuration = \
                RepoConfigurationData.to_structure(repo_configuration)

    def _set_additional_repos_from_opts(self, opts):
        """Set additional repositories based on the Anaconda options."""
        repositories = self.get_repo_configurations()
        existing_names = {r.name for r in repositories}
        additional_repositories = []

        for repo_name, repo_url in opts.addRepo:
            # Check the name of the repository.
            is_unique = repo_name not in existing_names

            if not is_unique:
                log.warning("Repository name %s is not unique. Only the first repo will "
                            "be used!", repo_name)
                continue

            # Generate the configuration data for the new repository.
            data = RepoConfigurationData()
            data.name = repo_name
            data.url = repo_url

            existing_names.add(data.name)
            additional_repositories.append(data)

        if not additional_repositories:
            return

        repositories.extend(additional_repositories)
        self.set_repo_configurations(repositories)

    def _generate_driver_disk_repositories(self):
        """Append generated driver disk repositories."""
        dd_repositories = generate_driver_disk_repositories()

        if not dd_repositories:
            return

        repositories = self.get_repo_configurations()
        repositories.extend(dd_repositories)
        self.set_repo_configurations(repositories)

    def _set_packages_from_opts(self, opts):
        """Configure packages based on the Anaconda options."""
        if opts.multiLib:
            configuration = self.get_packages_configuration()
            configuration.multilib_policy = MULTILIB_POLICY_ALL
            self.set_packages_configuration(configuration)

    @property
    def type(self):
        """The DBus type of the payload."""
        return PAYLOAD_TYPE_DNF

    def get_source_proxy(self):
        """Get the DBus proxy of the RPM source.

        The default source for the DNF payload is set via
        the default_source option in the payload section
        of the Anaconda config file.

        :return: a DBus proxy
        """
        return get_source(self.proxy)

    @property
    def source_type(self):
        """The DBus type of the source."""
        source_proxy = self.get_source_proxy()
        return source_proxy.Type

    def get_repo_configurations(self) -> [RepoConfigurationData]:
        """Get a list of DBus repo configurations."""
        return RepoConfigurationData.from_structure_list(
            self.proxy.Repositories
        )

    def set_repo_configurations(self, data_list: [RepoConfigurationData]):
        """Set a list of DBus repo configurations."""
        self.proxy.Repositories = \
            RepoConfigurationData.to_structure_list(data_list)

    def get_packages_configuration(self) -> PackagesConfigurationData:
        """Get the DBus data with the packages configuration."""
        return PackagesConfigurationData.from_structure(
            self.proxy.PackagesConfiguration
        )

    def set_packages_configuration(self, data: PackagesConfigurationData):
        """Set the DBus data with the packages configuration."""
        self.proxy.PackagesConfiguration = \
            PackagesConfigurationData.to_structure(data)

    def get_packages_selection(self) -> PackagesSelectionData:
        """Get the DBus data with the packages selection."""
        return PackagesSelectionData.from_structure(
            self.proxy.PackagesSelection
        )

    def set_packages_selection(self, data: PackagesSelectionData):
        """Set the DBus data with the packages selection."""
        self.proxy.PackagesSelection = \
            PackagesSelectionData.to_structure(data)

    def is_ready(self):
        """Is the payload ready?"""
        enabled_repos = self._dnf_manager.enabled_repositories

        # If CDN is used as the installation source and we have
        # a subscription attached then any of the enabled repos
        # should be fine as the base repo.
        # If CDN is used but subscription has not been attached
        # there will be no redhat.repo file to parse and we
        # don't need to do anything.
        if self.source_type == SOURCE_TYPE_CDN:
            return self._is_cdn_set_up() and enabled_repos

        # Otherwise, a base repository has to be enabled.
        return any(map(self._is_base_repo, enabled_repos))

    def _is_cdn_set_up(self):
        """Is the CDN source set up?"""
        if not self.source_type == SOURCE_TYPE_CDN:
            return False

        if not is_module_available(SUBSCRIPTION):
            return False

        subscription_proxy = SUBSCRIPTION.get_proxy()
        return subscription_proxy.IsSubscriptionAttached

    def _is_base_repo(self, repo_id):
        """Is it a base repository?"""
        return repo_id == constants.BASE_REPO_NAME \
            or repo_id in constants.DEFAULT_REPOS

    def unsetup(self):
        self._dnf_manager.reset_base()
        tear_down_sources(self.proxy)

    @property
    def needs_network(self):
        """Do the sources require a network?"""
        return self.service_proxy.IsNetworkRequired()

    def _get_proxy_url(self):
        """Get a proxy of the current source.

        :return: a proxy or None
        """
        source_proxy = self.get_source_proxy()
        source_type = source_proxy.Type

        if source_type != SOURCE_TYPE_URL:
            return None

        data = RepoConfigurationData.from_structure(
            source_proxy.Configuration
        )

        return data.proxy

    ###
    # METHODS FOR WORKING WITH REPOSITORIES
    ###

    def _handle_system_repository(self, data):
        """Handle a system repository.

        The user is trying to do "repo --name=updates" in a kickstart file.
        We can only enable or disable the already existing on-disk repo config.

        :raise: SourceSetupError if the system repository is not available
        """
        try:
            self._dnf_manager.set_repository_enabled(data.name, data.enabled)
        except UnknownRepositoryError:
            msg = "The '{}' repository is not one of the pre-defined repositories."
            raise SourceSetupError(msg.format(data.name)) from None

    def _set_up_additional_repository(self, data):
        """Set up sources for the additional repository.

        :param RepoConfigurationData data: a source configuration
        :return RepoConfigurationData: a repository configuration
        """
        # Check the validity of the repository.
        if not data.url:
            msg = _("The '{repository_name}' repository has no mirror, baseurl or metalink set.")
            raise SourceSetupError(msg.format(repository_name=data.name)) from None

        # There is nothing to set up for sources natively supported by DNF.
        if any(data.url.startswith(p) for p in ["file:", "http:", "https:", "ftp:"]):
            return data

        # Set up the NFS source with a substituted URL.
        if data.url.startswith("nfs:"):
            data.url = self._dnf_manager.substitute(
                data.url
            )
            source = NFSSourceModule()
            source.set_configuration(data)
            self._internal_sources.append(source)

            task = SetUpSourcesTask([source])
            task.run()

            return source.repository

        # Set up the HDD source.
        if data.url.startswith("hd:"):
            device_mount = self._create_mount_point(
                ISO_DIR + "-" + data.name + "-hdd-device"
            )
            iso_mount = self._create_mount_point(
                INSTALL_TREE + "-" + data.name + "-hdd-iso"
            )

            partition, directory = parse_hdd_url(data.url)

            task = SetUpHardDriveSourceTask(
                device_mount=device_mount,
                iso_mount=iso_mount,
                partition=partition,
                directory=directory,
            )
            result = task.run()
            data.url = "file://" + result.install_tree_path
            return data

        # Otherwise, raise an error.
        msg = _("The '{repository_name}' repository uses an unsupported protocol.")
        raise SourceSetupError(msg.format(repository_name=data.name)) from None

    def _create_mount_point(self, *paths):
        """Create a mount point from specified paths.

        FIXME: This is a temporary workaround.
        """
        mount_point = join_paths(*paths)
        self._mount_points.append(mount_point)
        return mount_point

    def _tear_down_additional_sources(self):
        """Tear down sources of additional repositories.

        FIXME: This is a temporary workaround.
        """
        while self._mount_points:
            mount_point = self._mount_points.pop()
            task = TearDownMountTask(mount_point)
            task.run()

        while self._internal_sources:
            source = self._internal_sources.pop()
            task = TearDownSourcesTask([source])
            task.run()

    @property
    def space_required(self):
        return calculate_required_space(self._dnf_manager)

    def install(self):
        self._progress_cb(0, _('Starting package installation process'))

        # Get the packages configuration and selection data.
        configuration = self.get_packages_configuration()
        selection = self.get_packages_selection()

        # Add the rpm macros to the global transaction environment
        task = SetRPMMacrosTask(configuration)
        task.run()

        try:
            # Resolve packages.
            task = ResolvePackagesTask(self._dnf_manager, selection)
            task.run()
        except NonCriticalInstallationError as e:
            # FIXME: This is a temporary workaround.
            # Allow users to handle the error. If they don't want
            # to continue with the installation, raise a different
            # exception to make sure that we will not run the error
            # handler again.
            if error_handler.cb(e) == ERROR_RAISE:
                raise InstallationError(str(e)) from e

        # Set up the download location.
        task = PrepareDownloadLocationTask(self._dnf_manager)
        task.run()

        # Download the packages.
        task = DownloadPackagesTask(self._dnf_manager)
        task.progress_changed_signal.connect(self._progress_cb)
        task.run()

        # Install the packages.
        task = InstallPackagesTask(self._dnf_manager)
        task.progress_changed_signal.connect(self._progress_cb)
        task.run()

        # Clean up the download location.
        task = CleanUpDownloadLocationTask(self._dnf_manager)
        task.run()

    def _is_source_default(self):
        """Report if the current source type is the default source type.

        NOTE: If no source was set previously a new default one
              will be created.
        """
        return self.source_type == conf.payload.default_source

    # pylint: disable=arguments-differ
    def setup(self, report_progress, only_on_change=False):
        """Set up the payload.

        :param function report_progress: a callback for a progress reporting
        :param bool only_on_change: restart thread only if existing repositories changed
        """
        # Reset the validation report.
        self._report = ValidationReport()

        # Skip the setup if possible.
        if self._skip_if_no_changed_repositories(only_on_change):
            return

        # It will be necessary to check the software selection again.
        self._software_validation_required = True

        # Download package metadata
        report_progress(_("Downloading package metadata..."))

        try:
            self._update_base_repo()
        except (OSError, SourceSetupError, DNFManagerError) as e:
            self._report.error_messages.append(str(e))
            raise SourceSetupError(str(e)) from e

        # Gather the group data
        report_progress(_("Downloading group metadata..."))
        self.dnf_manager.load_packages_metadata()

        # Check if that failed
        if not self.is_ready():
            msg = _("No base repository is configured.")
            self._report.error_messages.append(msg)
            raise SourceSetupError(msg)

        # run payload specific post configuration tasks
        self.dnf_manager.load_repomd_hashes()

    def _skip_if_no_changed_repositories(self, only_on_change):
        """Have the repositories changed since the last setup?

        If the repositories haven't changed and we are allowed
        to skip the payload setup, return True. Otherwise,
        return False.
        """
        if not only_on_change:
            return False

        log.debug("Testing repositories availability")
        task = VerifyRepomdHashesTask(self.dnf_manager)
        report = task.run()

        if not report.is_valid():
            return False

        log.debug("Payload won't be restarted, repositories are still available.")
        return True

    def _update_base_repo(self):
        """Update the base repository from the DBus source."""
        log.debug("Tearing down sources")
        tear_down_sources(self.proxy)
        self._tear_down_additional_sources()

        log.debug("Preparing the DNF base")
        self._dnf_manager.clear_cache()
        self._dnf_manager.reset_substitution()
        self._dnf_manager.configure_base(self.get_packages_configuration())
        self._dnf_manager.configure_proxy(self._get_proxy_url())
        self._dnf_manager.dump_configuration()
        self._dnf_manager.read_system_repositories()

        log.info("Configuring the base repo")

        # Set up the source.
        set_up_sources(self.proxy)

        # Set up the base repo.
        if self.source_type not in SOURCE_REPO_FILE_TYPES:
            self._add_base_repository()
        else:
            # Remove all treeinfo repositories.
            self._remove_treeinfo_repositories()

            # Otherwise, fall back to the default repos that we disabled above
            self._enable_system_repositories()

        self._include_additional_repositories()
        self._validate_enabled_repositories()

    def _add_base_repository(self):
        """Add the base repository.

        Try to add a valid base repository to the DNF base.

        :raise: DNFManagerError if the repo is invalid
        """
        # Get the repo configuration of the first source.
        data = RepoConfigurationData.from_structure(
            self.proxy.GetRepoConfigurations()[0]
        )
        log.debug("Using the repo configuration: %s", data)

        # Load the treeinfo metadata.
        task = LoadTreeInfoMetadataTask(data)
        result = task.run()

        # Update the repo configuration.
        if result.repository_data:
            data = result.repository_data

        # Update the substitution variables.
        if result.release_version:
            self._dnf_manager.configure_substitution(
                result.release_version
            )

        # Update the treeinfo repositories.
        self.set_repo_configurations(update_treeinfo_repositories(
            repositories=self.get_repo_configurations(),
            treeinfo_repositories=result.treeinfo_repositories,
        ))

        # Add and load the base repository.
        log.debug("Add the base repository at %s.", data.url)
        data.name = constants.BASE_REPO_NAME
        data.enabled = True

        try:
            self._dnf_manager.add_repository(data)
            self._dnf_manager.load_repository(data.name)
        except DNFManagerError as e:
            log.error("The base repository is invalid: %s", str(e))
            self._dnf_manager.remove_repository(data.name)
            raise e

    def _enable_system_repositories(self):
        """Enable system repositories.

        * Restore previously disabled system repositories.
        * Enable or disable system repositories based on the current configuration.
        """
        self._dnf_manager.restore_system_repositories()

        log.debug("Enable or disable updates repositories.")
        updates_enabled = self._get_updates_enabled()
        self._set_repositories_enabled(conf.payload.updates_repositories, updates_enabled)

        log.debug("Disable repositories based on the Anaconda configuration file.")
        self._set_repositories_enabled(conf.payload.disabled_repositories, False)

        if constants.isFinal:
            log.debug("Disable rawhide repositories.")
            self._set_repositories_enabled(["*rawhide*"], False)

    def _get_updates_enabled(self):
        """Are latest updates enabled?"""
        source_proxy = self.get_source_proxy()
        source_type = source_proxy.Type

        if source_type == SOURCE_TYPE_CLOSEST_MIRROR:
            return source_proxy.UpdatesEnabled
        else:
            return False

    def _set_repositories_enabled(self, patterns, enabled):
        """Enable or disable matching repositories.

        :param patterns: a list of patterns to match the repo ids
        :param enabled: True to enable, False to disable
        """
        repo_ids = set()

        for pattern in patterns:
            repo_ids.update(self._dnf_manager.get_matching_repositories(pattern))

        for repo_id in sorted(repo_ids):
            self.dnf_manager.set_repository_enabled(repo_id, enabled)

    def _include_additional_repositories(self):
        """Add additional repositories to DNF."""
        for data in self.get_repo_configurations():
            log.debug("Add the '%s' repository (%s).", data.name, data)

            # A system repository can be only enabled or disabled.
            if data.origin == REPO_ORIGIN_SYSTEM:
                self._handle_system_repository(data)
                return

            # Set up additional sources.
            repository = self._set_up_additional_repository(data)

            # Add a new repository.
            self._dnf_manager.add_repository(repository)

            # Load an enabled repository to check its validity.
            self._dnf_manager.load_repository(repository.name)

    def _validate_enabled_repositories(self):
        """Validate all enabled repositories.

        Collect error messages about invalid repositories.
        All invalid repositories are disabled.

        The user repositories are validated when we add them
        to DNF, so this covers invalid system repositories.
        """
        for repo_id in self.dnf_manager.enabled_repositories:
            try:
                self.dnf_manager.load_repository(repo_id)
            except MetadataError as e:
                self._report.warning_messages.append(str(e))

    def _remove_treeinfo_repositories(self):
        """Remove all old treeinfo repositories before loading new ones.

        Find all repositories added from treeinfo file and remove them.
        After this step new repositories will be loaded from the new link.
        """
        log.debug("Remove all treeinfo repositories.")
        repositories = [
            r for r in self.get_repo_configurations()
            if r.origin != REPO_ORIGIN_TREEINFO
        ]
        self.set_repo_configurations(repositories)

    def post_install(self):
        """Perform post-installation tasks."""
        super().post_install()

        # Write selected kickstart repos to target system
        task = WriteRepositoriesTask(
            sysroot=conf.target.system_root,
            dnf_manager=self.dnf_manager,
            repositories=self.get_repo_configurations(),
        )
        task.run()

        # rpm needs importing installed certificates manually, see rhbz#748320 and rhbz#185800
        task = ImportRPMKeysTask(
            sysroot=conf.target.system_root,
            gpg_keys=conf.payload.default_rpm_gpg_keys
        )
        task.run()

        # Update the DNF configuration.
        task = UpdateDNFConfigurationTask(
            sysroot=conf.target.system_root,
            data=self.get_packages_configuration()
        )
        task.run()

        # Close the DNF base.
        task = ResetDNFManagerTask(
            dnf_manager=self.dnf_manager
        )
        task.run()

    @property
    def kernel_version_list(self):
        return get_kernel_version_list()

    @property
    def software_validation_required(self):
        """Is it necessary to validate the software selection?"""
        return self._software_validation_required

    def check_software_selection(self, selection):
        """Check the software selection.

        :param selection: a packages selection data
        :return ValidationReport: a validation report
        """
        log.debug("Checking the software selection...")

        # Run the validation task.
        task = CheckPackagesSelectionTask(
            dnf_manager=self._dnf_manager,
            selection=selection,
        )

        # Get the validation report.
        report = task.run()

        # This validation is no longer required.
        self._software_validation_required = False

        log.debug("The selection has been checked: %s", report)
        return report
