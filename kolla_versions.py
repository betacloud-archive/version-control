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

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
INDEPENDENT = ["gnocchi", "kuryr", "rally", "tempest", "networking-sfc"]
RELEASE = "newton"
URL = "https://raw.githubusercontent.com/openstack/kolla/stable/%s/kolla/common/config.py" % RELEASE
r = requests.get(URL, stream=True)

projects = {}

for line in r.iter_lines():
    if "tar.gz" in line and "requirements" not in line:
        m = re.search("([a-z-]+)-(\d+\.\d+\.\d+).*\.tar\.gz", line)
        project = m.group(1)
        if project == "python-watcher":
            project = "watcher"
        elif project == "kuryr-lib":
            project = "kuryr"
        projects[project] = {}
        projects[project]['used'] = m.group(2)

        release = RELEASE
        if project in INDEPENDENT:
            release = "_independent"
        y = requests.get("https://raw.githubusercontent.com/openstack/releases/master/deliverables/%s/%s.yaml" % (release, project), stream=True)
        if y.status_code == 200:
            d = yaml.load(y.content)
            projects[project]['current'] = d['releases'][-1]['version']
        else:
            projects[project]['current'] = '---'

j2_env = Environment(loader=FileSystemLoader(THIS_DIR),
                     trim_blocks=True,
                     autoescape=True)
template = "kolla_versions_template.html"
rendered_html = j2_env.get_template(template).render(
    last_update=datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H:%M:%S'),
    projectnames=sorted(projects),
    projects=projects,
    release=RELEASE
)
with open("versions.html", "wb") as fh:
    fh.write(rendered_html)
