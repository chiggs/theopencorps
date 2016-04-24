"""
Handler for the various results that get posted back
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
from xml.etree import ElementTree

import theopencorps.auth

from theopencorps.datamodel.models import Push, Project, JUnitTestResult, JUnitTestCase, TravisJob
from theopencorps.handlers.hooks import CustomTravisHookHandler
from theopencorps.datamodel.project import ProjectHelper


def parse_testcase(tree):
    result = JUnitTestCase()
    result.classname = tree.get('classname', '')
    result.name = tree.get('name', '')
    result.time = float(tree.get('time', "0.0"))
    result.passed = True

    if tree.find('failure') is not None:
        result.passed = False
        result.failure = tree.find('failure').text
    if tree.find('error') is not None:
        result.passed = False
        result.error = tree.find('error').text
    if tree.find('skipped') is not None:
        result.passed = False
        result.skipped = tree.find('skipped').text
    if tree.find('system-out') is not None:
        result.stdout = tree.find('system-out').text
    if tree.find('system-err') is not None:
        result.stderr = tree.find('system-err').text
    return result

def parse_testsuite(tree):
    """
    Takes an element that is the root of a testsuite and creates a JUnitTestResult
    """
    result = JUnitTestResult()
    result.tests = int(tree.get('tests', '0'))
    result.errors = int(tree.get('errors', '0'))
    result.failures = int(tree.get('failures', '0'))
    result.skipped = int(tree.get('skipped', '0'))
    result.valid = True

    result.testcases = [parse_testcase(testcase) for testcase in tree.iterfind('testcase')]

    # Sanity check the numbers?
    result.passed = result.tests - result.errors - result.failures - result.skipped
    total = sum([1 if testcase.passed else 0 for testcase in result.testcases])

    if result.passed != total:
        logging.warning("Invalid XML? Testsuite claims %d tests passed but only found %d",
                      result.passed, total)
    else:
        logging.info("Testsuite reports %d tests passed", result.passed)

    result.time = sum([testcase.time for testcase in result.testcases])
    return result



class JunitResultsHandler(CustomTravisHookHandler):

    @theopencorps.auth.validate_token("X-Hub-Signature")
    def post(self, project):
        job = self.get_job()
        build = self.get_build()

        try:
            root = ElementTree.fromstring(self.request.body)
        except Exception:
            logging.warning("Invalid XML supplied")
            self.response.set_status(404)
            return

        if root.tag == 'testsuites':
            suites = list(root.iterfind('testsuite'))
            if len(suites) != 1:
                logging.warning("Unable to handle multiple testsuites currently")
                self.response.set_status(404)
                return
            root = suites[0]

        testsuite = parse_testsuite(root)
        testsuite.travis_job = job.key
        testsuite.travis_build = build.key
        if self.push is not None:
            testsuite.push = self.push.key
        testsuite.project = project.key
        testsuite.put_async()

        job.insert_or_update()
        job.purge_async()

        build.insert_or_update()
        #build.purge_async()

        logging.info("Put %s", repr(testsuite))

        helper = ProjectHelper(project)
        helper.update_sim_result(passed=testsuite.passed,
                                 failed=testsuite.failures,
                                 errors=testsuite.errors,
                                 skipped=testsuite.skipped)
        project.put()

