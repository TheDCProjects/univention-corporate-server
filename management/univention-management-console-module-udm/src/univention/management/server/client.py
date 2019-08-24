#!/usr/bin/python2.7
# -*- coding: utf-8 -*-
#
# Univention Management Console
#  Univention Directory Manager Module
#
# Copyright 2019 Univention GmbH
#
# http://www.univention.de/
#
# All rights reserved.
#
# The source code of this program is made available
# under the terms of the GNU Affero General Public License version 3
# (GNU AGPL V3) as published by the Free Software Foundation.
#
# Binary versions of this program provided by Univention to you as
# well as other copyrighted, protected or trademarked materials like
# Logos, graphics, fonts, specific documentations and configurations,
# cryptographic keys etc. are subject to a license agreement between
# you and Univention and not subject to the GNU AGPL V3.
#
# In the case you use this program under the terms of the GNU AGPL V3,
# the program is provided in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public
# License with the Debian GNU/Linux or Univention distribution in file
# /usr/share/common-licenses/AGPL-3; if not, see
# <http://www.gnu.org/licenses/>.
"""
Sample Client for the UDM REST API.

>>> from univention.management.server.client import UDM
>>> uri = 'http://localhost/univention/udm/'
>>> udm = UDM.http(uri, 'Administrator', 'univention')
>>> module = udm.get('users/user')
>>> print('Found {}'.format(module))
>>> obj = next(module.search())
>>> if obj:
>>> 	obj = obj.open()
>>> print('Object {}'.format(obj))
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import sys
import time
import requests

if sys.version_info.major > 2:
	import http.client
	http.client._MAXHEADERS = 1000
else:
	import httplib
	httplib._MAXHEADERS = 1000


class HTTPError(Exception):

	def __init__(self, code, message, response):
		self.code = code
		self.response = response
		super(HTTPError, self).__init__(message)


class BadRequest(HTTPError):
	pass


class Unauthorized(HTTPError):
	pass


class Forbidden(HTTPError):
	pass


class NotFound(HTTPError):
	pass


class PreconditionFailed(HTTPError):
	pass


class UnprocessableEntity(HTTPError):
	pass


class ServerError(HTTPError):
	pass


class ServiceUnavailable(HTTPError):
	pass


class Session(object):

	def __init__(self, credentials, language='en-US', reconnect=True):
		self.language = language
		self.credentials = credentials
		self.session = self.create_session()
		self.reconnect = reconnect
		self.default_headers = {
			'Accept': 'application/json; q=1; text/html; q=0.2, */*; q=0.1',
			'Accept-Language': self.language,
		}

	def create_session(self):
		sess = requests.session()
		sess.auth = (self.credentials.username, self.credentials.password)
		try:
			from cachecontrol import CacheControl
		except ImportError:
			#print('Cannot cache!')
			pass
		else:
			sess = CacheControl(sess)
		return sess

	def get_method(self, method):
		sess = self.session
		return {
			'GET': sess.get,
			'POST': sess.post,
			'PUT': sess.put,
			'DELETE': sess.delete,
			'PATCH': sess.patch,
			'OPTIONS': sess.options,
		}.get(method.upper(), sess.get)

	def request(self, method, uri, data=None, **headers):
		return self.make_request(method, uri, data, **headers)[1]

	def make_request(self, method, uri, data=None, **headers):
		if method in ('GET', 'HEAD'):
			params = data
			json = None
		else:
			params = None
			json = data

		def doit():
			response = self.get_method(method)(uri, params=params, json=json, headers=dict(self.default_headers, **headers))
			data = self.eval_response(response)
			return response, data
		for i in range(5):
			try:
				return doit()
			except ServiceUnavailable as exc:
				if not self.reconnect:
					raise
				try:
					retry_after = min(5, int(exc.response.headers.get('Retry-After', 1)))
				except ValueError:
					retry_after = 1
				time.sleep(retry_after)
				return doit()

	def eval_response(self, response):
		if response.status_code >= 299:
			msg = '{} {}: {}'.format(response.request.method, response.url, response.status_code)
			try:
				json = response.json()
			except ValueError:
				pass
			else:
				if isinstance(json, dict):
					if 'error' in json:
						server_message = json['error'].get('message')
						# traceback = json['error'].get('traceback')
						if server_message:
							msg += '\n{}'.format(server_message)
			errors = {400: BadRequest, 404: NotFound, 403: Forbidden, 401: Unauthorized, 412: PreconditionFailed, 422: UnprocessableEntity, 500: ServerError, 503: ServiceUnavailable}
			cls = HTTPError
			cls = errors.get(response.status_code, cls)
			raise cls(response.status_code, msg, response)
		return response.json()


class Client(object):

	def __init__(self, client):
		self.client = client


class UDM(Client):

	@classmethod
	def http(cls, uri, username, password):
		return cls(uri, username, password)

	def __init__(self, uri, username, password, *args, **kwargs):
		self.uri = uri
		self.username = username
		self.password = password
		self._api_version = None
		super(UDM, self).__init__(Session(self), *args, **kwargs)

	def modules(self):
		# TODO: cache - needs server side support
		entry = self.client.request('GET', self.uri)
		prefix_modules = entry['_links']['udm/relation/object-modules']
		for prefix_module in prefix_modules:
			entry = self.client.request('GET', prefix_module['href'])
			module_infos = entry.get('_links', {}).get('udm/relation/object-types', [])
			for module_info in module_infos:
				yield Module(self, module_info['href'], module_info['name'], module_info['title'])

	def version(self, api_version):
		self._api_version = api_version
		return self

	def obj_by_dn(self, dn):
		# TODO: Needed?
		raise NotImplementedError()

	def get(self, name):
		for module in self.modules():
			if module.name == name:
				return module

	def __repr__(self):
		return 'UDM(uri={}, username={}, password=****, version={})'.format(self.uri, self.username, self._api_version)


class Module(Client):

	def __init__(self, udm, uri, name, title, *args, **kwargs):
		super(Module, self).__init__(udm.client, *args, **kwargs)
		self.udm = udm
		self.uri = uri
		self.username = udm.username
		self.password = udm.password
		self.name = name
		self.title = title
		self.relations = {}

	def load_relations(self):
		if self.relations:
			return
		entry = self.client.request('GET', self.uri)
		self.relations = entry.get('_links', {})

	def __repr__(self):
		return 'Module(uri={}, name={})'.format(self.uri, self.name)

	def new(self, superordinate=None):
		return Object(self.udm, None, None, {}, [], {}, None, superordinate, None)

	def get(self, dn):
		for obj in self.search(position=dn, scope='base'):
			return obj.open()

	def get_by_entry_uuid(self, uuid):
		for obj in self.search(filter={'entryUUID': uuid}, scope='base'):
			return obj.open()

	def get_by_id(self, dn):
		# TODO: Needed?
		raise NotImplementedError()

	def search(self, filter=None, position=None, scope='sub', hidden=False, superordinate=None, opened=False):
		data = {}
		if isinstance(filter, dict):
			for prop, val in filter.items():
				data['property'] = prop
				data['propertyvalue'] = val
		elif isinstance(filter, basestring):
			data['filter'] = filter
		if superordinate:
			data['superordinate'] = superordinate
		data['position'] = position
		data['scope'] = scope
		data['hidden'] = '1' if hidden else ''
		if opened:
			data['properties'] = '*'
		self.load_relations()
		entries = self.client.request('GET', self.relations['search'][0]['href'], data=data)
		for entry in entries['entries']:
			if opened:
				yield Object(self.udm, entry['objectType'], entry['dn'], entry['properties'], entry['options'], entry['policies'], entry['position'], entry.get('superordinate'), entry['uri'], links=entry.get('_links', {}))  # NOTE: this is missing last-modified, therefore no conditional request is done on modification!
			else:
				yield ShallowObject(self.udm, entry['dn'], entry['uri'])

	def create(self, properties, options, policies, position, superordinate=None):
		obj = self.create_template(position=position, superordinate=superordinate)
		obj.options = options
		obj.properties = properties
		obj.policies = policies
		obj.position = position
		obj.superordinate = superordinate
		obj.save()
		return obj

	def create_template(self, position=None, superordinate=None):
		self.load_relations()
		data = {'position': position, 'superordinate': superordinate}
		entry = self.client.request('GET', self.relations['create-form'][0]['href'], data=data)['entry']
		return Object(self.udm, self.name, None, entry['properties'], entry['options'], entry['policies'], entry['position'], entry.get('superordinate'), self.uri, links=entry.get('_links', {}))


class ShallowObject(Client):

	def __init__(self, udm, dn, uri, *args, **kwargs):
		super(ShallowObject, self).__init__(udm.client, *args, **kwargs)
		self.dn = dn
		self.udm = udm
		self.uri = uri

	def open(self):
		resp, entry = self.client.make_request('GET', self.uri)
		return Object(self.udm, entry['objectType'], entry['dn'], entry['properties'], entry['options'], entry['policies'], entry['position'], entry.get('superordinate'), entry['uri'], links=entry.get('_links', {}), etag=resp.headers.get('Etag'), last_modified=resp.headers.get('Last-Modified'))

	def __repr__(self):
		return 'ShallowObject(dn={})'.format(self.dn)


class References(object):

	def __init__(self, obj=None):
		self.obj = obj

	def __getitem__(self, item):
		links = [ShallowObject(self.obj.udm, x['name'], x['href']) for x in self.obj.links['udm/relation/object-reference/%s' % (item,)]]
		return links

	def __get__(self, obj, cls=None):
		return type(self)(obj)


class Object(Client):

	objects = References()

	@property
	def props(self):
		return self.properties

	@props.setter
	def props(self, props):
		self.properties = props

	@property
	def module(self):
		return self.udm.get(self.object_type)

	def __init__(self, udm, object_type, dn, properties, options, policies, position, superordinate, uri, links=None, etag=None, last_modified=None, *args, **kwargs):
		super(Object, self).__init__(udm.client, *args, **kwargs)
		self.udm = udm
		self.object_type = object_type
		self.dn = dn
		self.properties = properties
		self.options = options
		self.policies = policies
		self.position = position
		self.superordinate = superordinate
		self.uri = uri
		self.links = links or {}
		self.etag = etag
		self.last_modified = last_modified

	def __repr__(self):
		return 'Object(module={}, dn={}, uri={})'.format(self.object_type, self.dn, self.uri)

	def reload(self):
		obj = self.module.get(self.dn)
		self._copy_from_obj(obj)

	def save(self):
		if self.dn:
			return self._modify()
		else:
			return self._create()

	def delete(self, remove_referring=False):
		return self.client.request('DELETE', self.uri)

	def _modify(self):
		data = {
			'properties': self.props,
			'options': self.options,
			'policies': self.policies,
			'position': self.position,
			'superordinate': self.superordinate,
		}
		headers = dict((key, value) for key, value in {
			'If-Unmodified-Since': self.last_modified,
			'If-Match': self.etag,
		}.items() if value)
		resp, entry = self.client.make_request('PUT', self.uri, data=data, **headers)
		if resp.status_code == 201 and 'Location' in resp.headers:  # move()
			resp, entry = self.client.make_request('GET', resp.headers['Location'])
		self.dn = entry['dn']
		self.reload()

	def _copy_from_obj(self, obj):
		self.dn = obj.dn
		self.props = obj.props
		self.options = obj.options
		self.policies = obj.policies
		self.position = obj.position
		self.superordinate = obj.superordinate
		self.udm = obj.udm
		self.uri = obj.uri
		self.links = obj.links
		self.etag = obj.etag
		self.last_modified = obj.last_modified

	def _create(self):
		data = {
			'properties': self.props,
			'options': self.options,
			'policies': self.policies,
			'position': self.position,
			'superordinate': self.superordinate,
		}
		resp, entry = self.client.make_request('POST', self.module.uri, data=data)
		if resp.status_code in (200, 201) and 'Location' in resp.headers:
			uri = resp.headers['Location']
			obj = ShallowObject(self.udm, None, uri).open()
			self._copy_from_obj(obj)
		return entry
