#!/usr/bin/env python

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import logging
import os
import re
import sys

from distutils.version import LooseVersion
import docker
import jinja2
import requests
import yaml

class AttrDict(dict):
    def __init__(self, *args, **kwargs):
        super(AttrDict, self).__init__(*args, **kwargs)
        self.__dict__ = self


def cleanup_version(version):
    # some git tags include a leading v, e.g. v5.1.2
    # the 'v' has to be removed
    if version.startswith("v"):
        version = version[1:]

    # some git tags include a leading r, e.g. r2.6.8
    # the 'r' has to be removed
    if version.startswith("r"):
        version = version[1:]

    # some ubuntu packages include a version postfix -, e.g. 3.6.6-1
    # the '-...' has to be removed
    if "-" in version:
        version, _, _ = version.partition('-')

    # some ubuntu packages include a version postfix +, e.g. 10.1.21+maria-1~xenial
    # the '+...' has to be removed
    if "+" in version:
        version, _, _ = version.partition('+')

    # some ubuntu packages include a version prefix :, e.g. 1:2.6.10
    # the '...:' has to be removed
    if ":" in version:
        _, _, version = version.partition(':')

    return version


def get_version_from_anitya(project, series=None):
    if project == "mariadb":
        project = "mariadb-galera"

    r = requests.post(URL_ANITYA_API, data={"id": ANITYA_IDS[project]})

    if series:
        versions = [LooseVersion(cleanup_version(v)) for v in r.json().get('versions') if cleanup_version(v).startswith(series)]
        version = str(versions[0])
    else:
        version = r.json().get("version")

    return version


def get_version_from_docker_image(namespace, project, tag, registry=""):

    # change package names
    # FIXME: move this into a configuration file
    if project == "rabbitmq":
        package = "rabbitmq-server"
    elif project == "mariadb":
        # NOTE: name will change to mariadb-server with 10.1
        package = "mariadb-galera-server"
    elif project == "mongodb":
        package = "mongodb-server"
    else:
        package = project

    if registry:
        image = "%s/%s/ubuntu-source-%s:%s" % (registry, namespace, project, tag)
    else:
        image = "%s/ubuntu-source-%s:%s" % (namespace, project, tag)

    LOG.info("pulling image %s" % image)
    DOCKER.images.pull(image)

    LOG.info("running image %s" % image)
    version = DOCKER.containers.run(
        image,
        "dpkg-query --showformat='${Version}' --show %s" % package,
        name=project,
        remove=True
    )
    LOG.info("got version %s for %s" % (version.rstrip(), project))
    LOG.info("removing image %s" % image)
    DOCKER.images.remove(image)
    return version.rstrip()


def get_latest_tag_from_docker_image(registry, namespace, project):
    url = "https://%s/v1/repositories/%s/ubuntu-source-%s/tags" % (registry, namespace, project)

    r = requests.get(url)
    versions = [LooseVersion(v) for v in r.json().keys()]
    versions.sort()
    return versions[-1]


# configure logging

LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
formatter = logging.Formatter(LOG_FORMAT)
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
LOG = logging.getLogger(__name__)
LOG.addHandler(stream_handler)
LOG.setLevel(logging.INFO)

# load configuration

FILE_CONFIGURATION = "files/configuration.yml"
with open(FILE_CONFIGURATION, "r") as fp:
    CONFIGURATION = yaml.load(fp)

# some static parameters

FILE_ANITYA_IDS = "files/anitya-ids.yml"
FILE_VERSIONS = "files/versions.yml"
FILE_TEMPLATE = "kolla-versions-template.html.j2"
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
URL_ANITYA_API = "https://release-monitoring.org/api/version/get"
URL_KOLLA_CONFIGURATION = "https://raw.githubusercontent.com/openstack/kolla/%s/kolla/common/config.py" % CONFIGURATION["kolla_release"]

# load anitya ids

with open(FILE_ANITYA_IDS, "r") as fp:
    ANITYA_IDS = yaml.load(fp)

# get docker client

DOCKER = docker.DockerClient(base_url="unix:///var/run/docker.sock")

# check openstack projects

with open(FILE_VERSIONS, "r") as fp:
    VERSIONS = yaml.load(fp)

r = requests.get(URL_KOLLA_CONFIGURATION, stream=True)
openstack_projects = {}

for line in r.iter_lines():
    # check all projects listed in config.py
    if "tar.gz" in line and "requirements" not in line:
        m = re.search("([a-z-]+)-(\d+\.\d+\.\d+).*\.tar\.gz", line)
        project = m.group(1)
        if project == "python-watcher":
            project = "watcher"
        elif project == "kuryr-lib":
            project = "kuryr"
        openstack_projects[project] = {}
        openstack_projects[project]['kolla'] = m.group(2)

        # check if release is independent
        release = CONFIGURATION["openstack_release"]
        if project in CONFIGURATION["independent_projects"]:
            release = "_independent"

        # get latest available release from releases repository
        y = requests.get("https://raw.githubusercontent.com/openstack/releases/master/deliverables/%s/%s.yaml" % (release, project), stream=True)
        if y.status_code == 200:
            d = yaml.load(y.content)
            openstack_projects[project]['current'] = d['releases'][-1]['version']
        else:
            openstack_projects[project]['current'] = '-'

        # overwrite broken versions
        if project == "rally":
            openstack_projects[project]['current'] = CONFIGURATION["versions"]["rally"]
        elif project == "tempest":
            openstack_projects[project]['current'] = CONFIGURATION["versions"]["tempest"]
        elif project == "neutron-lbaas-dashboard":
            openstack_projects[project]['current'] = CONFIGURATION["versions"]["neutron_lbaas_dashboard"]

        openstack_projects[project]['betacloud'] = VERSIONS["openstack"].get(project, '-')

# check service projects

service_projects = {}

betacloud_release = get_latest_tag_from_docker_image("quay.io", "betacloud", "kolla-toolbox")
LOG.info("latest available betacloud docker image tag is %s" % betacloud_release)

for project in VERSIONS["services_kolla"]:
    service_projects[project] = {}

    if project == "mariadb":
        series = "10.0"
    elif project == "mongodb":
        series = "2.6"
    else:
        series = None

    current = get_version_from_anitya(project, series)

    kolla = get_version_from_docker_image("kolla", project, CONFIGURATION["kolla_release"])

    betacloud = get_version_from_docker_image("betacloud", project, betacloud_release, registry="quay.io")

    service_projects[project]["current"] = cleanup_version(current)
    service_projects[project]["kolla"] = cleanup_version(kolla)
    service_projects[project]["betacloud"] = cleanup_version(betacloud)

# render template

j2_env = jinja2.Environment(loader=jinja2.FileSystemLoader("templates"),
                            trim_blocks=True,
                            autoescape=True)
rendered_html = j2_env.get_template(FILE_TEMPLATE).render(
    last_update=datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H:%M:%S'),
    openstack_project_names=sorted(openstack_projects),
    openstack_projects=openstack_projects,
    release=CONFIGURATION["kolla_release"],
    betacloud_release=betacloud_release,
    release_name=CONFIGURATION["openstack_release"],
    service_projects=service_projects,
    service_project_names=VERSIONS["services_kolla"]
)

# write output

with open("versions.html", "wb") as fh:
    fh.write(rendered_html)
