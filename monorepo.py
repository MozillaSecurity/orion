#!/usr/bin/env python3
# coding: utf-8
'''
A script that aids in building and publishing multiple 🐳 containers as microservices within a single repository,
aka monorepo.
'''

__author__ = 'Christoph Diehl <cdiehl@mozilla.com>'

import os
import sys
import logging
import argparse
import subprocess


class Common():
    """Common methods and functions shared across CI and CD.
    """

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)

    @staticmethod
    def get_service(folder):
        dockerfile = os.path.join(folder, 'Dockerfile')
        service = os.path.split(os.path.dirname(dockerfile))[-1]
        return [service, dockerfile]

    @staticmethod
    def find_services(root):
        folders = []
        for dirpath, _, files in os.walk(root):
            for fname in files:
                if fname == 'Dockerfile':
                    folders.append(dirpath)
        return folders


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

    def build(self):
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
        self.logger.info('Pushing image for %s', self.service)
        subprocess.check_call([
            'docker', 'push',
            '{}/{}:latest'.format(DockerHub.ORG, self.service)
        ])
        subprocess.check_call([
            'docker', 'push',
            '{}/{}:{}'.format(DockerHub.ORG, self.service, self.version)
        ])


class Git(Common):
    """Git utility class.
    """

    def __init__(self):
        super().__init__()

    @staticmethod
    def revision():
        return subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD']).strip().decode('utf-8')


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

    def has_trigger(self, commit_range, path='.'):
        self.logger.info('Finding containers that changed in "%s"', commit_range)
        diff = subprocess.check_output(['git', 'diff', '--name-only', commit_range, path]).split()

        folders = {
            os.path.dirname(line).decode('utf-8') for line in diff if os.path.dirname(line)
        }
        self.logger.info('The following folders contain changes: %s', folders)
        return folders

    def deliver(self, folder, options):
        [service, dockerfile] = self.get_service(folder)
        version = 'nightly' if self.is_cron else Git.revision()
        if os.path.exists(dockerfile):
            docker = DockerHub(dockerfile, service, version)
            if options.build:
                docker.build()

            if options.deliver \
                and self.is_pull_request == 'false' \
                and self.branch == 'master':
                docker.push()

    def run(self, options):
        if self.is_cron:
            # This is a cron task, we rebuild and publish every found image.
            for folder in self.find_services(options.path):
                self.deliver(folder, options)
        else:
            if not self.commit_range:
                self.logger.warning('Could not find a commit range - not doing anything.')
                return
            # We only rebuild and publish each image which has new changes.
            for folder in self.has_trigger(self.commit_range, options.path):
                self.deliver(folder, options)


class MonorepoManager():
    """Command-line interface for MonorepoManager.
    """

    @staticmethod
    def parse_args():
        parser = argparse.ArgumentParser(
            add_help=False,
            description='Monorepo Manager',
            epilog='The exit status is 0 for non-failures and -1 for failures.',
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
            prog='Monorepo'
        )

        m = parser.add_argument_group('Mandatory Arguments')
        m.add_argument('-ci',
                       metavar='backend',
                       type=str,
                       help='Name of the used CI backend.')

        o = parser.add_argument_group('Optional Arguments')
        o.add_argument('-path',
                       type=str,
                       default=os.path.relpath(os.getcwd()),
                       help='Set folder explicitly.')
        o.add_argument('-build',
                       action='store_true',
                       default=True,
                       help='Build Docker images')
        o.add_argument('-deliver',
                       action='store_true',
                       default=False,
                       help='Push Docker images')
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
        logging.basicConfig(format='[Monorepo] %(name)s (%(funcName)s) %(levelname)s: %(message)s',
                            level=logging.DEBUG)

        args = cls.parse_args()

        if args.ci == 'travis':
            Travis().run(args)


if __name__ == '__main__':
    sys.exit(MonorepoManager.main())
