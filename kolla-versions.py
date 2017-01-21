#!/usr/bin/env python

import datetime
import os
import re
import sys

from jinja2 import Environment, FileSystemLoader
import requests
import yaml

class AttrDict(dict):
    def __init__(self, *args, **kwargs):
        super(AttrDict, self).__init__(*args, **kwargs)
        self.__dict__ = self

RELEASE = "3.0.2"
RELEASE_NAME = "newton"
INDEPENDENT = [
    "gnocchi",
    "kuryr",
    "networking-sfc",
    "rally",
    "tempest"
]
URL_KOLLA_CONFIGURATION = "https://raw.githubusercontent.com/openstack/kolla/%s/kolla/common/config.py" % RELEASE
TEMPLATE = "templates/kolla-versions-template.html.j2"
THIS_DIR = os.path.dirname(os.path.abspath(__file__))

VERSION_NEUTRON_LBAAS_DASHBOARD = "1.0.0"
VERSION_RALLY = "0.7.0"
VERSION_TEMPEST = "14.0.0"

with open("files/betacloud-versions.yml", "r") as fp:
    BETACLOUD_VERSIONS = yaml.load(fp)

r = requests.get(URL_KOLLA_CONFIGURATION, stream=True)
projects = {}

for line in r.iter_lines():
    # check all projects listed in config.py
    if "tar.gz" in line and "requirements" not in line:
        m = re.search("([a-z-]+)-(\d+\.\d+\.\d+).*\.tar\.gz", line)
        project = m.group(1)
        if project == "python-watcher":
            project = "watcher"
        elif project == "kuryr-lib":
            project = "kuryr"
        projects[project] = {}
        projects[project]['used_kolla'] = m.group(2)

        # check if release is independent
        release = RELEASE_NAME
        if project in INDEPENDENT:
            release = "_independent"

        # get latest available release from releases repository
        y = requests.get("https://raw.githubusercontent.com/openstack/releases/master/deliverables/%s/%s.yaml" % (release, project), stream=True)
        if y.status_code == 200:
            d = yaml.load(y.content)
            projects[project]['current'] = d['releases'][-1]['version']
        else:
            projects[project]['current'] = '---'

        # overwrite broken versions
        if project == "rally":
            projects[project]['current'] = VERSION_RALLY
        elif project == "tempest":
            projects[project]['current'] = VERSION_TEMPEST
        elif project == "neutron-lbaas-dashboard":
            projects[project]['current'] = VERSION_NEUTRON_LBAAS_DASHBOARD

        projects[project]['used_betacloud'] = BETACLOUD_VERSIONS.get(project, '---')

# render template
j2_env = Environment(loader=FileSystemLoader(THIS_DIR),
                     trim_blocks=True,
                     autoescape=True)
rendered_html = j2_env.get_template(TEMPLATE).render(
    last_update=datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H:%M:%S'),
    projectnames=sorted(projects),
    projects=projects,
    release=RELEASE,
    release_name=RELEASE_NAME
)

# write output
with open("versions.html", "wb") as fh:
    fh.write(rendered_html)
