#
# Like what you see? Join us!
# https://www.univention.com/about-us/careers/vacancies/
#
# Copyright 2004-2024 Univention GmbH
#
# https://www.univention.de/
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
# <https://www.gnu.org/licenses/>.

"""|UDM| basic functionality"""

from __future__ import annotations

import copy
import re
import sys
import time
from logging import getLogger
from re import Match
from typing import TYPE_CHECKING, Any

import unidecode
from ldap.filter import filter_format

import univention.admin.localization
import univention.config_registry
import univention.logging
from univention.admin._ucr import configRegistry


if TYPE_CHECKING:
    from collections.abc import Callable, Container, Iterable

    from univention.admin.handlers import simpleLdap
    from univention.admin.layout import Tab
    from univention.admin.types import TypeHint


log = getLogger('ADMIN')


__all__ = ('configRegistry', 'extended_attribute', 'hook', 'mapping', 'modules', 'objects', 'option', 'pattern_replace', 'policiesGroup', 'property', 'syntax', 'ucr_overwrite_layout', 'ucr_overwrite_module_layout', 'ucr_overwrite_properties')

ucr_property_prefix = 'directory/manager/web/modules/%s/properties/'


def ucr_overwrite_properties(module: Any, lo: univention.admin.uldap.access) -> None:
    """Overwrite properties in property_descriptions by UCR variables"""
    ucr_prefix = ucr_property_prefix % module.module
    if not module:
        return

    for var in configRegistry.keys():
        if not var.startswith(ucr_prefix):
            continue
        try:
            prop_name, attr = var[len(ucr_prefix):].split('/', 1)
            # ignore internal attributes
            log.debug('ucr_overwrite_properties: found variable: %s', var)
            if attr.startswith('__'):
                continue
            if attr == 'default':
                # a property object is instantiated with default=...
                #   but internally uses "base_default" as member variable
                #   "default" is an instance_method...
                attr = 'base_default'
            if prop_name in module.property_descriptions:
                prop = module.property_descriptions[prop_name]
                log.debug('ucr_overwrite_properties: found property')
                if hasattr(prop, attr):
                    new_prop_val = configRegistry[var]
                    old_prop_val = getattr(prop, attr)
                    if old_prop_val is None:
                        # if the attribute was None the type cast
                        #   will fail. best bet is str as type
                        old_prop_val = ''
                    prop_val_type = type(old_prop_val)
                    log.debug('ucr_overwrite_properties: set property attribute %s to %s', attr, new_prop_val)
                    if attr in ('syntax', ):
                        if hasattr(univention.admin.syntax, new_prop_val):
                            syntax = getattr(univention.admin.syntax, new_prop_val)
                            setattr(prop, attr, syntax())
                        else:
                            if lo.searchDn(filter=filter_format(univention.admin.syntax.LDAP_Search.FILTER_PATTERN, [new_prop_val])):
                                syntax = univention.admin.syntax.LDAP_Search(new_prop_val)
                                syntax._load(lo)
                                setattr(prop, attr, syntax)
                            else:
                                log.error("ucr_overwrite_properties: UCR variable %s does not refer to a known UDM syntax: '%s'", var, new_prop_val)
                    elif prop_val_type is bool:
                        setattr(prop, attr, configRegistry.is_true(None, None, new_prop_val))
                    else:
                        setattr(prop, attr, prop_val_type(new_prop_val))
                    log.debug('ucr_overwrite_properties: get property attribute: %s (type %s)', old_prop_val, prop_val_type)
        except Exception:
            log.exception('ucr_overwrite_properties: failed to set property attribute:')
            continue


