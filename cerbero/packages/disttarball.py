# cerbero - a multi-platform build system for Open Source software
# Copyright (C) 2012 Andoni Morales Alastruey <ylatuya@gmail.com>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Library General Public
# License as published by the Free Software Foundation; either
# version 2 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Library General Public License for more details.
#
# You should have received a copy of the GNU Library General Public
# License along with this library; if not, write to the
# Free Software Foundation, Inc., 59 Temple Place - Suite 330,
# Boston, MA 02111-1307, USA.

import os
import tarfile

from cerbero.utils import _
from cerbero.utils import messages as m
from cerbero.errors import UsageError


class DistTarball(object):
    ''' Creates a distribution tarball '''

    def __init__(self, package):
        self.package = package
        self.prefix = self.package.config.prefix

    def pack(self, output_dir, force=False):
        filename = "%s-%s.tar.bz2" % (self.package.name, self.package.version)
        if os.path.exists(filename):
            if force:
                os.remove(filename)
            else:
                raise UsageError("File %s already exists" % filename)

        tar = tarfile.open(filename, "w:bz2")
        for f in self.package.get_files_list():
            if not os.path.exists(os.path.join(self.prefix, f)):
                m.warning(_("File %s do not exists and won't be added to the "
                            "package") % f)
                continue
            tar.add(os.path.join(self.prefix,f), f)
        tar.close()
        return filename