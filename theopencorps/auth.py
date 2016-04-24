"""
Handles authentication of users via third party providers.

If we don't already have a datastore account for the user then we create our
own local entity.
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
import urllib
import hmac
import hashlib


import webapp2
from google.appengine.ext import ndb

from webapp2_extras import sessions

from authomatic import Authomatic
from authomatic.adapters import Webapp2Adapter

import theopencorps.secrets as config
from theopencorps.datamodel.models import User, Project
from theopencorps.endpoints.github import GithubEndpoint

authomatic = Authomatic(config=config.config,
                        secret=config.SECRET,
                        report_errors=True,
                        logging_level=logging.DEBUG)


class LoginHandler(webapp2.RequestHandler):

    def get(self):
        """
        Only support GitHub at the moment
        """
        result = authomatic.login(Webapp2Adapter(self), "github")
        if not result:
            logging.critical("authomatic.login() returned %s", repr(result))
            return

        user = False
        if result.user:
            if not (result.user.name and result.user.id):
                result.user.update()
            logging.info("User %s (%s) successfully authenticated", result.user.name, result.user.id)

            user = User.get_by_id(str(result.user.id))
            if user is None:
                logging.info("User ID %s didn't exist in datastore - creating new user %s",
                                                    str(result.user.id), result.user.name)
                user = User(id=str(result.user.id),
                            user_name=result.user.name)

                # Fill in additional information from github API
                gh_user = GithubEndpoint(token=result.user.credentials.token).user
                user.login = gh_user.get("login", "")
                user.email = gh_user.get("email", "")
                user.avatar_url = gh_user.get("avatar_url", "")
                user.url = gh_user.get("url", "")
                user.html_url = gh_user.get("html_url", "")
                user.put_async()

            else:
                logging.info("Found user %s (%s) in datastore", user.key.id(), user.login, user.user_name)

            # Save the user name and ID to cookies that we can use it in other handlers.
            self.response.set_cookie('user_id', result.user.id)
            self.response.set_cookie('user_name', urllib.quote(result.user.username))

            if result.user.credentials:
                # Serialize credentials and store it as well.
                # TODO: review whether these should go in datastore rather than a cookie
                serialized_credentials = result.user.credentials.serialize()
                self.response.set_cookie('credentials', serialized_credentials)
        elif result.error:
            self.response.write(u'<h2>Pants, something went wrong: {}</h2>'.format(result.error.message))
            self.response.set_cookie('error', urllib.quote(result.error.message))

        self.redirect('/')



class TokenValidatedHandler(webapp2.RequestHandler):
    """
    Base class for handlers that use a token in the request to confirm
    that the request can be trusted.

    Token is HMAC hex digest of the request payload generated using a secret
    """
    def get_project(self, user, repo):
        try:
            return self.project
        except AttributeError:
            pass
        fullname = "%s/%s" % (user, repo)
        project = Project.get_by_id(fullname)
        if project is not None:
            logging.info("Found project %s (id: %s)", fullname, project.key.id)
        else:
            logging.warning("Failed to find project %s", fullname)
        self.project = project
        return project


def validate_token(header):
    """
    For webhooks, results from Travis-CI etc the POST requests aren't user authenticated.

    We use an SHA1 HMAC digest with a custom header to validate the origin of the request

    This decorator handles everything and makes sure we have a valid project for the
    request.
    """
    def _wrap(handler_method):
        def check_token(self, user, repo, *args, **kwargs):
            project = self.get_project(user, repo)
            if project is None:
                logging.warning("Got request for %s/%s which didn't exist", user, repo)
                self.response.set_status(404)
                return

            key = str(project.secret)  # Convert from unicode to a string
            logging.info("Using key: %s (%s)", key, type(key))
            exp = hmac.new(key, self.request.body, hashlib.sha1).hexdigest()
            got = self.request.headers.get(header, default="")
            if not got:
                logging.warning("No %s header was provided with result", header)
                self.response.write("Didn't find %s header in request" % header)
                self.response.set_status(404)
                return
            try:
                hashtype, got = got.split("=")
            except ValueError:
                logging.warning("Got a webhook with a HMAC hashtype of %s", got)
                self.response.write("Invalid HMAC digest %s" % got)
                self.response.set_status(404)
                return
            if hashtype != "sha1":
                logging.warning("Got a webhook with a HMAC hashtype of %s", hashtype)
                self.response.write("Unable to process HMAC using hash %s" % hashtype)
                self.response.set_status(404)
                return

            if exp != got:
                logging.warning("%s didn't match (got %s but expected %s for %d bytes (%d ascii)",
                                header, got, exp, len(self.request.body), len(repr(self.request.body)))
                logging.info(repr(self.request.headers))
                logging.info(self.request.body)
                logging.info("%d bytes (%d newlines)", len(self.request.body), self.request.body.count("\n"))
                self.response.write("Wrong HMAC digest recieved - expected %s" % exp)
                self.response.set_status(404)
                return
            else:
                logging.info("Remote end provided correct %s %s",
                            header, got)
            return handler_method(self, project, *args, **kwargs)
        return check_token
    return _wrap

class BaseSessionHandler(webapp2.RequestHandler):

    def dispatch(self):
        """
        """
        self.session_store = sessions.get_store(request=self.request)

        try:
            # Dispatch the request.
            webapp2.RequestHandler.dispatch(self)
        finally:
            # Save all sessions.
            self.session_store.save_sessions(self.response)

    @webapp2.cached_property
    def session(self):
        """Returns a session using the default cookie key."""
        return self.session_store.get_session()


    @webapp2.cached_property
    def user(self):
        """
        Returns the User object from datastore for the currently logged in user
        Or None on failure
        """

        # Retrieve values from cookies.
        user_id = self.request.cookies.get('user_id')
        user_name = urllib.unquote(self.request.cookies.get('user_name', ''))

        if user_id:
            user = User.get_by_id(str(user_id))
            return user
        return None

    @webapp2.cached_property
    def credentials(self):
        serialized_credentials = self.request.cookies.get('credentials')
        return authomatic.credentials(serialized_credentials)


def login_required(handler_method):
    """
    A decorator to mark handlers as requiring logged in permissions

    Redirects to main page on error
    """
    def check_login(self, *args):
        if not self.user:
            self.redirect('/')
            return
        return handler_method(self, *args)
    return check_login 


class LogoutHandler(BaseSessionHandler):

    @login_required
    def get(self):
        # Delete cookies.
        self.response.delete_cookie('user_id')
        self.response.delete_cookie('user_name')
        self.response.delete_cookie('credentials')

        # Redirect home.
        self.redirect('./')

