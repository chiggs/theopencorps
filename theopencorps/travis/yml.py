"""
Helper for generating the .travis.yml file for 
"""
__copyright__ = """
Copyright (C) 2016 Potential Ventures Ltd

This file is part of theopencorps
<https://github.com/theopencorps/theopencorps/>
"""

__license__ = """
This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <http://www.gnu.org/licenses/>.
"""

import os
from jinja2 import Environment, FileSystemLoader

# Annoyingly GAE is jinja 2.6 which doesn't support lstrip_blocks=True
_env = Environment(loader=FileSystemLoader(os.path.dirname(__file__)), trim_blocks=True)

class TravisYML(object):
    """
    Convenience wrapper for our Travis YML generation
    """
    def __init__(self, *args, **kwargs):
        for name, value in kwargs.iteritems():
            setattr(self, name, value)

    def render(self):
        _template = _env.get_template('travis.yml.tpl')
        return _template.render(**self.__dict__)
