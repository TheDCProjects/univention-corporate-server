import sys

from univention.config_registry import ConfigRegistry
from univention.testing.codes import TestCodes
import univention.testing.utils as utils
from univention.lib.umc_connection import UMCConnection


class TestUMCSystem(object):
    """
    A base class for testing UMC-system
    """

    def __init__(self):
        """Test Class constructor"""
        self.username = None
        self.password = None
        self.hostname = None
        self.Connection = None

        self.UCR = ConfigRegistry()

    def reload_ucr(self):
        """Reload the UCR variables """
        self.UCR.load()

    def get_ucr_credentials(self):
        """Get credentials from the registry"""
        try:
            self.reload_ucr()
            self.username = self.UCR['tests/domainadmin/account']
            self.password = self.UCR['tests/domainadmin/pwd']
            self.hostname = self.UCR['hostname']

            # extracting the 'uid' value of the username string
            self.username = self.username.split(',')[0][len('uid='):]
        except Exception as exc:
            print "Failed to get the UCR username and/or a password for test"
            self.return_code_result_skip()
        if self.hostname is None:
            print "The hostname in the UCR should not be 'None'"
            self.return_code_result_skip()

    def create_connection_authenticate(self):
        """Create UMC connection and authenticate"""
        try:
            self.Connection = UMCConnection(self.hostname)
            self.Connection.auth(self.username, self.password)
        except Exception as exc:
            utils.fail("Failed to authenticate, hostname '%s' : %s" %
                       (self.hostname, exc))

    def make_query_request(self, prefix, options=None):
        """
        Makes a '/query' UMC request with a provided 'prefix' argument,
        returns request result.
        """
        try:
            request_result = self.Connection.request(prefix + '/query',
                                                     options)
            if not request_result:
                utils.fail("Request '%s/query' failed, no result, hostname %s"
                           % (prefix, self.hostname))
            return request_result
        except Exception as exc:
            utils.fail("Exception while making '%s/query' request: %s"
                       % (prefix, exc))

    def make_top_query_request(self):
        """Makes a 'top/query' UMC request and returns result"""
        return self.make_query_request('top')

    def make_service_query_request(self):
        """Makes a 'services/query' UMC request and returns result"""
        return self.make_query_request('services')

    def check_service_presence(self, request_result, service_name):
        """
        Check if the service with 'service_name' was listed in the response
        'request_result'. Returns 'missing software' code 137 when missing.
        """
        for result in request_result:
            if result['service'] == service_name:
                break
        else:
            print("The '%s' service is missing in the UMC response: "
                  "%s" % (service_name, request_result))
            sys.exit(TestCodes.REASON_INSTALL)

    def check_obj_exists(self, name, obj_type):
        """
        Checks if user, group or policy object with provided 'name' exists
        via UMC 'udm/query' request, returns True when exists.
        Object type selected by 'obj_type' argument.
        """
        options = {"container": "all",
                   "objectType": obj_type,
                   "objectProperty": "None",
                   "objectPropertyValue": "",
                   "hidden": False}
        try:
            request_result = self.Connection.request('udm/query', options,
                                                     obj_type)
            if not request_result:
                utils.fail("Request 'udm/query' with options '%s' "
                           "failed, hostname '%s'" % (options, self.hostname))
            for result in request_result:
                if result.get('name') == name:
                    return True
        except Exception as exc:
            utils.fail("Exception while making 'udm/query' request: %s" %
                       exc)

    def delete_obj(self, name, obj_type, flavor):
        """
        Deletes object with a 'name' by making UMC-request 'udm/remove'
        with relevant options and flavor depending on 'obj_type'
        Supported types are: users, groups and policies.
        """
        print "Deleting test object '%s' with a name: '%s'" % (obj_type, name)

        if obj_type == 'users':
            obj_identifier = "uid=" + name + ",cn=" + obj_type + ","
        elif obj_type == 'groups':
            obj_identifier = "cn=" + name + ",cn=" + obj_type + ","
        elif obj_type == 'policies':
            obj_identifier = "cn=" + name + ",cn=UMC,cn=" + obj_type + ","
        else:
            utils.fail("The object identifier format is unknown for the "
                       "provided object type '%s'" % obj_type)

        obj_identifier = obj_identifier + self.ldap_base
        options = [{"object": obj_identifier,
                    "options": {"cleanup": True,
                                "recursive": True}}]
        try:
            request_result = self.Connection.request('udm/remove',
                                                     options,
                                                     flavor)
            if not request_result:
                utils.fail("Request 'udm/remove' to delete object with options"
                           " '%s' failed, hostname %s"
                           % (options, self.hostname))
            if not request_result[0].get('success'):
                utils.fail("Request 'udm/remove' to delete object with options"
                           " '%s' failed, no success = True in response, "
                           "hostname %s" % (options, self.hostname))
        except Exception as exc:
            utils.fail("Exception while making 'udm/remove' request: %s" %
                       exc)

    def return_code_result_skip(self):
        """Method to stop the test with the code 77, RESULT_SKIP """
        sys.exit(TestCodes.RESULT_SKIP)
