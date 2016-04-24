"""
Handlers for project related API calls
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
import webapp2

import theopencorps
import theopencorps.auth

class ProjectBaseHandler(theopencorps.auth.BaseSessionHandler):

    @webapp2.cached_property
    def gh_user(self):
        """
        Github API access - as the logged in user
        """
        return GithubEndpoint(token=self.credentials.token)


class ProjectHandler(ProjectBaseHandler):

    def get(self, user, repo):
        fullname = "%s/%s" % (user, repo)
        project_key = ndb.Key(Project, fullname)
        tests_future = JUnitTestResult.query(JUnitTestResult.project==project_key).order(JUnitTestResult.created).fetch_async(500)
        project = project_key.get()

        if project is None:
            self.response.set_status(404)
            template = paths.JINJA_ENVIRONMENT.get_template('404.html')
            self.response.write(template.render(user=self.user,
                                                baseurl="../",
                                                message="Project %s not found" % fullname))
            return

        repo = project.repo.get()
        tests = tests_future.get_result()
        tests = [test for test in tests if test.valid]
        maxtests = max([test.tests for test in tests]) if tests else 0

        template = paths.JINJA_ENVIRONMENT.get_template('project.html')
        self.response.write(template.render(user=self.user, project=project, repo=repo,
                                            tests=tests, maxtests=maxtests))
        return


    def post(self, user, repo):
        """
        This is the task queue processor that does everything related to
        updating a project.

        Triggered by webhooks etc.
        """
        fullname = "%s/%s" % (user, repo)
        logging.info("Got a post for %s", fullname)
        project_key = ndb.Key(Project, fullname)
        project = project_key.get()
        repo = project.repo.get()
        helper = ProjectHelper(project, repo=repo)
        before = project.failure_count
        try:
            complete = helper.advance()
        except Exception as e:
            project.put()
            logging.error("Project task failed: %s", repr(e))
            return
        project.put()

        if not complete:
            if project.failure_count > before:
                taskqueue.add(url="/%s" % repo.full_name, countdown=0.5)
            else:
                taskqueue.add(url="/%s" % repo.full_name)
        return

class NewProjectHandler(ProjectBaseHandler):

    """
    Form submission handler for creating a new project.

    We do very little work here, just create the project object and
    redirect to the project page.  We then queue up tasks to finish
    up the project creation.

    We use pusher to provide live feedback of the signup process
    """

    @theopencorps.auth.login_required
    def post(self):
        logging.info(cgi.escape(self.request.get("repo")))
        repo_info = json.loads(cgi.escape(self.request.get("repo")))
        gh_username = cgi.escape(self.request.get("gh_username"))
        name = cgi.escape(self.request.get("name"))
        desc = cgi.escape(self.request.get("description"))
        tags = cgi.escape(self.request.get("tags"))
        uid  = int(cgi.escape(self.request.get("unique_id")))

        # Kick off the async requests
        oc_repos_future = Repository.query(Repository.repo_id == repo_info["id"]).fetch_async(2)
        gh_repo_future = self.gh_user.get_repo_async(gh_username, repo_info["name"])

        pusher_channel = "progress_%d" % uid
        logging.debug("Using Pusher channel %s" % pusher_channel)
        logging.info("Received: %s -> %s with tags %s", gh_username, name, tags)

        p = pusher.Pusher(**config.config['pusher'])
        def update_progress(percent, message):
            p[pusher_channel].trigger('update', {'progress' : percent, 'message': message})

        update_progress(20, "Querying GitHub for information about %s/%s" % (gh_username, repo_info["name"]))
        gh_repo = gh_repo_future.get_result()
        if not gh_repo:
            logging.error("Something went wrong, no Github repo for id %d",
                            repo_info['id'])
            update_progress(0, "ERROR: Failed to retrieve Github repository information for id %s" % repo_info['id'])
            return

        # Github repository is asynchronous, make take time to appear if newly created...
        retry = 1
        while "full_name" not in gh_repo:
            logging.warning("Attempt %d to retrieve repository information returned %s", retry, repr(gh_repo))
            try:
                gh_repo = self.gh_user.get_repo(gh_username, repo_info["name"])
            except HTTPException as e:
                logging.warning(repr(e))
                time.sleep(0.005)
                retry += 1
                if retry >= 10:
                    break

        if 'full_name' not in gh_repo:
            update_progress(0, "Failed to retrieve github repository data.  Please ensure the repository exists and try again")
            return

        # Kick off the project retrieval
        project_future = Project.get_by_id_async(gh_repo['full_name'])

        # Check that we don't already have that project
        # Find the repo object for this repository
        repos = oc_repos_future.get_result()
        if not repos:
            logging.info("Creating new repository object to track %s:%d",
                         repo_info['name'], repo_info['id'])

            repo = Repository(repo_id = gh_repo['id'],
                              name = gh_repo['name'],
                              full_name = gh_repo['full_name'],
                              api_url = gh_repo['url'],
                              url = gh_repo['html_url'],
                              provider="github")
            repo.put()
            update_progress(40, "Repository %s set up" % gh_repo['full_name'])
        else:
            # TODO: Make id the key...
            repo = repos[0]
            update_progress(40, "Repository infromation for %s retrived from database" % repo.full_name)


        project = project_future.get_result()

        # Hmmm, seems to be difficult to delete projects via dev console
        # FIXME this is only really temporary, but overwrite an existing one
        if project is not None:
            if False:
                update_progress(60, "Existing project found for %s" % repo.full_name)
                update_progress(100, "%s/%s" % (paths.opencorps_host, repo.full_name))
                self.redirect("/%s" % repo.full_name)
                return
            logging.error("A project for %s already exists - deleting", repo.full_name)
            project.key.delete()
            project = None

        if project is None:
            logging.info("Creating new project for %s", repo.full_name)
            project = Project(name=name,
                              full_name=repo.full_name,
                              tags=tags.split(","),
                              owner=self.user.key,
                              description=desc,
                              repo=repo.key,
                              id=repo.full_name)
            project.shields = [Shield(subject=subject, status="unknown", colour="lightgrey")
                                    for subject in ProjectHelper._shields]
            project.shields_svg = ["" for subject in ProjectHelper._shields]

            digest = "%s created at %f with random salt of %d" % (
                repo.full_name, time.time(), random.getrandbits(32))
            project.secret = hashlib.sha1(digest).hexdigest()
            logging.info("%s -> %s", digest, project.secret)
            update_progress(60, "Project created to track %s" % repo.full_name)

        logging.info("Creating webhook for repository %s", repo.full_name)
        self.gh_user.create_webhook(gh_username, repo.name,
                                    "https://theopencorps.potential.ventures/%s/%s/commit" % (gh_username, repo.name),
                                    secret=str(project.secret))
        update_progress(90, "Webhook enabled for %s" % repo.full_name)
        project.github_webhook = True
        project.put()
        update_progress(100, "%s/%s" % (paths.opencorps_host, repo.full_name))
        taskqueue.add(url="/%s" % repo.full_name, countdown=0.3)
        return


    @theopencorps.auth.login_required
    def get(self):
        gh_user = self.gh_user.user
        repos = self.gh_user.get_repos()
        template = paths.JINJA_ENVIRONMENT.get_template('new.html')
        self.response.write(template.render(user=self.user, gh_user=gh_user, repos=repos, unique_id=random.getrandbits(31)))
