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
import cloudstorage as gcs

import theopencorps.auth
from theopencorps.handlers.hooks import CustomTravisHookHandler
from theopencorps.datamodel.models import AlteraSynthResult

class LogFileHandler(CustomTravisHookHandler):

    @theopencorps.auth.validate_token("X-Hub-Signature")
    def post(self, project):
        """
        We store the logfile on Google Cloud Storage

        In theory we're creating a large dataset to mine in future... maybe
        """
        travis_job_id = int(self.request.headers.get("Travis-JobID", "0"))
        fhint = self.request.headers.get("Content-Filename", "unknown")

        filename = "/buildlogs/%s/%d/%s" % (project.key.id(), travis_job_id, fhint)

        gcs_file = gcs.open(filename, 'w', content_type='text/plain')
        gcs_file.write(self.request.body)
        gcs_file.close()

        job = self.get_job()
        job.logfiles.append(filename)
        job.insert_or_update()
        job.purge_async()



class QuartusResultHandler(CustomTravisHookHandler):

    @theopencorps.auth.validate_token("X-Hub-Signature")
    def post(self, project):
        """
        Again, store the logfile, but we also parse stuff out
        """
        travis_job_id = int(self.request.headers.get("Travis-JobID", "0"))
        fhint = self.request.headers.get("Content-Filename", "")

        job = self.get_job()
        build = self.get_build()

        synth = AlteraSynthResult()
        synth.travis_job = job.key
        synth.project = project.key
        synth.travis_build = build.key
        if self.push is not None:
            synth.push = self.push.key

        # TODO: parse out metrics from logfiles
        #results = logparser.handle_text(self.request.body, hint=fhint)
        #for result in results:
            #for metric, value in result.iteritems():
                #attribute = "%s_%s" % (result.name, metric)
                #attribute = attribute.lower()
                #attribute = attribute.replate("-", "_")
                #attribute = attribute.replate(".", "_")
                #setattr(synth, attribute, value)

        build.insert_or_update()
        synth.put_async()

        # Write the logfile back to disk
        if not fhint:
            fhint = "unknown"
        filename = "/buildlogs/%s/%d/%s" % (project.key.id(), travis_job_id, fhint)

        gcs_file = gcs.open(filename, 'w', content_type='text/plain')
        gcs_file.write(self.request.body)
        gcs_file.close()

        job.logfiles.append(filename)
        job.insert_or_update()
        job.purge_async()

