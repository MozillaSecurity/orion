# coding: utf-8
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Build matrix for CI tasks"""
from abc import ABC
from itertools import product
from json import dumps as json_dumps
from json import loads as json_loads
from logging import getLogger
from pathlib import Path

from jsonschema import RefResolver, validate
from yaml import safe_load as yaml_load

from . import Taskcluster

LANGUAGES = ["python"]
PLATFORMS = ["linux", "windows"]
VERSIONS = {
    ("python", "linux"): ["2.7", "3.5", "3.6", "3.7", "3.8", "3.9"],
    ("python", "windows"): ["3.8"],
}
IMAGES = {
    ("python", "linux", "2.7"): "ci-py-27",
    ("python", "linux", "3.5"): "ci-py-35",
    ("python", "linux", "3.6"): "ci-py-36",
    ("python", "linux", "3.7"): "ci-py-37",
    ("python", "linux", "3.8"): "ci-py-38",
    ("python", "linux", "3.9"): "ci-py-39",
    ("python", "windows", "3.8"): "ci-py-38-win",
}
SCHEMA_CACHE = {}
LOG = getLogger(__name__)


def _schema_by_name(name):
    for schema in SCHEMA_CACHE.values():
        if schema["title"] == name:
            return schema
    raise RuntimeError(f"Unknown schema name: {name}")  # pragma: no cover


def _validate_schema_by_name(instance, name):
    schema = _schema_by_name(name)
    resolver = RefResolver(None, referrer=None, store=SCHEMA_CACHE)
    return validate(instance=instance, schema=schema, resolver=resolver)


class MatrixJob:
    __slots__ = (
        "env",
        "language",
        "name",
        "platform",
        "require_previous_stage_pass",
        "script",
        "secrets",
        "stage",
        "version",
    )

    def __init__(
        self,
        name,
        language,
        version,
        platform,
        env,
        script,
        stage=1,
        previous_pass=False,
    ):
        self.language = language
        self.version = version
        self.platform = platform
        if name is None:
            self.name = f"{language}/{platform}/{version}"
        else:
            self.name = name
        self.env = env
        self.script = script
        self.stage = stage
        self.require_previous_stage_pass = previous_pass
        self.secrets = []

    @property
    def image(self):
        return IMAGES[(self.language, self.platform, self.version)]

    def check(self):
        assert isinstance(self.name, str), "`name` must be a string"
        assert self.language in LANGUAGES, f"unknown `language`: {self.language}"
        assert self.platform in PLATFORMS, f"unknown `platform`: {self.platform}"
        assert (
            self.language,
            self.platform,
        ) in VERSIONS, (
            f"no versions for language '{self.language}', platform '{self.platform}'"
        )
        assert self.version in VERSIONS[(self.language, self.platform)], (
            f"unknown version '{self.version}' for language '{self.language}', "
            f"platform '{self.platform}'"
        )
        assert isinstance(self.env, dict), "`env` must be a dict"
        assert all(
            isinstance(key, str) for key in self.env
        ), "all `env` keys must be strings"
        assert all(
            isinstance(value, str) for value in self.env.values()
        ), "all `env` values must be strings"
        assert isinstance(self.script, list), "`script` must be a list"
        assert self.script, "`script` must not be empty"
        assert all(
            isinstance(cmd, str) for cmd in self.script
        ), "`script` must be a list of strings"
        for secret in self.secrets:
            assert isinstance(
                secret, CISecret
            ), "`secrets` must be a list of `CISecret` objects"
        assert (
            isinstance(self.stage, int) and self.stage > 0
        ), "`stage` must be a positive integer"
        assert isinstance(
            self.require_previous_stage_pass, bool
        ), "`require_previous_stage_pass` must be a boolean"
        assert (self.language, self.platform, self.version,) in IMAGES, (
            f"no image available for language '{self.language}', "
            f"platform '{self.platform}', version '{self.version}'"
        )

    @classmethod
    def from_json(cls, data):
        if isinstance(data, dict):
            obj = data
        else:
            obj = json_loads(data)
        _validate_schema_by_name(instance=obj, name="MatrixJob")
        result = cls(
            obj["name"],
            obj["language"],
            obj["version"],
            obj["platform"],
            obj["env"],
            obj["script"],
        )
        result.stage = obj["stage"]
        result.require_previous_stage_pass = obj["require_previous_stage_pass"]
        result.secrets.extend(CISecret.from_json(secret) for secret in obj["secrets"])
        result.check()
        return result

    def __str__(self):
        obj = {attr: getattr(self, attr) for attr in self.__slots__}
        obj["secrets"] = ([str(secret) for secret in self.secrets],)
        return json_dumps(obj)

    def matches(
        self, language=None, version=None, platform=None, env=None, script=None
    ):
        if language is not None and self.language != language:
            return False

        if version is not None and self.version != version:
            return False

        if platform is not None and self.platform != platform:
            return False

        if script is not None and self.script != script:
            return False

        if env is not None:
            for var, value in env.items():
                if var not in self.env:
                    return False

                if self.env[var] != value:
                    return False

        return True


class CISecret(ABC):
    __slots__ = ("secret", "key")

    def __init__(self, secret, key=None):
        self.secret = secret
        self.key = key

    def is_alias(self, other):
        """True if other aliases self.

        This currently means type is equal and type-specific fields
        (defined in `__slots__`) are exactly the same.
        """
        if type(self) is not type(other):
            return False
        # intentionally only look at self.__slots__, not super().__slots__
        return all(
            getattr(self, attr) == getattr(other, attr) for attr in self.__slots__
        )

    def get_secret_data(self):
        result = Taskcluster.get_service("secrets").get(self.secret)
        assert "secret" in result, "Missing secret value"
        if self.key is not None:
            assert self.key not in result["secret"], f"Missing secret key: {self.key}"
            return result["secret"][self.key]
        return result["secret"]

    @staticmethod
    def from_json(data):
        if isinstance(data, dict):
            obj = data
        else:
            obj = json_loads(data)  # pragma: no cover
        _validate_schema_by_name(instance=obj, name="CISecret")
        if obj["type"] == "env":
            return CISecretEnv(obj["secret"], obj["name"], key=obj.get("key"))
        if obj["type"] == "file":
            return CISecretFile(obj["secret"], obj["path"], key=obj.get("key"))
        return CISecretKey(
            obj["secret"], hostname=obj.get("hostname"), key=obj.get("key")
        )


class CISecretEnv(CISecret):
    __slots__ = ("name",)

    def __init__(self, secret, name, key=None):
        super().__init__(secret, key)
        self.name = name

    def __str__(self):
        return json_dumps(
            {
                "type": "env",
                "key": self.key,
                "secret": self.secret,
                "name": self.name,
            }
        )


class CISecretFile(CISecret):
    __slots__ = ("path",)

    def __init__(self, secret, path, key=None):
        super().__init__(secret, key)
        self.path = path

    def __str__(self):
        return json_dumps(
            {
                "type": "file",
                "key": self.key,
                "secret": self.secret,
                "path": self.path,
            }
        )

    def write(self):
        data = self.get_secret_data()
        if not isinstance(data, str):
            data = json_dumps(data)
        Path(self.path).write_text(data)


class CISecretKey(CISecret):
    __slots__ = ("hostname",)

    def __init__(self, secret, key=None, hostname=None):
        super().__init__(secret, key)
        self.hostname = hostname

    def __str__(self):
        return json_dumps(
            {
                "type": "key",
                "key": self.key,
                "secret": self.secret,
                "hostname": self.hostname,
            }
        )

    def write(self):
        if self.hostname is not None:
            dest = Path.home() / ".ssh" / f"id_rsa.{self.hostname}"
            with (Path.home() / ".ssh" / "config").open("a") as cfg:
                print(f"Host {self.hostname}", file=cfg)
                print("HostName github.com", file=cfg)
                print(f"IdentityFile ~/.ssh/id_rsa.{self.hostname}", file=cfg)
        else:
            dest = Path.home() / ".ssh" / "id_rsa"
        dest.write_text(self.get_secret_data())
        dest.chmod(0o400)


class CIMatrix:
    __slots__ = ("jobs", "secrets")

    def __init__(self, matrix, branch, is_release):
        """CI Job Matrix.

        See the jsonschema specification.

        *NB* despite being superficially very similar to Travis syntax,
             the semantics are different!

        Matrix expansion has 3 steps:
         - cartesian product of language/version/platform/env/script
         - exclude jobs using jobs.exclude
         - include jobs using jobs.include
        """
        # matrix is language/platform/version
        self.jobs = []
        self.secrets = []
        self._parse_matrix(matrix, branch, is_release)

    def _parse_matrix(self, matrix, branch, is_release):
        _validate_schema_by_name(instance=matrix, name="CIMatrix")

        given = set()
        used = set()

        default_language = None
        if "language" in matrix:
            default_language = matrix["language"]
            given.add("language")

        specified_versions = []
        if "version" in matrix:
            # some language versions are specified
            specified_versions.extend(matrix["version"])
            given.add("version")

        if "platform" in matrix:
            specified_platforms = matrix["platform"]
            given.add("platform")
        else:
            specified_platforms = _schema_by_name("CIMatrix")["properties"]["platform"][
                "default"
            ]

        global_env = {}
        specified_envs = []
        env_name = "env"
        if "env" in matrix:
            envs = matrix["env"]
            if isinstance(envs, dict):
                if "global" in envs:
                    global_env.update(envs["global"])
                envs = envs.get("jobs", [])
                env_name = "env.jobs"
            for env in envs:
                specified_envs.append(env.copy())
            if envs:
                given.add(env_name)

        specified_scripts = []
        if "script" in matrix:
            if all(isinstance(cmd, str) for cmd in matrix["script"]):
                specified_scripts.append(matrix["script"].copy())
            else:
                for idx, script in enumerate(matrix["script"]):
                    specified_scripts.append(script.copy())
            given.add("script")

        # cartesian product of everything specified so far
        if default_language is not None and specified_versions and specified_scripts:
            for platform, version, env, script in product(
                specified_platforms,
                specified_versions,
                specified_envs or [{}],
                specified_scripts,
            ):
                local_env = global_env.copy()
                local_env.update(env)
                self.jobs.append(
                    MatrixJob(
                        None, default_language, version, platform, local_env, script
                    )
                )
            LOG.debug("product created %d jobs", len(self.jobs))
            used |= {"language", "version", "platform", "script", env_name}

        if "secrets" in matrix:
            self.secrets.extend(self._parse_secrets(matrix["secrets"]))

        if "jobs" in matrix:
            # exclude jobs
            if "exclude" in matrix["jobs"]:
                for exclude in matrix["jobs"]["exclude"]:
                    self.jobs = [job for job in self.jobs if not job.matches(**exclude)]
                    LOG.debug("%d jobs after exclude", len(self.jobs))

            # include jobs
            if "include" in matrix["jobs"]:
                for idx, include in enumerate(matrix["jobs"]["include"]):
                    name = include.get("name")

                    if "when" in include:
                        if include["when"].get("release") is not None:
                            if include["when"]["release"] != is_release:
                                continue

                        elif include["when"].get("branch") is not None:
                            if include["when"]["branch"] != branch:
                                continue

                    assert "script" in include or len(specified_scripts) == 1
                    if "script" in include:
                        script = include["script"].copy()
                    else:
                        script = specified_scripts[0]
                        used.add("script")

                    assert "language" in include or default_language is not None
                    if "language" in include:
                        language = include["language"]
                    else:
                        language = default_language
                        used.add("language")

                    assert "platform" in include or len(specified_platforms) == 1
                    if "platform" in include:
                        platform = include["platform"]
                    else:
                        platform = specified_platforms[0]
                        used.add("platform")

                    assert "version" in include or len(specified_versions) == 1
                    if "version" in include:
                        version = include["version"]
                    else:
                        version = specified_versions[0]
                        used.add("version")

                    env = global_env.copy()
                    if "env" in include:
                        env.update(include["env"])

                    job = MatrixJob(
                        name,
                        language,
                        version,
                        platform,
                        env,
                        script,
                    )
                    assert not any(
                        exist.matches(
                            language=job.language,
                            version=job.version,
                            platform=job.platform,
                            env=job.env,
                            script=job.script,
                        )
                        for exist in self.jobs
                    ), f"included job #{idx} already exists"

                    if "secrets" in include:
                        job.secrets.extend(self._parse_secrets(include["secrets"]))

                    if include.get("when", {}).get("all_passed") is not None:
                        job.stage = 2
                        job.require_previous_stage_pass = include["when"]["all_passed"]

                    self.jobs.append(job)

        # check for any unused matrix values and print a warning
        unused = given - used
        if unused:
            missing = {"language", "version", "script"} - given
            if len(unused) > 1:
                keys = "values '" + "', '".join(sorted(unused)) + "were"
            else:
                keys = f"value '{unused.pop()} was"
            LOG.warning(
                "Top-level %s given, but will have no effect without '%s'.",
                keys,
                "', '".join(sorted(missing)),
            )

        for job in self.jobs:
            job.check()

    def _parse_secrets(self, secrets):
        for secret in secrets:
            result = CISecret.from_json(secret)
            assert not any(result.is_alias(secret) for secret in self.secrets)
            yield result


def _load_schema_cache():
    for path in (Path(__file__).parent / "schemas").glob("*.yaml"):
        schema = yaml_load(path.read_text())
        SCHEMA_CACHE[schema["$id"]] = schema


def _validate_globals():
    # validate VERSIONS
    valid_image_keys = []
    for (language, platform), versions in VERSIONS.items():
        assert language in LANGUAGES, f"unknown language in VERSIONS: {language}"
        assert platform in PLATFORMS, f"unknown platform in VERSIONS: {platform}"
        valid_image_keys.extend((language, platform, version) for version in versions)
    # validate IMAGES
    missing_images = ["/".join(img) for img in set(valid_image_keys) - set(IMAGES)]
    assert not missing_images, (
        "IMAGES: missing images for: " f"[{', '.join(missing_images)}]"
    )
    extra_images = ["/".join(img) for img in set(IMAGES) - set(valid_image_keys)]
    assert not extra_images, (
        "IMAGES: unnecessary images given: " f"[{', '.join(extra_images)}]"
    )


_load_schema_cache()
del _load_schema_cache
_validate_globals()
del _validate_globals
