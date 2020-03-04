#!/usr/bin/env python3
# coding: utf-8
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
A script that aids in building and publishing multiple 🐳 containers as microservices within a
single repository aka monorepo.
"""

__author__ = "Christoph Diehl <cdiehl@mozilla.com>"
__version__ = "2.0.0"

import os
import sys
import json
import logging
import argparse
import subprocess
import http.client

try:
    import yaml
except ImportError as error:
    print("Consider: pip3 install -r requirements.txt")
    sys.exit(1)


class MonorepoManagerException(Exception):
    """Exception class for Monorepo Manager."""


class Common:
    """Common methods and functions shared across CI and CD.
    """

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)

    @classmethod
    def get_service_in_hierarchy(cls, folder):
        """Locates a service in an arbitrary large hierarchy and determines the service.
        """
        service_path = cls.find_service_in_parent(folder)
        if service_path is None:
            return None
        return os.path.join(service_path, "service.yaml")

    @classmethod
    def find_service_in_parent(cls, folder):
        """Searches backwards in the hierarchy to find the service containing the Dockerfile.
        """
        content = os.listdir(folder)
        if "service.yaml" in content:
            return folder
        folders = folder.split(os.sep)
        if len(folders) > 1:
            folders.pop()
            return cls.find_service_in_parent(os.sep.join(folders))
        return None

    @classmethod
    def find_services(cls, root):
        """Searches forward to find all services. Usually used in cron tasks to rebuild every container.
        """
        folders = []
        for dirpath, _, files in os.walk(root):
            for fname in files:
                if fname == "service.yaml":
                    folders.append(dirpath)
        return folders

    @classmethod
    def is_test(cls, folder):
        """Whether the folder is a container structure test folder.
        """
        return os.path.basename(folder) == "tests"

    @classmethod
    def read_service_metadata(cls, filename="service.yaml"):
        """Reads the metadata information file of the service.
        """
        if os.path.isfile(filename):
            with open(filename) as fo:
                return yaml.safe_load(fo.read())
        return None


class CI(Common):
    """CI base class.
    """


class CD(Common):
    """CD base class.
    """


class DockerHub(CD):
    """DockerHub auxiliary class.
    """

    ORG = os.environ.get("DOCKER_ORG")

    def __init__(self, dockerfile, image_name, version):
        super().__init__()
        self.dockerfile = dockerfile
        self.image_name = image_name
        self.version = version
        self.tags = []
        self.root = os.path.abspath(os.path.dirname(self.dockerfile))
        self.repository = "{}/{}".format(DockerHub.ORG, self.image_name)

    def build(self, arch="", options=None):
        """Builds a Docker image.
        """
        self.logger.info("Building image for service: %s", self.dockerfile)

        build_args = None
        if options:
            build_args = options.get("build_args")

        version_prefix = ""
        if arch:
            version_prefix = arch + "-"

        version1 = "{}{}".format(version_prefix, self.version)
        version2 = "{}{}".format(version_prefix, "latest")

        self.tags.append("{}:{}".format(self.repository, version1))
        self.tags.append("{}:{}".format(self.repository, version2))

        # Generate the build command.
        # fmt: off
        command = [
            "docker",
            "build",
            "--pull",
            "--no-cache",
            "--compress",
            "-t", self.tags[0],
            "-t", self.tags[1],
            "-f", self.dockerfile,
        ]
        # fmt: on
        if build_args:
            for arg in build_args:
                command.extend(["--build-arg", arg])
        command.append(self.root)

        self._run(command)

    def push(self):
        """Pushes docker image with defined tag and tag latest to registry.
        """
        self.logger.info("Pushing image for service '%s' to registry.", self.image_name)

        for tag in self.tags:
            self._run(["docker", "push", tag])

    def manifest(self, path):
        self._run(path.split())

    def test(self, arch=None):
        """Runs structural container tests against an image.
        """
        self.logger.info("Testing container integrity of image: %s", self.image_name)

        # Do we have a |tests| folder for this service?
        testpath = os.path.join(self.root, "tests")
        if not os.path.isdir(testpath):
            return

        # Collect all container test configurations.
        confs = []
        for filename in os.listdir(testpath):
            if filename.endswith("_test.yaml") or filename.endswith("_test.yml"):
                confs.append(os.path.join("/tmp/tests", filename))
        if not confs:
            return

        # Build the command which will fetch and run the container-structure-test image.
        version = "{}-latest".format(arch) if arch else "latest"
        # fmt: off
        command = [
            "docker", "run", "--rm",
            "-v", "/var/run/docker.sock:/var/run/docker.sock",
            "-v", "{}/:/tmp/tests/".format(testpath),
            "gcr.io/gcp-runtimes/container-structure-test:latest",
            "test",
            "--image", "{}:{}".format(self.repository, version),
        ]
        # fmt: on
        for name in confs:
            command.extend(["--config", name])

        # Run the tests.
        self._run(command)

    def _run(self, command):
        self.logger.debug(command)
        try:
            subprocess.check_call(command)
        except subprocess.CalledProcessError as error:
            raise MonorepoManagerException(error)


class Git(Common):
    """Git utility class.
    """

    @staticmethod
    def revision():
        """Returns the HEAD revision id of the repository.
        """
        command = ["git", "rev-parse", "--short", "HEAD"]
        return subprocess.check_output(command).strip().decode("utf-8")

    def has_trigger(self, commit_range, path="."):
        """Returns folders which changed within a commit range.
        """
        commits = subprocess.check_output(["git", "show", "--shortstat", commit_range]).decode("utf-8")

        # look in commit message for a force-rebuild command
        if "/force-rebuild" in commits:
            self.logger.info("/force-rebuild command found.")
            return self.find_services(path)

        self.logger.info('Finding containers that changed in "%s"', commit_range)

        command = ["git", "diff", "--name-only", commit_range, path]
        diff = subprocess.check_output(command).split()

        folders = {
            os.path.dirname(line).decode("utf-8")
            for line in diff
            if os.path.dirname(line)
        }
        self.logger.info("The following folders contain changes: %s", folders)

        return folders


class Travis(CI):
    """Travis CI helper class.

    Requires the following environment variables to be set:

        TRAVIS_COMMIT_RANGE - Used to find out which images changed since the last commit.
        TRAVIS_PULL_REQUEST - If set to true, we shall not push images to the Docker registry.
        TRAVIS_BRANCH       - We only want to push images for builds on the master branch.
        TRAVIS_EVENT_TYPE   - In case of a cron task we want to force build nightlies.
    """

    PUSH_BRANCH = "master"

    def __init__(self):
        super().__init__()
        # fmt: off
        self.commit_range = os.environ.get("TRAVIS_COMMIT_RANGE", "").replace("...", "..")
        self.is_cron = os.environ.get("TRAVIS_EVENT_TYPE") == "cron"
        self.is_pull_request = os.environ.get("TRAVIS_PULL_REQUEST")
        self.branch = os.environ.get("TRAVIS_BRANCH")
        # fmt: on

    def start(self, service_dir, options, version):
        """Runs the build process and optionally tests and pushes to the registry.
        """
        service_file = os.path.join(service_dir, "service.yaml")
        if not os.path.isfile(service_file):
            self.logger.error("Meta information missing for: %s", service_dir)
            return
        logging.info("Reading service meta information from: %s", service_file)
        metadata = self.read_service_metadata(service_file)
        if not metadata:
            self.logger.error("No valid meta information in: %s", service_file)
            return

        # Global settings
        image_name = metadata.get("name")
        architectures = metadata.get("arch", [])
        manifest = metadata.get("manifest")

        # Sanitiy checking
        if not image_name:
            self.logger.error("A name for the image must be given.")
            return
        if len(architectures) > 1 and not manifest:
            self.logger.error("Multiple architectures provided but no manifest given.")
            return

        if architectures:
            for arch, arch_opts in architectures.items():
                # Local settings
                dockerfile = None
                if arch_opts:
                    dockerfile = architectures[arch].get("dockerfile")
                dockerfile = os.path.join(service_dir, dockerfile or "Dockerfile")

                docker = DockerHub(dockerfile, image_name, version)
                if options.build:
                    docker.build(arch, arch_opts)

                if options.test:
                    docker.test(arch)

                # fmt: off
                if options.deliver:
                    if self.is_pull_request == "false" and self.branch == self.PUSH_BRANCH:
                        docker.push()
                # fmt: on
        else:
            dockerfile = os.path.join(service_dir, "Dockerfile")

            docker = DockerHub(dockerfile, image_name, version)
            if options.build:
                docker.build()

            if options.test:
                docker.test()

            # fmt: off
            if options.deliver:
                if self.is_pull_request == "false" and self.branch == self.PUSH_BRANCH:
                    docker.push()
            # fmt: on

        if manifest:
            docker.manifest(manifest)

    def run(self, options):
        """Initiates the CI/CD run at Travis.
        """
        version = "nightly" if self.is_cron else Git.revision()
        if self.is_cron:
            # This is a cron task.
            # We rebuild and optionally publish every found service.
            for service_dir in self.find_services(options.path):
                self.start(os.path.abspath(service_dir), options, version)
        else:
            if not self.commit_range:
                raise MonorepoManagerException(
                    "Could not find a commit range - aborting."
                )
            # We only rebuild and optionally publish each service which has new changes.
            for folder in Git().has_trigger(self.commit_range, options.path):
                if self.is_test(folder):
                    # Test folders do not qualify for rebuilds.
                    self.logger.debug("Folder %s is a test folder - ignoring.", folder)
                    continue
                self.start(folder, options, version)


class TravisAPI(CI):
    """Travis CI REST API bridge for local build managment.

    To obtain a Travis token run either:

        travis login --org | --com
        travis token --org | --com

    or visit: https://travis-ci.org/profile
    """

    def run(self, options, branch="master"):
        """Triggers a build at Travis CI with the Travis REST API.
        """
        if not hasattr(options, "token") or not options.token:
            raise MonorepoManagerException("No Travis token provided.")

        tld = "com" if options.pro else "org"
        url = "api.travis-ci.{0}".format(tld)
        repo = options.repo.replace("/", "%2F")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Travis-API-Version": 3,
            "Authorization": "token {0}".format(options.token),
        }
        conf = options.conf.read()
        request = {
            "request": {
                "branch": branch,
                "config": json.loads(json.dumps(yaml.safe_load(conf))),
            }
        }
        params = json.dumps(request)

        connection = http.client.HTTPSConnection(url)
        self.logger.debug("Sending HTTP headers: %s", headers)
        self.logger.debug("Sending request body: %s", params)
        connection.request("POST", "/repo/{0}/requests".format(repo), params, headers)

        response = connection.getresponse()
        self.logger.info(response.read().decode())


class MonorepoManager:
    """Command-line interface for MonorepoManager.
    """

    HOME = os.path.dirname(os.path.abspath(__file__))

    @classmethod
    def parse_args(cls):
        """Arguments for the MonorepoManager.
        """
        parser = argparse.ArgumentParser(
            add_help=False,
            description="Monorepo Manager",
            epilog="The exit status is 0 for non-failures and 1 for failures.",
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
            prog="Monorepo",
        )

        # fmt: off
        m = parser.add_argument_group('Mandatory Arguments')  # pylint: disable=invalid-name
        m.add_argument('-ci',
                       required=True,
                       metavar='backend',
                       type=str,
                       help='Name of the used CI backend.')

        o = parser.add_argument_group('Optional Arguments')  # pylint: disable=invalid-name
        o.add_argument('-path',
                       type=str,
                       default=os.path.relpath(os.getcwd()),
                       help='Set folder explicitly.')
        o.add_argument('-build',
                       action='store_true',
                       default=False,
                       help='Build Docker images')
        o.add_argument('-deliver',
                       action='store_true',
                       default=False,
                       help='Push Docker images')
        o.add_argument('-test',
                       action='store_true',
                       default=False,
                       help='Test Docker containers')
        o.add_argument('-token',
                       type=str,
                       default='',
                       help='Travis API token')
        o.add_argument('-repo',
                       type=str,
                       default='mozillasecurity/orion',
                       help='Travis repository slug')
        o.add_argument('-pro',
                       action='store_true',
                       default=False,
                       help='Travis professional account')
        o.add_argument('-conf',
                       metavar='path',
                       type=argparse.FileType(),
                       default=os.path.join(cls.HOME, '.travis.yml'),
                       help='Travis build configuration')
        o.add_argument('-h', '-help', '--help',
                       action='help',
                       help=argparse.SUPPRESS)
        o.add_argument('-version',
                       action='version',
                       version='%(prog)s rev {}'.format(Git.revision()),
                       help=argparse.SUPPRESS)
        # fmt: on
        return parser.parse_args()

    @classmethod
    def main(cls):
        """Entrypoint for the MonorepoManager.
        """
        logging.basicConfig(
            format="[Monorepo] %(name)s (%(funcName)s) %(levelname)s: %(message)s",
            level=logging.DEBUG,
        )

        args = cls.parse_args()

        if args.ci == "travis":
            try:
                Travis().run(args)
            except MonorepoManagerException as msg:
                logging.error(msg)
                return 1

        if args.ci == "travis-api":
            try:
                TravisAPI().run(args)
            except MonorepoManagerException as msg:
                logging.error(msg)
                return 1

        return 0


if __name__ == "__main__":
    sys.exit(MonorepoManager.main())
