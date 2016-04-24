"""
Base definitions for the data model
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


class SHA1Property(ndb.StringProperty):
    """
    Property type for SHA1 commit hashes in git

    Perform some checking of the string
    """
    def _validate(self, value):
        assert len(value) == 40
        assert int(value, 16)
        for char in value:
            assert char in ["0123456789abcdef"]

class OCBaseModel(ndb.Model):
    """
    Collection for any common functionality on data model
    """
    created             = ndb.DateTimeProperty(auto_now_add=True)

    def put(self):
        logging.debug("Storing %s = %s", self.__class__.__name__,
                                         repr(self.to_dict()))
        return ndb.Model.put(self)

    def put_async(self):
        logging.debug("Storing %s = %s", self.__class__.__name__,
                                         repr(self.to_dict()))
        return ndb.Model.put_async(self)


    @ndb.transactional
    def insert_or_update(self):
        """
        Either we insert our new object or merge our changes into the
        existing object
        """
        stored = self.insert()
        if stored is not self:
            stored.merge(self)
            stored.put()
        return stored

    @ndb.transactional
    def insert(self):
        """
        Atomic insertion - don't overwrite if existing

        Returns the new object
        """
        fetch = self.key.get()
        if fetch is None:
            logging.debug("Inserted %s (%s)", self.__class__.__name__,
                                                repr(self.to_dict()))
            self.put()
            return self
        logging.info("Insert collided %s (%s)", fetch.__class__.__name__,
                                            repr(fetch.to_dict()))
        return fetch

    def merge(self, other):
        """
        Combine any changes in "other" into self

        Assumes we have either made the same changes, or changes
        to different members.

        This means we can merge multiple updates together on writeback
        thus reducing the locking required.
        """
        for name, value in other.to_dict().iteritems():
            if name == "created":
                continue
            mine = getattr(self, name)


            if isinstance(mine, list):
                seen = set()
                merged = [x for x in mine + value
                            if not (x in seen or seen.add(x))]

                if merged != mine:
                    logging.info("Merging other.%s = %s into self -> %s",
                                                name, repr(value), repr(merged))
                    setattr(self, name, merged)

            elif not mine and value:
                logging.info("Merging other.%s = %s into self",
                                                name, repr(value))
                setattr(self, name, value)

            elif mine and mine != value:
                logging.warning("Merge conflict self.%s=%s vs %s",
                                name, repr(mine), repr(value))
