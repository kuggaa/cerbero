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
import stat
import tempfile
import shutil
import uuid
from zipfile import ZipFile

from cerbero.errors import EmptyPackageError
from cerbero.packages import PackagerBase, PackageType
from cerbero.packages.package import Package, App, AppExtensionPackage
from cerbero.utils import messages as m
from cerbero.utils import shell, to_winepath, get_wix_prefix, etree
from cerbero.tools import strip
from cerbero.packages.wix import MergeModule, VSMergeModule, MSI, WixConfig, Burn, Fragment
from cerbero.packages.wix import VSTemplatePackage
from cerbero.config import Platform


class MergeModulePackager(PackagerBase):

    def __init__(self, config, package, store):
        PackagerBase.__init__(self, config, package, store)
        self._with_wine = config.platform != Platform.WINDOWS
        self.wix_prefix = get_wix_prefix()
        # Init wix wine prefix in the case of using it.
        self.wix_wine_prefix = None

    def pack(self, output_dir, devel=False, force=False, keep_temp=False):
        PackagerBase.pack(self, output_dir, devel, force, keep_temp)

        paths = []

        # create runtime package
        p = self.create_merge_module(output_dir, PackageType.RUNTIME, force,
                                     self.package.version, keep_temp)
        paths.append(p)

        if devel:
            p = self.create_merge_module(output_dir, PackageType.DEVEL, force,
                                         self.package.version, keep_temp)
            paths.append(p)

        return paths

    def create_merge_module(self, output_dir, package_type, force, version,
                            keep_temp):
        self.package.set_mode(package_type)
        files_list = self.files_list(package_type, force)
        if isinstance(self.package, VSTemplatePackage):
            mergemodule = VSMergeModule(self.config, files_list, self.package)
        else:
            mergemodule = MergeModule(self.config, files_list, self.package)
        tmpdir = None
        # For application packages that requires stripping object files, we need
        # to copy all the files to a new tree and strip them there:
        if self._is_app() and self.package.strip:
            tmpdir = tempfile.mkdtemp()
            for f in files_list:
                src = os.path.join(self.config.prefix, f)
                dst = os.path.join(tmpdir, f)
                if not os.path.exists(os.path.dirname(dst)):
                    os.makedirs(os.path.dirname(dst))
                shutil.copy(src, dst)
            s = strip.Strip(self.config, self.package.strip_excludes)
            for p in self.package.strip_dirs:
                s.strip_dir(os.path.join(tmpdir, p))

        package_name = self._package_name(version)

        if self.package.wix_use_fragment:
          mergemodule = Fragment(self.config, files_list, self.package)
          sources = [os.path.join(output_dir, "%s-fragment.wxs" % package_name)]
        else:
          mergemodule = MergeModule(self.config, files_list, self.package)
          sources = [os.path.join(output_dir, "%s.wxs" % package_name)]
        if tmpdir:
            mergemodule.prefix = tmpdir
        elif self.wix_wine_prefix:
            mergemodule.prefix = self.wix_wine_prefix

        mergemodule.write(sources[0])
        if self.package.wix_use_fragment:
          wixobjs = [os.path.join(output_dir, "%s-fragment.wixobj" % package_name)]
        else:
          wixobjs = [os.path.join(output_dir, "%s.wixobj" % package_name)]

        for x in ['utils']:
            wixobjs.append(os.path.join(output_dir, "%s.wixobj" % x))
            sources.append(os.path.join(os.path.abspath(self.config.data_dir),
                           'wix/%s.wxs' % x))

        if self._with_wine:
            final_wixobjs = [to_winepath(x) for x in wixobjs]
            final_sources = [to_winepath(x) for x in sources]
        else:
            final_wixobjs = wixobjs
            final_sources = sources

        candle = Candle(self.wix_prefix, self._with_wine)
        candle.compile(' '.join(final_sources), output_dir)
        if self.package.wix_use_fragment:
          path = wixobjs[0]
        else:
          light = Light(self.wix_prefix, self._with_wine)
          path = light.compile(final_wixobjs, package_name, output_dir, True)
        # Clean up
        if not keep_temp:
            os.remove(sources[0])
            if not self.package.wix_use_fragment:
              for f in wixobjs:
                  os.remove(f)
                  try:
                      os.remove(f.replace('.wixobj', '.wixpdb'))
                  except:
                      pass
        if tmpdir:
            shutil.rmtree(tmpdir)

        return path

    def _is_app(self):
        return isinstance(self.package, App) or \
            isinstance(self.package, AppExtensionPackage)

    def _package_name(self, version):
        return "%s-%s-%s" % (self.package.name, self.config.target_arch,
                             version)


