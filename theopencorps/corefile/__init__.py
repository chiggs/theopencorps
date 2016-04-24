#!/usr/bin/env python
"""
This module takes a corefile.yml description of a block and performs various
validations and transformations
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

import yaml

class CoreFileException(Exception): pass
class YMLSyntaxError(CoreFileException): pass
class SchemaError(CoreFileException): pass

class SupportedSchema(object):

    _sections = {}
    _version = None

    @classmethod
    def validate(cls, dictionary):
        def recurse_check(schema, sample, path=""):
            for section, items in sample.iteritems():
                if section not in schema:
                    raise SchemaError("Unsupported section %s%s" % (path, section))
                elif callable(schema[section]):
                    if schema[section](items): continue
                    else: raise SchemaError("%s failed validation" % repr(items))
                elif isinstance(items, list):
                    for thing in items:
                        if thing not in schema[section]:
                            raise SchemaError("Unsupported value %s for section %s" % (
                                thing, section))
                    continue
                recurse_check(schema[section], items, path="%s%s." % (path, section))
            return True
        return recurse_check(cls._sections, dictionary)

class SchemaV1(SupportedSchema):

    _version = 1
    _sections = {
        "schema_version": lambda x: x == [1],
        "simulation" : {
            "fusesoc_vunit": lambda x: len(x) == 1,
            "vunit": lambda x: len(x) > 0,
            },
        "synthesis" : {
            "fusesoc": lambda x: len(x) == 1,
            "targets": {"altera" : {}, "xilinx" : {}}
            },
        "documentation": lambda x: len(x) == 1
    }


    @classmethod
    def to_template_variables(cls, yml):
        """
        Returns a dictionary of variables for filling into a template
        """
        rv = {}
        rv["environment_variables"] = []
        if "simulation" in yml:
            simtype = yml["simulation"]
            if "fusesoc_vunit" in simtype:
                rv["fusesoc"] = True
                rv["vunit"] = True
                rv["environment_variables"].append("CORE=%s" % simtype["fusesoc_vunit"][0])
            if "vunit" in simtype:
                rv["vunit"] = True
                rv["environment_variables"].append("VUNIT_SCRIPTFILES=\"%s\"" % " ".join(simtype["vunit"]))
        if "synthesis" in yml and "targets" in yml["synthesis"]:
            if "altera" in yml["synthesis"]["targets"]:
                rv["quartus"] = True
            if "xilinx" in yml["synthesis"]["targets"]:
                rv["vivado"] = True
        return rv


class CoreFile(object):

    def __init__(self, corefile=None):
        """
        kwargs: corefile (fileobj or string) - file object to initialise from
        """
        self.yaml_dict = {}
        if corefile is not None:
            self.load(corefile)


    def load(self, corefile):
        """
        Convenience method that takes either a file object or filename as argument
        """
        if isinstance(corefile, str):
            self.load_filename(corefile)
        else:
            self.load_file(corefile)

    def load_filename(self, corefile):
        """
        Load contents from filename
        """
        with open(corefile, 'r') as f:
            self.load_file(f)

    def load_file(self, fileobj):
        """
        Load from a file object
        """
        try:
            self.yaml_dict = yaml.safe_load(fileobj)
        except yaml.YAMLError as e:
            raise YMLSyntaxError("Failed to parse YML file: %s" % repr(e))
        SchemaV1.validate(self.yaml_dict)

    def to_template_dict(self):
        """
        Generate a .travis.yml file based on the parsed YML file
        """
        return SchemaV1.to_template_variables(self.yaml_dict)

