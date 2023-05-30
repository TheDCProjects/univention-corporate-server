# SPDX-FileCopyrightText: 2014-2023 Univention GmbH
# SPDX-License-Identifier: AGPL-3.0-only
#
# Like what you see? Join us!
# https://www.univention.com/about-us/careers/vacancies/

from typing import IO, Any, Tuple  # noqa: F401

from . import File


class Raw(File):
    """represents a "RAW" disk image"""

    def __init__(self, inputfile):
        # type: (IO[bytes]) -> None
        File.__init__(self)
        self._inputfile = inputfile
        self._path = inputfile.name

    @File.hashed
    def hash(self):
        # type: () -> Tuple[Any, ...]
        return (Raw, self._inputfile)

    def _create(self, path):
        # type: (str) -> None
        pass