class MSIPackager(PackagerBase):

    UI_EXT = '-ext WixUIExtension'
    UTIL_EXT = '-ext WixUtilExtension'

    def __init__(self, config, package, store):
        PackagerBase.__init__(self, config, package, store)
        self._with_wine = config.platform != Platform.WINDOWS
        self.wix_prefix = get_wix_prefix()
        # We use this trick to workaround the wix path limitation.
        # wix_wine_prefix is a symbolic link to the regular cerbero prefix
        # and should not be a folder.
        if self._with_wine:
          self.wix_wine_prefix = self.get_wix_wine_prefix()
          os.symlink(config.prefix, self.wix_wine_prefix)
        else:
          self.wix_wine_prefix = None

    def get_unique_wix_wine_prefix(self):
        return '/tmp/wix_%s' % str(uuid.uuid4())[:8]

    def get_wix_wine_prefix(self):
        wix_wine_prefix = self.get_unique_wix_wine_prefix()
        while (os.path.exists(wix_wine_prefix)):
          wix_wine_prefix = self.get_unique_wix_wine_prefix()
        return wix_wine_prefix

    def pack(self, output_dir, devel=False, force=False, keep_temp=False):
        self.output_dir = os.path.realpath(output_dir)
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
        self.force = force
        self.keep_temp = keep_temp

        paths = []
        self.merge_modules = {}

        # create runtime package
        p = self._create_msi_installer(PackageType.RUNTIME)
        paths.append(p)

        # create devel package
        if devel and not self._is_app():
            p = self._create_msi_installer(PackageType.DEVEL)
            paths.append(p)

        # create zip with merge modules
        if not self._is_app() and not self.package.wix_use_fragment:
            self.package.set_mode(PackageType.RUNTIME)
            zipf = ZipFile(os.path.join(self.output_dir, '%s-merge-modules.zip' %
                                        self._package_name()), 'w')
            for p in self.merge_modules[PackageType.RUNTIME]:
                zipf.write(p)
            zipf.close()

        if not keep_temp:
            for msms in self.merge_modules.values():
                for p in msms:
                    if os.path.exists(p):
                      os.remove(p)

        if self.wix_wine_prefix:
          os.remove(self.wix_wine_prefix)

        return paths

    def _is_app(self):
        return isinstance(self.package, App) or \
            isinstance(self.package, AppExtensionPackage)

    def _package_name(self):
        return "%s-%s-%s" % (self.package.name, self.config.target_arch,
                             self.package.version)

    def _create_msi_installer(self, package_type):
        self.package.set_mode(package_type)
        if self._is_app():
            self.packagedeps = [self.package]
        else:
            self.packagedeps = self.store.get_package_deps(self.package, True)
        self._create_merge_modules(package_type, self.package.wix_use_fragment)
        config_path = self._create_config()
        return self._create_msi(config_path)

    def _create_merge_modules(self, package_type, wix_use_fragment):
        packagedeps = {}
        for package in self.packagedeps:
            package.set_mode(package_type)
            package.wix_use_fragment = wix_use_fragment
            m.action("Creating Merge Module for %s" % package)
            packager = MergeModulePackager(self.config, package, self.store)
            if self.wix_wine_prefix:
               packager.wix_wine_prefix = self.wix_wine_prefix
            try:
                path = packager.create_merge_module(self.output_dir,
                           package_type, self.force, self.package.version,
                           self.keep_temp)
                packagedeps[package] = path
            except EmptyPackageError:
                m.warning("Package %s is empty" % package)
        self.packagedeps = packagedeps
        self.merge_modules[package_type] = packagedeps.values()

    def _create_config(self):
        config = WixConfig(self.config, self.package)
        config_path = config.write(self.output_dir)
        return config_path

    def _create_msi(self, config_path):
        sources = [os.path.join(self.output_dir, "%s.wxs" %
                   self._package_name())]
        msi = MSI(self.config, self.package, self.packagedeps, config_path,
                  self.store)

        if self.wix_wine_prefix:
          msi.prefix = self.wix_wine_prefix

        msi.write(sources[0])

        wixobjs = [os.path.join(self.output_dir, "%s.wixobj" %
                                self._package_name())]

        wixobjs.extend(self.merge_modules[self.package.package_mode])

        for x in ['utils']:
            wixobjs.append(os.path.join(self.output_dir, "%s.wixobj" % x))
            sources.append(os.path.join(os.path.abspath(self.config.data_dir),
                           'wix/%s.wxs' % x))

        if self._with_wine:
            final_wixobjs = [to_winepath(x) for x in wixobjs]
            final_sources = [to_winepath(x) for x in sources]
        else:
            final_wixobjs = wixobjs
            final_sources = sources

        candle = Candle(self.wix_prefix, self._with_wine,
                      "%s %s" % (self.UI_EXT, self.UTIL_EXT))
        candle.compile(' '.join(final_sources), self.output_dir)
        light = Light(self.wix_prefix, self._with_wine,
                      "%s %s" % (self.UI_EXT, self.UTIL_EXT))
        path = light.compile(final_wixobjs, self._package_name(), self.output_dir)

        # Clean up
        if not self.keep_temp:
            os.remove(sources[0])
            for f in wixobjs:
                os.remove(f)
                try:
                    os.remove(f.replace('.wixobj', '.wixpdb'))
                except:
                    pass
            os.remove(config_path)

        return path

