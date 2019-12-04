#!/usr/bin/env python3
# coding: utf-8
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
A script that aids in building and publishing multiple 🐳 containers as microservices within a single repository,
aka monorepo.
"""

__author__ = 'Christoph Diehl <cdiehl@mozilla.com>'

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
    def get_service(cls, folder):
        """The child folder within its parent folder is usually the service containing the Dockerfile.
        """
        service = os.sep.join(folder.split(os.sep)[0:2])
        dockerfile = os.path.join(service, 'Dockerfile')
        service_name = folder.split(os.sep)[1]
        return service_name, dockerfile

    @classmethod
    def get_service_in_hierarchy(cls, folder):
        """Locates a service in an arbitrary large hierarchy and determines the service name.
        """
        service_path = cls.find_service_in_parent(folder)
        if service_path is None:
            return None, None
        service_name = service_path.rstrip(os.sep).split(os.sep)[-1]
        dockerfile = os.path.join(service_path, 'Dockerfile')
        return service_name, dockerfile

    @classmethod
    def find_service_in_parent(cls, folder):
        """Searches backwards in the hierarchy to find the service containing the Dockerfile.
        """
        content = os.listdir(folder)

        if 'Dockerfile' in content:
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
                if fname == 'Dockerfile':
                    folders.append(dirpath)
        return folders

    @classmethod
    def is_test(cls, folder):
        """Whether the folder is a container structure test folder.
        """
        return os.path.basename(folder) == 'tests'


class CI(Common):
    """CI base class.
    """

    def __init__(self):
        super().__init__()


class CD(Common):
    """CD base class.
    """

    def __init__(self):
        super().__init__()


class DockerHub(CD):
    """DockerHub helper class.
    """

    ORG = os.environ.get('DOCKER_ORG')

    def __init__(self, dockerfile, service, version):
        super().__init__()
        self.dockerfile = dockerfile
        self.service = service
        self.version = version
        self.root = os.path.abspath(os.path.dirname(self.dockerfile))

    def build(self):
        """Builds docker image with tags.
        """
        self.logger.info('Building image for %s', self.dockerfile)
        subprocess.check_call([
            'docker', 'build',
            '--pull',
            '--compress',
            '-t', '{}/{}:{}'.format(DockerHub.ORG, self.service, self.version),
            '-t', '{}/{}:latest'.format(DockerHub.ORG, self.service),
            '-f', self.dockerfile,
            os.path.dirname(self.dockerfile)
        ])

    def push(self):
        """Pushes docker image with defined tag and tag latest to registry.
        """
        self.logger.info('Pushing image for %s', self.service)
        subprocess.check_call([
            'docker', 'push',
            '{}/{}:latest'.format(DockerHub.ORG, self.service)
        ])
        subprocess.check_call([
            'docker', 'push',
            '{}/{}:{}'.format(DockerHub.ORG, self.service, self.version)
        ])

    def test(self):
        """Runs structural container tests against an image.
        """
        self.logger.info('Testing container %s', self.service)

        # Do we have a |tests| folder for this service?
        testpath = os.path.join(self.root, 'tests')
        if not os.path.isdir(testpath):
            return

        # Collect all test YAML configurations.
        confs = []
        for filename in os.listdir(testpath):
            if filename.endswith('_test.yaml') or filename.endswith('_test.yml'):
                confs.append(os.path.join('/tmp/tests', filename))
        if not confs:
            return

        # Build the command which will fetch and run the container-structure-test image.
        command = [
            'docker', 'run', '--rm',
            '-v', '/var/run/docker.sock:/var/run/docker.sock',
            '-v', '{}/:/tmp/tests/'.format(testpath),
            'gcr.io/gcp-runtimes/container-structure-test:latest',
            'test',
            '--quiet',
            '--image', '{}/{}:latest'.format(DockerHub.ORG, self.service)
        ]
        for name in confs:
            command.append('--config')
            command.append(name)

        self.logger.info(command)
        try:
            subprocess.check_call(command)
        except subprocess.CalledProcessError as err:
            raise MonorepoManagerException(err)


class Git(Common):
    """Git utility class.
    """

    def __init__(self):
        super().__init__()

    @staticmethod
    def revision():
        """Returns the HEAD revision id of the repository.
        """
        return subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD']).strip().decode('utf-8')

    def has_trigger(self, commit_range, path='.'):
        """Returns folders which changed within a commit range.
        """
        commits = subprocess.check_output(['git', 'show', '--shortstat', commit_range]).decode('utf-8')

        # look in commit message for a force-rebuild command
        if '/force-rebuild' in commits:
            self.logger.info('/force-rebuild command found.')
            return self.find_services(path)

        self.logger.info('Finding containers that changed in "%s"', commit_range)
        diff = subprocess.check_output(['git', 'diff', '--name-only', commit_range, path]).split()

        folders = {
            os.path.dirname(line).decode('utf-8') for line in diff if os.path.dirname(line)
        }
        self.logger.info('The following folders contain changes: %s', folders)

        return folders


class Travis(CI):
    """Travis CI helper class.

    Requires the following environment variables to be set:

        TRAVIS_COMMIT_RANGE - Used to find out which images changed since the last commit.
        TRAVIS_PULL_REQUEST - If set to true, we shall not push images to the Docker registry.
        TRAVIS_BRANCH       - We only want to push images for builds on the master branch.
        TRAVIS_EVENT_TYPE   - In case of a cron task we want to force build nightlies.
    """

    def __init__(self):
        super().__init__()
        self.commit_range = os.environ.get('TRAVIS_COMMIT_RANGE', '').replace('...', '..')
        self.is_cron = os.environ.get('TRAVIS_EVENT_TYPE') == 'cron'
        self.is_pull_request = os.environ.get('TRAVIS_PULL_REQUEST')
        self.branch = os.environ.get('TRAVIS_BRANCH')

    def deliver(self, folder, options, version):
        """Runs the build process and optionally tests and pushes it to the registry.
        """
        service, dockerfile = self.get_service_in_hierarchy(folder)
        if not dockerfile:
            self.logger.error('Service "%s" contains no Dockerfile!', service)
            return

        docker = DockerHub(dockerfile, service, version)
        if options.build:
            docker.build()

        if options.test:
            docker.test()

        if options.deliver \
                and self.is_pull_request == 'false' \
                and self.branch == 'master':
            docker.push()

    def run(self, options):
        """Initiates the CI/CD run at Travis.
        """
        version = 'nightly' if self.is_cron else Git.revision()
        if self.is_cron:
            # This is a cron task. We rebuild and optionally publish every found service!
            for folder in self.find_services(options.path):
                self.deliver(folder, options, version)
        else:
            if not self.commit_range:
                raise MonorepoManagerException('Could not find a commit range - not doing anything.')
            # We only rebuild and optionally publish each service which has new changes.
            for folder in Git().has_trigger(self.commit_range, options.path):
                if self.is_test(folder):
                    # Test folders do not qualify for rebuilds.
                    self.logger.debug('Folder %s is test folder, ignoring.', folder)
                    continue
                self.deliver(folder, options, version)


class TravisAPI(CI):
    """Travis CI REST API bridge for local build managment.

    To obtain a Travis token run either:

        travis login --org | --com
        travis token --org | --com

    or visit: https://travis-ci.org/profile
    """

    def __init__(self):
        super().__init__()

    def run(self, options, branch="master"):
        """Triggers a build at Travis CI with the Travis REST API.
        """
        if not hasattr(options, 'token') or not options.token:
            raise MonorepoManagerException('No Travis token provided.')

        tld = 'com' if options.pro else 'org'
        url = 'api.travis-ci.{0}'.format(tld)
        repo = options.repo.replace('/', '%2F')
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Travis-API-Version': 3,
            'Authorization': 'token {0}'.format(options.token)
        }
        conf = options.conf.read()
        request = {
            'request': {
                'branch': branch,
                'config': json.loads(json.dumps(yaml.safe_load(conf)))
            }
        }
        params = json.dumps(request)

        connection = http.client.HTTPSConnection(url)
        self.logger.debug('Sending HTTP headers: %s', headers)
        self.logger.debug('Sending request body: %s', params)
        connection.request('POST', '/repo/{0}/requests'.format(repo), params, headers)

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
            description='Monorepo Manager',
            epilog='The exit status is 0 for non-failures and 1 for failures.',
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
            prog='Monorepo'
        )

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

        return parser.parse_args()

    @classmethod
    def main(cls):
        """Entrypoint for the MonorepoManager.
        """
        logging.basicConfig(format='[Monorepo] %(name)s (%(funcName)s) %(levelname)s: %(message)s',
                            level=logging.DEBUG)

        args = cls.parse_args()

        if args.ci == 'travis':
            try:
                Travis().run(args)
            except MonorepoManagerException as msg:
                logging.error(msg)
                return 1

        if args.ci == 'travis-api':
            try:
                TravisAPI().run(args)
            except MonorepoManagerException as msg:
                logging.error(msg)
                return 1

        return 0


if __name__ == '__main__':
    sys.exit(MonorepoManager.main())
