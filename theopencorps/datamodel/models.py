"""
This file defines all of the storage objects held in the datastore.

Any objects that are persistent is defined in this file.
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


from google.appengine.ext import ndb
from google.appengine.api import taskqueue

from theopencorps.datamodel import OCBaseModel, SHA1Property

class User(OCBaseModel):
    """
    User Accounts - map onto GitHub user accounts

    Note that github can change usernames

    Tied into Github, but unavoidably so probably.

    Key is the github user ID
    """
    provider            = ndb.StringProperty(default="Github", choices=["Github"])
    login               = ndb.StringProperty()
    user_name           = ndb.StringProperty()
    email               = ndb.StringProperty()
    last_login          = ndb.DateTimeProperty(auto_now_add=True)
    avatar_url          = ndb.StringProperty(indexed=False)
    url                 = ndb.StringProperty(indexed=False)
    html_url            = ndb.StringProperty(indexed=False)


class Repository(OCBaseModel):
    """
    Track a Github repository

    Key:                full_name
    Parent:             None?
    """
    repo_id             = ndb.IntegerProperty()
    provider            = ndb.StringProperty()
    name                = ndb.StringProperty()
    full_name           = ndb.StringProperty()
    url                 = ndb.StringProperty()
    api_url             = ndb.StringProperty()


class Push(OCBaseModel):
    """
    A push is related to a specific push event on a repository

    It is created by a push event notification.

    Key:                sha1 of the commit (after)
    """
    ref                 = ndb.StringProperty()
    before              = SHA1Property()
    after               = SHA1Property()
    fork_merge          = SHA1Property()        # Merge commit pulling upstream into our fork, if at all
    travis_update       = SHA1Property()        # Update to travis.yml we do after this push, if at all
    compare             = ndb.StringProperty(indexed=False)


class Shield(OCBaseModel):
    """
    Representation of a shield object
    """
    subject             = ndb.StringProperty()
    status              = ndb.StringProperty()
    colour              = ndb.StringProperty()
    href                = ndb.StringProperty()

class Project(OCBaseModel):
    """
    A project entry.

    For simplicity we have a one-to-one mapping with Github Projects, therefore the key
    is full_name e.g chiggs/some_repository

    Project creation lifecycle is:

        * New -> create the project object
        * Fork on github
        * Add webhook on github
        * Synchronise on travis
        * Enable hook on travis
        * Commit .travis.yml for the repository

    """
    name                = ndb.StringProperty()
    full_name           = ndb.StringProperty()
    owner               = ndb.KeyProperty(User)
    updated             = ndb.DateTimeProperty(auto_now_add=True)
    description         = ndb.TextProperty()
    languages           = ndb.StringProperty(repeated=True)
    tags                = ndb.StringProperty(repeated=True)
    repo                = ndb.KeyProperty(Repository)

    # List (in order) of all the shields
    shields             = ndb.StructuredProperty(Shield, repeated=True)

    # List (in order) of SVG for each shield (cached)
    shields_svg         = ndb.TextProperty(repeated=True)


    # Secret is used for: HMAC on github, HMAC on results posted
    secret              = SHA1Property(indexed=False)

    # Help us to determine the state of a given project
    github_webhook      = ndb.BooleanProperty(default=False)
    forked              = ndb.BooleanProperty(default=False)
    checked_user_oc_yml = ndb.BooleanProperty(default=False)
    user_oc_yml         = ndb.BooleanProperty(default=False)
    fork_oc_yml         = ndb.BooleanProperty(default=False)
    fork_yml_valid      = ndb.BooleanProperty(default=False)
    fork_yml_invalid    = ndb.BooleanProperty(default=False)
    fork_travis_yml     = ndb.BooleanProperty(default=False)
    travis_sync_req     = ndb.BooleanProperty(default=False)
    travis_webhook      = ndb.BooleanProperty(default=False)
    init_complete       = ndb.BooleanProperty(default=False)
    failure_count       = ndb.IntegerProperty(default=0)
    system_message      = ndb.TextProperty()

    # Pending merges
    pending_merges      = ndb.KeyProperty(Push, repeated=True)


class JUnitTestCase(OCBaseModel):
    """
    JUnit test case - a single test
    """
    classname           = ndb.StringProperty()
    name                = ndb.StringProperty()
    time                = ndb.FloatProperty()
    passed              = ndb.BooleanProperty()
    failure             = ndb.TextProperty()    # Not indexed
    error               = ndb.TextProperty()    # Not indexed
    skipped             = ndb.TextProperty()    # Not indexed
    stderr              = ndb.TextProperty()    # Not indexed
    stdout              = ndb.TextProperty()    # Not indexed





class TravisJob(OCBaseModel):
    """
    Object representing an individual Travis Job

    Key is travis_id
    """
    travis_id           = ndb.IntegerProperty()
    build_id            = ndb.IntegerProperty()
    commit              = SHA1Property()
    repository_id       = ndb.IntegerProperty()
    number              = ndb.StringProperty()
    state               = ndb.StringProperty()
    duration            = ndb.FloatProperty()
    log_id              = ndb.IntegerProperty()
    logfiles            = ndb.StringProperty(repeated=True)
    valid               = ndb.BooleanProperty()


    @staticmethod
    def purge_duplicate_travis_jobs(new_job_id):
        """
        We can receive duplicate job results since travis jobs can
        be restarted.

        This task can be scheduled to remove any old job references
        with the same job number
        """
        valid_job = TravisJob.get_by_id(new_job_id)
        if valid_job is None:
            logging.warning("Received request to purge jobs older than %d but it wasn't found!", new_job_id)
            return

        duplicates = TravisJob.query(ndb.AND(
                TravisJob.repository_id == valid_job.repository_id,
                TravisJob.number == valid_job.number)).fetch()

        for duplicate in duplicates:
            if duplicate.travis_id == valid_job.travis_id:
                continue

            logging.info("Removing duplicate TravisJob: %s",
                                                repr(duplicate.to_dict()))

            results = JUnitTestResult.query(
                    JUnitTestResult.travis_job == duplicate.key).fetch()
            for result in results:
                logging.info("Marking historcal test result as invalid: %s",
                                                repr(result.to_dict()))
                result.valid = False
                result.put_async()
            duplicate.valid = False
            duplicate.put_async()

        logging.debug("Purge of duplicate TravisJobs complete")


    def purge_async(self):
        """
        Should be called after creating a new TravisJob to ensure old duplicates
        are flagged as invalid
        """
        logging.info("Queuing background task to purge old jobs")
        taskqueue.add(url="/jobs/%d/purge" % self.travis_id)





class TravisBuild(OCBaseModel):
    """
    Object representing an individual Travis build

    Key is travis_id
    """
    commit              = SHA1Property()
    travis_id           = ndb.IntegerProperty()
    repository_id       = ndb.IntegerProperty()
    number              = ndb.StringProperty()
    pull_request        = ndb.BooleanProperty()
    state               = ndb.StringProperty()
    duration            = ndb.FloatProperty()
    job_ids             = ndb.IntegerProperty(repeated=True)
    valid               = ndb.BooleanProperty()


class JUnitTestResult(OCBaseModel):
    """
    A data model representing JUnit test results

    """
    errors              = ndb.IntegerProperty()
    failures            = ndb.IntegerProperty()
    skipped             = ndb.IntegerProperty()
    passed              = ndb.IntegerProperty()
    tests               = ndb.IntegerProperty()
    time                = ndb.FloatProperty()
    testcases           = ndb.StructuredProperty(JUnitTestCase, repeated=True)
    travis_job          = ndb.KeyProperty(TravisJob)
    travis_build        = ndb.KeyProperty(TravisBuild)
    push                = ndb.KeyProperty(Push)
    project             = ndb.KeyProperty(Project)

    # A Travis job might restart etc so we may end up with duplicate
    # test results.  In this case, we'll query for travis builds with
    # the same job number and mark those results as invalid
    valid               = ndb.BooleanProperty()



class AlteraSynthResult(OCBaseModel):
    """
    A data model representing JUnit test results

    """
    map_registers_total                         = ndb.IntegerProperty(indexed=False)
    map_registers_synchronous_clear             = ndb.IntegerProperty(indexed=False)
    map_registers_synchronous_load              = ndb.IntegerProperty(indexed=False)
    map_registers_asynchronous_clear            = ndb.IntegerProperty(indexed=False)
    map_registers_asynchronous_load             = ndb.IntegerProperty(indexed=False)
    map_registers_asynchronous_load             = ndb.IntegerProperty(indexed=False)
    map_registers_clock_enable                  = ndb.IntegerProperty(indexed=False)

    map_resources_memory_bits                   = ndb.IntegerProperty(indexed=False)
    map_resources_registers                     = ndb.IntegerProperty(indexed=False)
    map_resources_logic_elements                = ndb.IntegerProperty(indexed=False)
    map_resources_combinatorial_functions       = ndb.IntegerProperty(indexed=False)
    map_resources_dsp_blocks                    = ndb.IntegerProperty(indexed=False)

    fit_logic_elements_total                    = ndb.IntegerProperty(indexed=False)
    fit_logic_elements_combinatorial_only       = ndb.IntegerProperty(indexed=False)
    fit_logic_elements_register_only            = ndb.IntegerProperty(indexed=False)
    fit_logic_elements_combinatorial_and_register=ndb.IntegerProperty(indexed=False)
    fit_logic_elements_four_input_functions     = ndb.IntegerProperty(indexed=False)
    fit_logic_elements_three_input_functions    = ndb.IntegerProperty(indexed=False)
    fit_logic_elements_two_input_functions      = ndb.IntegerProperty(indexed=False)
    fit_logic_elements_normal_mode              = ndb.IntegerProperty(indexed=False)
    fit_logic_elements_arithmetic_mode          = ndb.IntegerProperty(indexed=False)

    fit_resources_maximum_fan_out               = ndb.IntegerProperty(indexed=False)
    fit_resources_highest_non_globa_fan_out     = ndb.IntegerProperty(indexed=False)
    fit_resources_embedded_multiplier_9_bit_elementes = ndb.IntegerProperty(indexed=False)
    fit_resources_average_fan_out               = ndb.FloatProperty(indexed=False)


    travis_job          = ndb.KeyProperty(TravisJob)
    travis_build        = ndb.KeyProperty(TravisBuild)
    push                = ndb.KeyProperty(Push)
    project             = ndb.KeyProperty(Project)

    # A Travis job might restart etc so we may end up with duplicate
    # test results.  In this case, we'll query for travis builds with
    # the same job number and mark those results as invalid
    valid               = ndb.BooleanProperty()
