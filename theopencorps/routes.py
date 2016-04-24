"""
Routing for internet facing RESTful API

Could make this nicer using auto-registering decorators or some other fancy
mechanism, however initially let's focus on the logic itself.
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
import logging

import jinja2
import webapp2

import theopencorps
import theopencorps.handlers
from theopencorps.paths import JINJA_ENVIRONMENT
from theopencorps.datamodel.models import Project



class MainPage(theopencorps.auth.BaseSessionHandler):
    def get(self):
        template = JINJA_ENVIRONMENT.get_template('index.html')
        projects = Project.query().order(Project.created).fetch(20)
        self.response.write(template.render(user=self.user,
                                            projects=projects))

class DocsPage(theopencorps.auth.BaseSessionHandler):
    def get(self):
        template = JINJA_ENVIRONMENT.get_template('docs.html')
        self.response.write(template.render(user=self.user))

def handle_404(request, response, exception):
    logging.exception(exception)
    template = JINJA_ENVIRONMENT.get_template('404.html')
    response.set_status(404)
    response.write(template.render(user=None))



ROUTES = [
    webapp2.Route(r'/login',                              theopencorps.auth.LoginHandler),
    webapp2.Route(r'/logout',                             theopencorps.auth.LogoutHandler),
    webapp2.Route(r'/new',                                theopencorps.handlers.projects.NewProjectHandler),
    webapp2.Route(r'/<user>/<repo>',                      theopencorps.handlers.projects.ProjectHandler),
    webapp2.Route(r'/<user>/<repo>/simulation/results',   theopencorps.handlers.results.JunitResultsHandler),
    webapp2.Route(r'/<user>/<repo>/simulation/log',       theopencorps.handlers.logs.LogFileHandler),
    webapp2.Route(r'/<user>/<repo>/commit',               theopencorps.handlers.hooks.GithubWebHookHandler),
    webapp2.Route(r'/<user>/<repo>/commits/<sha1>',       theopencorps.handlers.builds.BuildHandler),
    webapp2.Route(r'/jobs/<job_id>/purge',                theopencorps.handlers.hooks.JobPurgeHandler),
    webapp2.Route(r'/',                                   MainPage),
    webapp2.Route(r'/docs',                               DocsPage),
    ]