class BurnPackager(MSIPackager):
    """Packager for Burn bundles"""
    BURN_EXT = '-ext WixBalExtension'
    UTIL_EXT = '-ext WixUtilExtension'

    def __init__(self, config, package, store):
        super(BurnPackager, self).__init__(config, package, store)

    def pack(self, output_dir, devel=False, force=False, keep_temp=False):
        # Create Msi package
        paths = super(BurnPackager, self).pack(output_dir, devel, force, keep_temp)
        self.package.sign(paths)
        # Create Burn package from the Msi package
        config_path = self._create_config()
        bundled_path = self._create_bundle(config_path, paths)
        bundled_path = self._sign_bundle(bundled_path)
        return [bundled_path] # post_package will sign the whole bundled path

    def _create_config(self):
        config = WixConfig(self.config, self.package)
        config_path = config.write(self.output_dir)
        return config_path

    def _create_bundle(self, config_path, paths):
        sources = [os.path.join(self.output_dir, "burn_%s.wxs" %
                   self._package_name())]
        burn = Burn(self.config, self.package, self.packagedeps, config_path,
                  self.store, paths)
        burn.write(sources[0])

        wixobjs = ["%s.wixobj" % p.rsplit('.',1)[0] for p in sources]
        for x in ['utils']:
            wixobjs.append(os.path.join(self.output_dir, "%s.wixobj" % x))
            sources.append(os.path.join(os.path.abspath(self.config.data_dir),
                           'wix/%s.wxs' % x))

        if self._with_wine:
            final_wixobjs = [to_winepath(x) for x in wixobjs]
            final_sources = [to_winepath(x) for x in sources]
        else:
            final_wixobjs = wixobjs
            final_sources = sources

        candle = Candle(self.wix_prefix, self._with_wine,
                        "%s %s" % (self.BURN_EXT, self.UTIL_EXT))
        candle.compile(' '.join(final_sources), self.output_dir)
        light = Light(self.wix_prefix, self._with_wine,
                      "%s %s" % (self.BURN_EXT, self.UTIL_EXT))
        path = light.compile(final_wixobjs, self._package_name(), self.output_dir, extension='exe')

        # Clean up
        if not self.keep_temp:
            os.remove(sources[0])
            for f in wixobjs:
                os.remove(f)
                try:
                    os.remove(f.replace('.wixobj', '.wixpdb'))
                except:
                    pass
            os.remove(config_path)

        return path

    def _sign_bundle(self, bundle):
        insignia = Insignia(self.wix_prefix, self._with_wine)
        engine = insignia.extract_engine(bundle, self.output_dir)
        self.package.sign([engine])
        bundled_path = insignia.attach_engine(bundle, self.output_dir, engine)

        if not self.keep_temp:
            os.remove(engine)

        return bundled_path

