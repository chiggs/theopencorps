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

import theopencorps.paths

import webapp2
from google.appengine.ext import ndb

import theopencorps.secrets
import theopencorps.routes as routes

app_pre = webapp2.WSGIApplication(routes.ROUTES, debug=True, config=theopencorps.secrets.config)
app_pre.error_handlers[404] = routes.handle_404

# Ensure that all pending async calls complete before terminating the request
app = ndb.toplevel(app_pre)