def pattern_replace(pattern: str, object: Any) -> str:
    """
    Replaces patterns like `<attribute:command,...>[range]` with values
    of the specified UDM attribute.
    """
    global_commands: list[str] = []

    def modify_text(text: str, commands: list[str]) -> str:
        # apply all string commands
        for iCmd in commands:
            if iCmd == 'lower':
                text = text.lower()
            elif iCmd == 'upper':
                text = text.upper()
            elif iCmd == 'umlauts':
                if isinstance(text, bytes):  # Python 2
                    text = text.decode('UTF-8')
                # We need this to handle german umlauts, e.g. ä -> ae
                for umlaut, code in property.UMLAUTS.items():
                    text = text.replace(umlaut, code)
                text = unidecode.unidecode(text)
            elif iCmd == 'alphanum':
                whitelist = configRegistry.get('directory/manager/templates/alphanum/whitelist', '')
                if isinstance(whitelist, bytes):  # Python 2
                    whitelist = whitelist.decode('UTF-8')
                if isinstance(text, bytes):
                    text = text.decode('UTF-8')
                text = ''.join([c for c in text if (c.isalnum() or c in whitelist)])
            elif iCmd in ('trim', 'strip'):
                text = text.strip()
        return text

    def repl(match: Match[str]) -> str:
        key = match.group('key')
        ext = match.group('ext')
        strCommands = []

        # check within the key for additional commands to be applied on the string
        # (e.g., 'firstname:lower,umlaut') these commands are found after a ':'
        if ':' in key:
            # get the corrected key without following commands
            key, tmpStr = key.rsplit(':', 1)

            # get all commands in lower case and without leading/trailing spaces
            strCommands = [iCmd.lower().strip() for iCmd in tmpStr.split(',')]

            # if this is a list of global commands store the
            # commands and return an empty string
            if not key:
                global_commands.extend(strCommands)
                return ''

        # make sure the key value exists
        if key in object and object[key]:  # noqa: RUF019
            val = modify_text(object[key], strCommands)
            # try to apply the indexing instructions, indicated through '[...]'
            if ext:
                try:
                    return eval('val%s' % (ext))  # noqa: S307
                except SyntaxError:
                    return val
            return val

        elif key == 'dn' and object.dn:
            return object.dn
        return ''

    regex = re.compile(r'<(?P<key>[^>]+)>(?P<ext>\[[\d:]+\])?')
    value = regex.sub(repl, pattern, 0)
    if global_commands:
        value = modify_text(value, global_commands)
    return value


