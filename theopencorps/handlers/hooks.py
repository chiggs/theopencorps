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
import json

import webapp2
from google.appengine.ext import ndb
from google.appengine.api import taskqueue

import theopencorps.auth
import theopencorps.secrets as config

from theopencorps.datamodel.models import Push, Repository, TravisJob, TravisBuild
from theopencorps.datamodel.project import ProjectHelper

from theopencorps.endpoints.travis import TravisEndpoint

class GithubWebHookHandler(theopencorps.auth.TokenValidatedHandler):

    """
    Handle a Github Webhook

        - We simply create a Push object to track this event
        - We queue the project worker to perform the related work resulting from the push
    """

    @theopencorps.auth.validate_token("X-Hub-Signature")
    def post(self, project):

        try:
            request = json.loads(self.request.body)
        except:
            logging.error("Invalid JSON supplied to GithubWebHookHandler")
            self.response.set_status(404)
            return

        event = self.request.headers.get('X-Github-Event', "")
        if event == "ping":
            logging.info("Recieved ping event for %s", project.full_name)
            logging.info(repr(request))
            self.response.set_status(200)
            self.response.write("Ping received!")
            return

        if event != "push":
            logging.info("Recieved unknown event \"%s\" for %s", event, project.full_name)
            self.response.set_status(404)
            self.response.write("Unexpected event \"%s\"" % event)
            return

        logging.info("Processing event \"%s\" for %s", event, project.full_name)

        sha1 = request['after']

        # Ensure we don't already have an object tracking this event
        push = ndb.Key(Push, sha1).get()
        if push is not None:
            logging.warning("Already seem to have a Build event tracking %s", sha1)
            logging.debug(repr(request))
            logging.debug(repr(push.to_dict()))
            taskqueue.add(url="/%s" % repo.full_name)
            return

        repo = project.repo.get()
        if repo is None:
            logging.error("Failed to find repository %s", project.repo.id)
            self.response.set_status(202)
            return

        got = request['repository']['full_name']
        exp = repo.full_name
        if got != exp:
            logging.error("Webhook event repository %s didn't match expected %s", got, exp)
            self.response.set_status(202)
            return

        # Create the build object
        push = Push(id=sha1)
        push.ref = request['ref']
        push.before = request['before']
        push.after = request['after']
        push.compare = request['compare']
        push.put()

        # Use the Github API to merge in the upstream changes to our fork
        if push.key not in project.pending_merges:
            project.pending_merges.append(push.key)
        else:
            logging.warning("Not appending to project - already in the pending merges queue")

        # Reset any failures
        project.failure_count = 0
        project.put()
        taskqueue.add(url="/%s" % repo.full_name)
        return







class CustomTravisHookHandler(theopencorps.auth.TokenValidatedHandler):
    """
    Since we have various common things we need to do for
    hooks we post from Travis, we abstract out into a base class
    """
    def __init__(self, *args, **kwargs):
        theopencorps.auth.TokenValidatedHandler.__init__(self, *args, **kwargs)
        self._job = None
        self._build = None

    def get_build_and_job(self):
        """
        Since they are interlinked, we need to retrieve both at the same time

        Assumes callee calls insert_or_update() when done
        """
        travis_build_id = int(self.request.headers.get("Travis-BuildID", "0"))
        travis_job_id = int(self.request.headers.get("Travis-JobID", "0"))
        commit = self.request.headers.get("Travis-Commit", "")

        if not travis_build_id or not travis_job_id:
            raise HookException("No travis build information")

        travis = TravisEndpoint(token=config.travis_token_post_auth)
        travis_data = travis.get_build(travis_build_id)

        job = TravisJob(id=travis_job_id,
                        travis_id=travis_job_id,
                        commit=commit,
                        valid=True)

        build = TravisBuild(id=travis_build_id,
                        commit=commit,
                        valid=True)

        travis_build = travis_data["build"]
        build.repository_id = travis_build["repository_id"]
        build.number = travis_build["number"]
        build.state = travis_build["state"]
        build.duration = travis_build["duration"]
        build.job_ids = travis_build["job_ids"]

        travis_job = [tj for tj in travis_data["jobs"] if tj["id"] == travis_job_id]
        if len(travis_job) != 1:
            logging.warning("Didn't find travis job id %s in build response", travis_job_id)
            logging.info(repr(travis_data["jobs"]))
        else:
            travis_job = travis_job[0]
            job.build_id = travis_job["build_id"]
            job.repository_id = travis_build["repository_id"]
            job.log_id = travis_job["log_id"]
            job.number = travis_job["number"]
            job.state = travis_job["state"]
            try:
                job.duration = travis_job["duration"]
            except KeyError:
                job.duration = 0
        return build, job

    def get_job(self):
        if self._job is not None:
            return self._job
        self._build, self._job = self.get_build_and_job()
        return self._job

    def get_build(self):
        if self._build is not None:
            return self._build
        self._build, self._job = self.get_build_and_job()
        return self._build

    @webapp2.cached_property
    def push(self):
        """
        Find the push event associated with this build
        """
        commit = self.request.headers.get("Travis-Commit", "")

        if not len(commit):
            logging.error("No commit information provided")
            return None

        # Find the Push object that's tracking this commit
        push = Push.get_by_id(commit)
        if push is not None:
            return push

        push = Push.query(ndb.OR(Push.fork_merge == commit,
                                 Push.travis_update == commit)).fetch()
        if not push:
            logging.warning("Failed to find the Push that triggered this build with commit %s", commit)
            return None
        elif len(push) > 1:
            logging.warning("Have multiple Push objects with the same sha %s", commit)
            return None
        return push[0]


class JobPurgeHandler(theopencorps.auth.BaseSessionHandler):

    def post(self, job_id):
        """
        Task queue processor for purging old Travis Jobs
        """
        try:
            job_id = int(job_id)
        except:
            logging.warning("Job purge handler called with %s", repr(job_id))
            return
        TravisJob.purge_duplicate_travis_jobs(job_id)
