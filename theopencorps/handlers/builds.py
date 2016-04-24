"""
Display stuff to do with builds...
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
import ansiconv

import cloudstorage as gcs

import theopencorps.paths as paths
import theopencorps.auth

from theopencorps.datamodel.models import Project, Repository, TravisJob, Push, JUnitTestResult


class BuildHandler(theopencorps.auth.BaseSessionHandler):

    """
    A build is identified by a commit
    """

    def get(self, user, repo, sha1):

        fullname = "%s/%s" % (user, repo)
        project = Project.get_by_id(fullname)

        if project is None:
            self.response.set_status(404)
            template = paths.JINJA_ENVIRONMENT.get_template('404.html')
            self.response.write(template.render(user=self.user,
                                                baseurl="../../../",
                                                message="Project %s not found" % fullname))
            return

        push = Push.get_by_id(sha1)
        if push is None:
            self.response.set_status(404)
            template = paths.JINJA_ENVIRONMENT.get_template('404.html')
            self.response.write(template.render(user=self.user,
                                                baseurl="../../../",
                                                message="Commit %s not found" % sha1))
            return

        repo = project.repo.get()
        junit = JUnitTestResult.query(JUnitTestResult.push==push.key).fetch()
        junit = [j for j in junit if j.valid]
        logging.info("Found %d junit results for sha %s", len(junit), sha1)
        junit = junit[0]

        sim_job = junit.travis_job.get()

        sim_logfiles = []

        for logfile in sim_job.logfiles:
            gcs_file = gcs.open(logfile)
            sim_logfiles.append((logfile.split('/')[-1].split(".")[0], ansiconv.to_html(gcs_file.read())))
            gcs_file.close()

        template = paths.JINJA_ENVIRONMENT.get_template('build.html')
        self.response.write(template.render(user=self.user,
                                            project=project,
                                            repo=repo,
                                            push=push,
                                            junit=junit,
                                            sim_job=sim_job,
                                            sim_logfiles=sim_logfiles))
        return
