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

from cerbero.config import Config, Platform, DistroVersion
from cerbero.bootstrap import BootstraperBase
from cerbero.build.oven import Oven
from cerbero.build.cookbook import CookBook


class BuildTools (BootstraperBase):

    BUILD_TOOLS = ['automake', 'autoconf', 'm4', 'libtool', 'pkg-config',
                   'orc-tool', 'gettext-m4', 'gettext-tools', 'nuget']
    PLAT_BUILD_TOOLS = {
        Platform.DARWIN: ['intltool', 'yasm', 'cmake'],
        Platform.WINDOWS: ['intltool', 'yasm'],
        Platform.LINUX: ['intltool-m4'],
    }

    def __init__(self, config, use_binaries=False, upload_binaries=False,
            build_missing=False):
        BootstraperBase.__init__(self, config)
        self.use_binaries = use_binaries
        self.upload_binaries = upload_binaries
        self.build_missing = build_missing
        if self.config.platform == Platform.WINDOWS:
            self.BUILD_TOOLS.remove('m4')
            self.BUILD_TOOLS.append('gperf')
        if self.config.platform == Platform.DARWIN:
            self.BUILD_TOOLS.append('gperf')
            if self.config.distro_version in [DistroVersion.OS_X_MOUNTAIN_LION,
                                              DistroVersion.OS_X_LION]:
                self.BUILD_TOOLS.insert(0, 'tar')
                self.BUILD_TOOLS.insert(0, 'xz')
        if self.config.platform == Platform.LINUX:
            if self.config.distro_version == DistroVersion.UBUNTU_LUCID or \
                self.config.distro_version == DistroVersion.UBUNTU_PRECISE or \
                self.config.distro_version == DistroVersion.DEBIAN_SQUEEZE:
                # x264 requires yasm >= 1.0
                self.BUILD_TOOLS.append('yasm')
            if self.config.distro_version in [DistroVersion.REDHAT_6]:
                self.BUILD_TOOLS.append('cmake')
        if self.config.target_platform == Platform.IOS:
            self.BUILD_TOOLS.append('gas-preprocessor')
        if self.config.distro_version in [DistroVersion.UBUNTU_LUCID,
                                          DistroVersion.UBUNTU_NATTY]:
            self.BUILD_TOOLS.append('glib-tools')
        if self.config.platform != Platform.LINUX and\
                not self.config.prefix_is_executable():
            # For glib-mkenums and glib-genmarshal
            self.BUILD_TOOLS.append('glib-tools')
        if self.config.variants.doc:
            self.BUILD_TOOLS.append('gtk-doc')
        self.BUILD_TOOLS += self.config.extra_build_tools

    def start(self):
        # Use a common prefix for the build tools for all the configurations
        # so that it can be reused
        config = Config()
        os.environ.clear()
        os.environ.update(self.config._pre_environ)
        config.prefix = self.config.build_tools_prefix
        config.load()
        config.build_tools_prefix = self.config.build_tools_prefix
        config.sources = self.config.build_tools_sources
        config.build_tools_sources = self.config.build_tools_sources
        config.cache_file = self.config.build_tools_cache
        config.build_tools_cache = self.config.build_tools_cache
        config.external_recipes = self.config.external_recipes
        config.home_dir = self.config.home_dir
        config.local_sources = self.config.local_sources
        # We use a different repo to prevent clashes between the same recipe
        # compiled with different prefixes
        config.binary_repo = self.config.binary_repo + '/build-tools'
        config.binary_repo_username = self.config.binary_repo_username
        config.binary_repo_password = self.config.binary_repo_password

        if not os.path.exists(config.prefix):
            os.makedirs(config.prefix)
        if not os.path.exists(config.sources):
            os.makedirs(config.sources)

        config.do_setup_env()
        cookbook = CookBook(config)
        recipes = self.BUILD_TOOLS
        recipes += self.PLAT_BUILD_TOOLS.get(self.config.platform, [])
        oven = Oven(cookbook)
        ordered_recipes = cookbook.list_recipes_deps(recipes)
        oven.start_cooking(ordered_recipes, self.use_binaries,
                self.upload_binaries, self.build_missing)
        self.config.do_setup_env()
