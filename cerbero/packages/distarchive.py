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
import tempfile
import zipfile
import shutil

import cerbero.utils.messages as m
from cerbero.utils import _, replace_prefix, is_text_file
from cerbero.config import Platform
from cerbero.errors import UsageError, EmptyPackageError
from cerbero.packages import PackagerBase, PackageType
from cerbero.enums import ArchiveType
from cerbero.tools.osxrelocator import OSXRelocator

class DistArchive(PackagerBase):
    ''' Creates a distribution archive '''

    def __init__(self, config, package, store, archive_type):
        PackagerBase.__init__(self, config, package, store)
        self.package = package
        self.prefix = config.prefix
        self.package_prefix = ''
        if self.config.packages_prefix is not None:
            self.package_prefix = '%s-' % self.config.packages_prefix

        if archive_type == ArchiveType.TARBALL:
            self.ext = 'tar.bz2'
            self.archive_func = self._create_tarball
        elif archive_type == ArchiveType.ZIP:
            self.ext = 'zip'
            self.archive_func = self._create_zip
        else:
            raise UsageError("Unsupported archive_type %s" % archive_type)

    def pack(self, output_dir, devel=True, force=False, keep_temp=False,
             split=True, package_prefix='', force_empty=False, relocatable=False):
        try:
            dist_files = self.files_list(PackageType.RUNTIME, force)
        except EmptyPackageError:
            m.warning(_("The runtime package is empty"))
            dist_files = []

        if devel:
            try:
                devel_files = self.files_list(PackageType.DEVEL, force)
            except EmptyPackageError:
                m.warning(_("The development package is empty"))
                devel_files = []
        else:
            devel_files = []

        if not split:
            dist_files += devel_files

        if not dist_files and not devel_files:
            raise EmptyPackageError(self.package.name)

        filenames = []
        if dist_files or force_empty:
            runtime = self._create_archive(output_dir, PackageType.RUNTIME,
                                           dist_files, force, package_prefix,
                                           relocatable)
            filenames.append(runtime)

        if split and devel and (devel_files or force_empty):
            devel = self._create_archive(output_dir, PackageType.DEVEL,
                                         devel_files, force, package_prefix,
                                         relocatable)
            filenames.append(devel)
        return filenames

    def get_name(self, package_type, ext=None):
        '''
        Get the name of the package file

        @cvar package_type: the type of the package to get the name from
        @type package_type: L{cerbero.packages.PackageType}
        @cvar ext: the extension to append to the package name
        @type ext: str
        @return: name of the package
        @rtype: str
        '''
        if not ext:
            ext = self.ext

        return "%s%s-%s-%s-%s%s.%s" % (self.package_prefix, self.package.name,
                self.config.target_platform, self.config.target_arch,
                self.package.version, package_type, ext)

    def _create_tarball(self, filename, files, package_prefix, relocatable):

        tar = tarfile.open(filename, "w:bz2")

        for f in files:
            filepath = os.path.join(self.prefix, f)
            arcname = os.path.join(package_prefix, f)
            if relocatable and not os.path.islink(filepath):
                if os.path.splitext(f)[1] in ['.la', '.pc'] or ('bin' in os.path.splitext(f)[0] and is_text_file(filepath)):
                    with open(filepath, 'r') as fo:
                        content = fo.read()
                        content = replace_prefix(self.config.prefix, content, "CERBERO_PREFIX")
                        rewritten = tempfile.NamedTemporaryFile()
                        rewritten.write(content)
                        rewritten.flush()
                        rewritten.seek(0)
                        tinfo = tar.gettarinfo(arcname=arcname, fileobj=fo)
                        tinfo.size = len(content)
                        tinfo.name = os.path.join(package_prefix, f)
                        tar.addfile(tinfo, rewritten)
                        rewritten.close()
                elif os.path.splitext(f)[1] in ['.dylib'] and self.config.target_platform == Platform.DARWIN:
                    tempdir = tempfile.mkdtemp()
                    os.makedirs(os.path.join(tempdir, os.path.dirname(f)))
                    rewritten = os.path.join(tempdir, f)
                    shutil.copy(filepath, rewritten)
                    relocator = OSXRelocator(self.config.prefix, tempdir, True)
                    relocator.change_id(rewritten)
                    tar.add(rewritten, arcname)
                    shutil.rmtree(tempdir)
                else:
                    tar.add(filepath, arcname)
            else:
                tar.add(filepath, arcname)
        tar.close()

    def _create_zip(self, filename, files, package_prefix, relocatable):

        zip_file = zipfile.ZipFile(filename, "w")

        for f in files:
            filepath = os.path.join(self.prefix, f)
            arcname = os.path.join(package_prefix, f)
            if relocatable and os.path.splitext(f)[1] in ['.la', '.pc']:
                with open(filepath, 'r') as fo:
                    content = fo.read()
                    content = content.replace(self.config.prefix, "CERBERO_PREFIX")
                    zip_file.writestr(arcname, content)
            else:
                zip_file.write(filepath, arcname)
        zip_file.close()

    def _create_archive(self, output_dir, package_type, files, force,
                        package_prefix, relocatable=False):
        filename = os.path.join(output_dir, self.get_name(package_type))
        if os.path.exists(filename):
            if force:
                os.remove(filename)
            else:
                raise UsageError("File %s already exists" % filename)

        self.archive_func(filename, files, package_prefix, relocatable)

        return filename
