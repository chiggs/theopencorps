"""
Logic related to a given project
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
import json
import logging
import time
import StringIO

import webapp2

import theopencorps.paths as paths
import pusher

import theopencorps.auth
import theopencorps.travis.yml
import theopencorps.corefile
import theopencorps.secrets as config
from theopencorps.datamodel.models import Project, Repository, User, JUnitTestResult, Push

from theopencorps.endpoints import HTTPException
from theopencorps.endpoints.travis import TravisEndpoint
from theopencorps.endpoints.github import GithubEndpoint

class ProjectError(Exception):
    pass


class ProjectHelper(object):

    """
    This class understands everything about a project and how to perform actions
    on it.

    Since some things take a long time, we run through this in a task queue
    rather than doing it live during a request.  This makes the website seem
    much more responsive.

    We can then use a websocket to update the rendered project page as
    we progress through the project initialisation stages.
    """

    _org = "OpenCorps"
    _shields = ["docs", "sim", "altera", "xilinx"]

    def __init__(self, project, repo=None):
        self.project = project
        if repo is None:
            self.repo = self.project.repo.get()
        else:
            self.repo = repo
        self.log = logging.getLogger("project.%s" % project.full_name.replace("/", "."))
        self.oc_corefile = None
        self._updates = None
        self._template = None


    def update_sim_result(self, passed=0, failed=0, errors=0, skipped=0):
        """
        Update our project shields based on an incoming simulation result
        """
        index = self._shields.index("sim")

        # Update the href
        self.project.shields[index].href = "simulation"

        if errors != 0:
            self.project.shields[index].colour = "red"
            self.project.shields[index].status = "%d errors" % errors
        elif failed != 0:
            self.project.shields[index].colour = "orange"
            self.project.shields[index].status = "%d failures" % failed
        elif passed != 0:
            self.project.shields[index].colour = "brightgreen"
            self.project.shields[index].status = "%d passing" % passed
        elif skipped != 0:
            self.project.shields[index].colour = "yellow"
            self.project.shields[index].status = "all skipped (%d)" % skipped
        else:
            self.project.shields[index].colour = "lightgrey"
            self.project.shields[index].status = "no tests"

    def update_status(self):
        """
        User Pusher to send updated project status div contents to anybody
        viewing the project page.
        """
        if self._updates is None:
            self._updates = pusher.Pusher(**config.config['pusher'])
        if self._template is None:
            self._template = paths.JINJA_ENVIRONMENT.get_template('project_status.html')
        status = self._template.render(baseurl="../", project=self.project, repo=self.repo)
        channel = "updates_%s" % (self.repo.full_name.replace("/", "_"))
        self._updates[channel].trigger('update_div',
                                       {'div' : "#project-status-col",
                                        'content': status})
        self.log.info("Pushed updated content to %s", channel)

    @webapp2.cached_property
    def gh_oc(self):
        """
        Github API access - as "theopencorps"
        """
        return GithubEndpoint(token=config.theopencorps_token)

    @webapp2.cached_property
    def travis(self):
        """
        Travis API access, as "theopencorps"
        """
        return TravisEndpoint(token=config.travis_token_post_auth)

    def cache_svgs(self):
        """
        TODO:
        Retrieve the shields.io SVGs and save them - the service seems a bit unreliable
        """
        pass

    def advance(self):
        """
        Do whatever is required on the project to advance the status.

        Returns False if there is still more to do...

        FIXME: This should really be a bit nicer - state machine mapping to
        function calls or something

        NOTE: Callee needs to put() the updated project

        This work should be done in a task queue rather than a request
        """
        if self.project.failure_count > 20:
            raise ProjectError("Giving up after %d failures" % self.project.failure_count)

        if not self.project.github_webhook:
            self.project.failure_count += 1
            raise ProjectError("Can't continue - no webhook for project")

        if not self.project.forked:
            if self.create_fork():
                self.update_status()
                self.project.failure_count = 0
            else:
                self.project.failure_count += 1
            return False

        if not self.project.user_oc_yml:
            result = self.check_user_oc()
            self.update_status()
            if not result:
                self.log.info("Waiting for a webhook on %s to indicate .opencorps.yml", self.repo.full_name)
                self.project.failure_count += 1
            else:
                self.project.failure_count = 0
            return False

        # Perform any pending_merges in case the user has update YML file
        # Note in theory we should check whether .opencorps.yml has changed
        # however for now we'll just always regenerate but only commit if
        # the .travis.yml turns out different
        if len(self.project.pending_merges):
            self.project.fork_yml_valid = False
            self.project.fork_yml_invalid = False
            self.project.fork_travis_yml = False
            if not self.apply_pending_merge():
                self.project.failure_count += 1
            else:
                self.project.failure_count = 0
            return False

        if not self.project.fork_yml_valid:
            self.validate_oc_yml()
            self.update_status()
            return self.project.fork_yml_invalid

        if not self.project.travis_sync_req:
            self.travis.sync(block=False)
            self.project.travis_sync_req = True
            self.project.failure_count = 0
            return False

        if not self.project.travis_webhook:
            if not self.enable_travis_webhook():
                self.project.failure_count += 1
            else:
                self.project.failure_count = 0
                self.update_status()
            return False

        if not self.project.fork_travis_yml:
            if not self.create_travis_yml():
                self.project.failure_count += 1
                return False

        self.project.failure_count = 0
        self.project.init_complete = True
        self.update_status()
        return True


    def create_fork(self):
        """
        Create a mirror of the repository under OpenCorps organisation

        TODO: Check that we don't already have a repo with the same name
        """
        user = self.repo.full_name.split('/')[0]
        name = self.repo.name
        msg = "fork %s/%s into %s/%s", user, name, self._org, name
        try:
            fork = self.gh_oc.fork(user, name, organisation=self._org)
        except HTTPException as e:
            self.log.error("%s failed: %s", (msg, repr(e)))
            self.project.system_message = "Failed to create %s: %s" % (msg, repr(e))
            return False

        self.log.info("Success: %s", msg)
        self.log.debug("Fork returned %s", repr(fork))
        self.project.forked = True
        self.project.system_message = "Sucessfully forked %s/%s into %s/%s" % (user, name, self._org, name)

        # Create a push event to track the current head
        # Can't emulate a full webhook since we don't get compare URL etc unless
        # there's been a push, but we could fake it up in the display probably...
        sha1 = self.gh_oc.get_head(user, name)
        push = Push(id=sha1)
        push.put_async()
        self.log.info("Created Push event for pre-fork commit: %s", sha1)
        return True


    def _get_opencorps_yml(self, user, name, filename=".opencorps.yml"):
        self.log.info("Searching for %s in %s/%s", filename, user, name)
        try:
            contents = self.gh_oc.get_file(user, name, filename)
            self.log.info("Found %d bytes of %s in %s/%s", len(contents), filename, user, name)
            return contents
        except HTTPException:
            self.log.warning("No %s in %s/%s", filename, user, name)
            return None


    @webapp2.cached_property
    def user_oc_yml(self):
        """
        Retrieve .opencorps.yml from the user repo
        """
        user = self.repo.full_name.split('/')[0]
        return self._get_opencorps_yml(user, self.repo.name)


    @webapp2.cached_property
    def oc_yml(self):
        """
        Retrieve .opencorps.yml from our fork
        """
        return self._get_opencorps_yml(self._org, self.repo.name)


    @webapp2.cached_property
    def travis_yml(self):
        """
        Retrieve travis YML from our repository
        """
        return self._get_opencorps_yml(self._org, self.repo.name, filename=".travis.yml")


    def check_user_oc(self):
        """
        Check whether .opencorps.yml exists in the user repo
        """
        self.project.checked_user_oc_yml = True
        if self.user_oc_yml is None:
            self.project.system_message = "No .opencorps.yml present.  Refer to documentation for how to enable this project"
            return False
        self.project.user_oc_yml = True
        return True


    def validate_oc_yml(self):
        """
        Check that the fork copy of .opencorps.yml is valid...
        """
        contents = self.oc_yml
        if contents is None:
            return False

        fobj = StringIO.StringIO(contents)
        try:
            self.oc_corefile = theopencorps.corefile.CoreFile(fobj)
            self.log.info("Have a valid .opencorps.yml in %s/%s", self._org, self.repo.name)
        except Exception as e:
            self.log.warning("Invalid .opencorps.yml in %s/%s", self._org, self.repo.name)
            self.log.info(repr(e))
            self.project.system_message = repr(e)
            self.project.fork_yml_valid = False
            self.project.fork_yml_invalid = True
            return False
        self.project.fork_yml_valid = True
        return True


    def enable_travis_webhook(self):
        """
        Enable travis webhook for our fork
        """
        if not self.travis.is_synced():
            self.log.info("Still waiting for travis to synchronise")
            # Give travis some time before hammering again...
            time.sleep(0.1)
            return False

        hooks = self.travis.get_hooks()
        repo = self.travis.get_repo(self._org, self.repo.name)

        if not hooks:
            logging.error("Failed to get travis hooks, giving up")
            return False

        for hook_d in hooks['hooks']:
            if hook_d['name'] == self.repo.name and \
                                hook_d['owner_name'] == self._org:
                hook_id = hook_d['id']
                logging.info("Found travis hook ID %s", repr(hook_id))
                break
        else:
            self.log.error("Couldn't find a matching travis hook")
            return False

        if hook_d['active']:
            self.log.info("Travis hook for %s/%s already enabled", 'OpenCorps', self.repo.name)
        else:
            self.log.info('Enabling travis hook for %s/%s', 'OpenCorps', self.repo.name)
            self.travis.enable_hook(int(hook_id))

        # Fix up Travis shonky API
        repo = repo["repo"]
        repo_id = repo["id"]

        if not self.travis.update_settings(repo_id,
                                           builds_only_with_travis_yml=True,
                                           build_pushes=True,
                                           build_pull_requests=False):
            self.log.warning("Didn't manage to update Travis settings for repo %d", repo_id)
        else:
            self.log.info("Updated Travis settings for %s/%s (%d)", self._org, self.repo.name, repo_id)

        self.project.travis_webhook = True
        return True



    def create_travis_yml(self):
        """
        Create a .travis.yml file in our fork of the repository
        """
        if self.oc_corefile is None:
            self.validate_oc_yml()

        self.log.info("Creating a .travis.yml file for %s", self.project.full_name)

        # Encrypt environment variables
        token = "'MSG_TOKEN=%s'" % self.project.secret
        secure_variables = []
        for variable in config.secure_variables + [token]:
            secure_variables.append(self.travis.encrypt('OpenCorps', self.repo.name, variable))
            self.log.info("%s -> %s", variable, secure_variables[-1])

        namespace = self.oc_corefile.to_template_dict()
        if "environment_variables" not in namespace:
            namespace["environment_variables"] = []
        namespace["environment_variables"].append("REPOSITORY=%s" % self.repo.full_name)
        namespace["environment"] = "trusty"
        namespace["modelsim"] = True
        namespace["secure_variables"] = secure_variables

        # Update tags based on what we found in the YML
        for tag in ["fusesoc", "vunit", "quartus", "vivado"]:
            if tag in namespace and tag not in self.project.tags:
                self.project.tags.append(tag)

        contents = theopencorps.travis.yml.TravisYML(**namespace).render()
        self.log.debug(contents)

        def thesame(one, tother):
            """
            Custom compare function to skip secure variables, since they change
            """
            one = one.split('\n')
            tother = tother.split('\n')
            for lineno, line in enumerate(one):
                if lineno >= len(tother):
                    return False
                if line.strip().startswith("- secure:"):
                    continue
                if line != tother[lineno]:
                    return False
            return True


        if self.travis_yml is None or not thesame(self.travis_yml, contents):

            before = self.gh_oc.get_head(self._org, self.repo.name)

            if self.travis_yml is None:
                self.log.info("Creating new .travis.yml in the repository")
                message = "Add OpenCorps .travis.yml to repository"
            else:
                self.log.info(".travis.yml has changed, updating %s", self.project.full_name)
                message = "Updating .travis.yml from .opencorps.yml"
            success = self.gh_oc.commit_file(self._org, self.repo.name,
                                   ".travis.yml", contents, message)
            self.project.fork_travis_yml = success
            if not success:
                self.log.error("Something when wrong committing .travis.yml")
                after = None
            else:
                self.log.info(".travis.yml updated successfully")
                after = self.gh_oc.get_head(self._org, self.repo.name)

            # Write back the update
            if after is not None:

                # First see if the before sha is just an upstream commit
                push = Push.get_by_id(before)

                if push is None:
                    push = Push.query(Push.fork_merge == before).fetch(1)
                    if len(push):
                        push = push[0]

                if push:
                    push.travis_update = after
                    push.put_async()

                # Tell travis to build this
                self.travis.sync(block=False)

        else:
            self.log.info("No need to update .travis.yml")
            self.project.fork_travis_yml = True
        return self.project.fork_travis_yml


    def apply_pending_merge(self):
        """
        Upstream changed, so we need to apply the fork to our
        repository.

        TODO: Regenerate .travis.yml if any dependent files were changed
        in any of the commits.
        """
        push = self.project.pending_merges[0].get()
        sha1 = push.after
        commit = ""

        # First of all attempt to cherry-pick, thus avoiding polluting history
        self.log.info("Attempting to cherry-pick upstream changeset %s", sha1)
        try:
            commit = self.gh_oc.cherry_pick(self._org, self.repo.name, sha1, force=True)
        except HTTPException as e:
            self.log.error("Failed to merge upstream changeset %s", sha1)
            self.log.debug(repr(e))

        if not commit:
            try:
                commit = self.gh_oc.merge(self._org, self.repo.name, sha1)
            except HTTPException as e:
                self.log.error("Failed to merge upstream changeset %s", sha1)
                self.log.debug(repr(e))
            return False

        if not len(commit):
            self.log.warning("Didn't get an sha1 for cherry-picked commit?")
        else:
            self.project.pending_merges.pop(0)
            # Tell travis to build this commit


        push.fork_merge = commit
        push.put_async()
        return True