class property:
    UMLAUTS = {
        'Ä': 'Ae',
        'Ö': 'Oe',
        'Ü': 'Ue',
        'ä': 'ae',
        'ö': 'oe',
        'ü': 'ue',
        'Þ': 'P',
        'ð': 'o',
        'þ': 'p',
    }

    def __init__(
            self,
            short_description: str = '',
            long_description: str = '',
            syntax: type | Any = None,
            module_search: None = None,
            multivalue: bool = False,
            one_only: bool = False,
            parent: None = None,
            options: list[str] = [],
            license: list[str] = [],
            required: bool = False,
            may_change: bool = True,
            identifies: bool = False,
            unique: bool = False,
            default: bool | int | str | list[str] | tuple[Any, list[str]] | tuple[Callable, list[str], Any] | None = None,
            prevent_umc_default_popup: bool = False,
            dontsearch: bool = False,
            show_in_lists: bool = True,
            cli_enabled: bool = True,
            editable: bool = True,
            configObjectPosition: None = None,
            configAttributeName: None = None,
            include_in_default_search: bool = False,
            nonempty_is_default: bool = False,
            readonly_when_synced: bool = False,
            size: str | None = None,
            copyable: bool = False,
            type_class: type[TypeHint] | None = None,
            lazy_loading_fn: str | None = None,
    ) -> None:
        """
        |UDM| property.

        :param short_description: a short descriptive text - shown below the input filed in |UMC| by default.
        :param long_description: a long descriptive text - shown only on demand in |UMC|.
        :param syntax: a syntax class or instance to validate the value.
        :param module_search: UNUSED?
        :param multivalue: allow only a single value (`False`) or multiple values (`True`) .
        :param one_only: UNUSED?
        :param parent: UNUSED?
        :param options: List of options, which enable this property.
        :param license: List of license strings, which are required to use this property.
        :param required: `True` for a required property, `False` for an optional property.
        :param may_change: `True` if the property can be changed after the object has been created, `False` when the property can only be specified when the object is created.
        :param identifies: `True` if the property is part of the set of properties, which are required to uniquely identify the object. The properties are used by default to build |RDN| for a new object.
        :param unique: `True` if the property must be unique for all object instances.
        :param default: The default value for the property when a new object is created.
        :param prevent_umc_default_popup: `True` to prevent a pop-up dialog in |UMC| when the default value is not set.
        :param dontsearch: `True` to prevent searches using the property.
        :param show_in_lists: `False` to prevent it from being shown in the CLI.
        :param cli_enabled: `True` to be able to set the attribute in the CLI.
        :param editable: `False` prevents the property from being modified by the user; it still can be modified by code.
        :param configObjectPosition: UNUSED?
        :param configAttributeName: UNUSED?
        :param include_in_default_search: The default search searches this property when set to `True`.
        :param nonempty_is_default: `True` selects the first non-empty value as the default. `False` always selects the first default value, even if it is empty.
        :param readonly_when_synced: `True` only shows the value as read-only when synchronized from some upstream database.
        :param size: The |UMC| widget size; one of :py:data:`univention.admin.syntax.SIZES`.
        :param copyable: With `True` the property is copied when the object is cloned; with `False` the new object will use the default value.
        :param type_class: An optional Typing class which overwrites the syntax class specific type.
        :param lazy_loading_fn: An optional function name that implements loading additional expensive properties if requested.
        """
        self.short_description = short_description
        self.long_description = long_description
        if isinstance(syntax, type):
            self.syntax = syntax()
        else:
            self.syntax = syntax
        self.module_search = module_search
        self.multivalue = multivalue
        self.one_only = one_only
        self.parent = parent
        self.options = options or []
        self.license = license or []
        self.required = required
        self.may_change = may_change
        self.identifies = identifies
        self.unique = unique
        self.base_default = default
        self.prevent_umc_default_popup = prevent_umc_default_popup
        self.dontsearch = dontsearch
        self.show_in_lists = show_in_lists
        self.cli_enabled = cli_enabled
        self.editable = editable
        self.configObjectPosition = configObjectPosition
        self.configAttributeName = configAttributeName
        self.templates: list[simpleLdap] = []
        self.include_in_default_search = include_in_default_search
        self.threshold = int(configRegistry.get('directory/manager/web/sizelimit', '2000') or 2000)
        self.nonempty_is_default = nonempty_is_default
        self.readonly_when_synced = readonly_when_synced
        self.size = size
        self.copyable = copyable
        self.type_class = type_class
        self.lazy_loading_fn = lazy_loading_fn

    def new(self) -> list[str] | None:
        return [] if self.multivalue else None

    def _replace(self, res, object):
        return pattern_replace(copy.copy(res), object)

    def default(self, object: simpleLdap) -> Any:
        base_default: bool | int | str | list[str] | tuple[Any, list[str]] | tuple[Callable, list[str], Any] | None = copy.copy(self.base_default)
        if not object.set_defaults:
            return [] if self.multivalue else ''

        if not base_default:
            return self.new()

        if isinstance(base_default, str):
            return self._replace(base_default, object)

        bd0 = base_default[0]

        # we can not import univention.admin.syntax here (recursive import) so we need to find another way to identify a complex syntax
        if getattr(self.syntax, 'subsyntaxes', None) is not None and isinstance(bd0, list | tuple) and not self.multivalue:
            return bd0

        if isinstance(bd0, str):
            # multivalue defaults will only be a part of templates, so not multivalue is the common way for modules
            if not self.multivalue:  # default=(template-str, [list-of-required-properties])
                if all(object[p] for p in base_default[1]):
                    for p in base_default[1]:
                        bd0 = bd0.replace('<%s>' % (p,), object[p])
                    return bd0
                return self.new()
            else:  # multivalue
                if all(isinstance(bd, str) for bd in base_default):
                    return [self._replace(bd, object) for bd in base_default]
                # must be a list of loaded extended attributes then, so we return it if it has content
                # return the first element, this is only related to empty extended attributes which are loaded wrong, needs to be fixed elsewhere
                if bd0:
                    return [bd0]
                return self.new()

        if callable(bd0):  # default=(func_obj_extra, [list-of-required-properties], extra-arg)
            if all(object[p] for p in base_default[1]):
                return bd0(object, base_default[2])
            return self.new()

        return self.new()

    def safe_default(self, object):
        def safe_parse(default):
            if not default:
                return False
            try:
                self.syntax.parse(default)
                return True
            except Exception:
                return False
        defaults = self.default(object)
        if isinstance(defaults, list):
            return [self.syntax.parse(d) for d in defaults if safe_parse(d)]
        elif safe_parse(defaults):
            return self.syntax.parse(defaults)
        return defaults

    def check_default(self, object: Any) -> None:
        defaults = self.default(object)
        try:
            if isinstance(defaults, list):
                for d in defaults:
                    if d:
                        self.syntax.parse(d)
            elif defaults:
                self.syntax.parse(defaults)
        except univention.admin.uexceptions.valueError:
            raise univention.admin.uexceptions.templateSyntaxError([t['name'] for t in self.templates])

    def matches(self, options: Iterable[str]) -> bool:
        if not self.options:
            return True
        return bool(set(self.options).intersection(set(options)))

    def lazy_load(self, obj):
        if self.lazy_loading_fn:
            getattr(obj, self.lazy_loading_fn)()