class Packager(object):

    def __new__(klass, config, package, store):
        if isinstance(package, Package) and not \
                isinstance(package, AppExtensionPackage):
            return MergeModulePackager(config, package, store)
        else:
            if hasattr(package, 'resources_wix_bundle') and package.resources_wix_bundle:
                return BurnPackager(config, package, store)
            return MSIPackager(config, package, store)


class Candle(object):
    ''' Compile WiX objects with candle '''

    cmd = '%(wine)s %(q)s%(prefix)s/candle.exe%(q)s %(source)s %(extra)s'

    def __init__(self, wix_prefix, with_wine, extra=''):
        self.options = {}
        self.options['prefix'] = wix_prefix
        self.options['extra'] = extra
        if with_wine:
            self.options['wine'] = 'wine'
            self.options['q'] = '"'
        else:
            self.options['wine'] = ''
            self.options['q'] = ''

    def compile(self, source, output_dir):
        self.options['source'] = source
        shell.call(self.cmd % self.options, output_dir)
        return os.path.join(output_dir, source, '.msm')


class Light(object):
    ''' Compile WiX objects with light'''

    cmd = '%(wine)s %(q)s%(prefix)s/light.exe%(q)s %(objects)s -o '\
          '%(msi)s.%(ext)s -sval %(extra)s'

    def __init__(self, wix_prefix, with_wine, extra=''):
        self.options = {}
        self.options['prefix'] = wix_prefix
        self.options['extra'] = extra
        if with_wine:
            self.options['wine'] = 'wine'
            self.options['q'] = '"'
        else:
            self.options['wine'] = ''
            self.options['q'] = ''

    def compile(self, objects, msi_file, output_dir, merge_module=False, extension=None):
        self.options['objects'] = ' '.join(objects)
        self.options['msi'] = msi_file
        if extension:
            self.options['ext'] = extension
        else:
            if merge_module:
                self.options['ext'] = 'msm'
            else:
                self.options['ext'] = 'msi'
        shell.call(self.cmd % self.options, output_dir)
        msi_file_path = os.path.join(output_dir, '%(msi)s.%(ext)s' % self.options)
        if self.options['wine'] == 'wine':
          os.chmod(msi_file_path, 0755)
        return msi_file_path

class Insignia(object):
    """
    Sign bundle with WiX insignia

    Insignia extracts the Burn engine
    to allow signing apart from the main bundle
    """

    cmd_extract = '%(wine)s %(q)s%(prefix)s/insignia.exe%(q)s -ib %(bundle)s -o %(engine)s'

    cmd_attach = '%(wine)s %(q)s%(prefix)s/insignia.exe%(q)s -ab %(engine)s %(bundle)s -o %(bundle)s'

    def __init__(self, wix_prefix, with_wine):
        self.options = {}
        self.options['prefix'] = wix_prefix
        if with_wine:
            self.options['wine'] = 'wine'
            self.options['q'] = '"'
        else:
            self.options['wine'] = ''
            self.options['q'] = ''

    def extract_engine(self, bundle, output_dir, engine='engine.exe'):
        self.options['bundle'] = bundle
        self.options['engine'] = engine
        shell.call(self.cmd_extract % self.options, output_dir)
        return os.path.join(output_dir, '%(engine)s' % self.options)

    def attach_engine(self, bundle, output_dir, engine):
        self.options['bundle'] = bundle
        self.options['engine'] = engine
        shell.call(self.cmd_attach % self.options, output_dir)
        return bundle

def register():
    from cerbero.packages.packager import register_packager
    from cerbero.config import Distro
    register_packager(Distro.WINDOWS, Packager)
