"""
Configure PYTHONPATH and template locations etc
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
import sys
import jinja2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../lib'))

templates = os.path.join(os.path.dirname(__file__), '../templates')

JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(templates),
    extensions=['jinja2.ext.autoescape'],
    autoescape=True)


# Workaround the dev-environment SSL
#   http://stackoverflow.com/q/16192916/893652
if os.environ.get('SERVER_SOFTWARE', '').startswith('Development'):
    import imp
    import os.path
    from google.appengine.tools.devappserver2.python import sandbox

    sandbox._WHITE_LIST_C_MODULES += ['_ssl', '_socket']
    # Use the system socket.
    psocket = os.path.join(os.path.dirname(os.__file__), 'socket.py')
    imp.load_source('socket', psocket)
    opencorps_host = "http://localhost:8080"
else:
    opencorps_host = "https://theopencorps.org"