class option:
    """|UDM| option to make properties conditional."""

    def __init__(self, short_description: str = '', long_description: str = '', default: int = 0, editable: bool = False, disabled: bool = False, objectClasses: Iterable[str] | None = None, is_app_option: bool = False) -> None:
        self.short_description = short_description
        self.long_description = long_description
        self.default = default
        self.editable = editable
        self.disabled = disabled
        self.is_app_option = is_app_option
        self.objectClasses = set()
        if objectClasses:
            self.objectClasses = set(objectClasses)

    def matches(self, objectClasses: Container[str]) -> bool:
        if not self.objectClasses:
            return True
        return all(not oc not in objectClasses for oc in self.objectClasses)


def ucr_overwrite_layout(module: Any, ucr_property: str, tab: Tab) -> bool | None:
    """Overwrite the advanced setting in the layout"""
    desc = tab['name']
    if hasattr(tab['name'], 'data'):
        desc = tab.tab['name'].data
    # replace invalid characters by underscores
    desc = re.sub(univention.config_registry.invalid_key_chars, '_', desc).replace('/', '_')
    return configRegistry.is_true('directory/manager/web/modules/%s/layout/%s/%s' % (module, desc, ucr_property), None)


def ucr_overwrite_module_layout(module: Any) -> None:
    """Overwrite the tab layout through |UCR| variables."""
    log.debug("layout overwrite")
    # there are modules without a layout definition
    if not hasattr(module, 'layout'):
        return

    new_layout = []
    for tab in module.layout[:]:
        desc = tab.label
        if hasattr(tab.label, 'data'):
            desc = tab.label.data

        # replace invalid characters by underscores
        desc = re.sub(univention.config_registry.invalid_key_chars, '_', desc).replace('/', '_')

        tab_layout = configRegistry.get('directory/manager/web/modules/%s/layout/%s' % (module.module, desc))
        log.debug("layout overwrite: tab_layout='%s'", tab_layout)
        tab_name = configRegistry.get('directory/manager/web/modules/%s/layout/%s/name' % (module.module, desc))
        log.debug("layout overwrite: tab_name='%s'", tab_name)
        tab_descr = configRegistry.get('directory/manager/web/modules/%s/layout/%s/description' % (module.module, desc))
        log.debug("layout overwrite: tab_descr='%s'", tab_descr)

        if tab_name:
            tab['name'] = tab_name

        if tab_descr:
            tab['description'] = tab_descr

        # for now the layout modification from UCS 2.4 is disabled (see Bug #26673)
        # (this piece of code does not respect the tab-group-hierarchie of UCS 3.0)
        # if tab_layout and tab_layout.lower() != 'none':
        #    layout = []
        #    for row in tab_layout.split( ';' ):
        #        line = []
        #        for col in row.split( ',' ):
        #            col = col.strip()
        #            if not col:
        #                continue
        #            if col in module.property_descriptions:
        #                line.append( col )
        #            else:
        #                log.error("layout overwrite: unknown property: %s", col )
        #        layout.append( line )
        #    tab[ 'layout' ] = { 'label' : _( 'General' ), 'layout' : layout }

        if not tab_layout or tab_layout.lower() != 'none':
            # disable specified properties via UCR
            log.debug('ucr_overwrite_module_layout: trying to hide properties on tab %s', desc)
            ucr_prefix = ucr_property_prefix % module.module
            for var in configRegistry.keys():
                if not var.startswith(ucr_prefix):
                    continue
                prop, attr = var[len(ucr_prefix):].split('/', 1)
                # ignore invalid/unknown UCR variables
                if '/' in attr:
                    continue
                if attr in ('__hidden') and configRegistry.is_true(var):
                    removed, layout = tab.remove(prop)
                    log.debug('ucr_overwrite_module_layout: tried to hide property: %s (found=%s)', prop, removed)
            new_layout.append(tab)

    module.layout = new_layout

    # sort tabs: All apps occur alphabetical after the "Apps" / "Options" tab
    app_tabs = [x for x in module.layout if x.is_app_tab]
    app_tabs.sort(key=lambda x: x.label.lower())
    layout = [x for x in module.layout if not x.is_app_tab]
    pos = ([i for i, x in enumerate(layout, 1) if x.label == 'Apps'] or [len(layout)])[0]
    layout[pos:pos] = app_tabs
    module.layout = layout


class extended_attribute:
    """Extended attributes extend |UDM| and |UMC| with additional properties defined in |LDAP|."""

    def __init__(self, name: str, objClass: str, ldapMapping: Any, deleteObjClass: bool = False, syntax: str = 'string', hook: Any = None) -> None:
        self.name = name
        self.objClass = objClass
        self.ldapMapping = ldapMapping
        self.deleteObjClass = deleteObjClass
        self.syntax = syntax
        self.hook = hook

    def __repr__(self):
        hook = None
        if self.hook:
            hook = self.hook.type
        return " univention.admin.extended_attribute: { name: '%s', oc: '%s', attr: '%s', delOC: '%s', syntax: '%s', hook: '%s' }" % (self.name, self.objClass, self.ldapMapping, self.deleteObjClass, self.syntax, hook)


class policiesGroup:

    def __init__(self, id: Any, short_description: str | None = None, long_description: str = '', members: Any = []) -> None:
        self.id = id
        if short_description is None:
            self.short_description = id
        else:
            self.short_description = short_description
        self.long_description = long_description
        self.members = members


def _ldap_cache(ttl=10, cache_none=True):
    def _decorator(func):
        func._cache = {}
        func._last_called = None

        def _decorated(lo, *args):
            cache = func._cache
            key = (id(lo), *list(args))
            now = time.time()

            if func._last_called and (now - func._last_called) > ttl:
                for cache_key, cache_val in list(cache.items()):
                    if cache_val['expire'] < now:
                        cache.pop(cache_key, True)
            func._last_called = now

            if key not in cache or cache[key]['expire'] < now:
                value = {'value': func(lo, *args), 'expire': time.time() + ttl}
                if value['value'] is None and not cache_none:
                    return
                cache[key] = value
            return cache[key]['value']

        def cache_clear():
            func._cache = {}

        _decorated.cache_clear = cache_clear

        return _decorated

    return _decorator


univention.admin = sys.modules[__name__]
from univention.admin import hook, mapping, modules, objects, syntax  # noqa: E402


syntax.import_syntax_files()
hook.import_hook_files()

import univention.admin.handlers  # noqa: E402


if __name__ == '__main__':
    prop = property('_replace')
    for pattern in ('<firstname>', '<firstname> <lastname>', '<firstname:upper>', '<:trim,upper><firstname> <lastname>     ', '<:lower><firstname> <lastname>', '<:umlauts><firstname> <lastname>'):
        print("pattern: '%s'" % pattern)
        print(" -> '%s'" % prop._replace(pattern, {'firstname': 'Andreas', 'lastname': 'Büsching'}))
