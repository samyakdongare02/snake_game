"""Local libffi recipe: official release tarball ships ./configure.

Avoids ./autogen.sh (LT_SYS_SYMBOL_USCORE / autoconf failures on Ubuntu 24.04).
p4a requires a module-level `recipe` instance.
"""

from os.path import exists, join
from multiprocessing import cpu_count

from pythonforandroid.logger import shprint
from pythonforandroid.recipe import Recipe
from pythonforandroid.util import current_directory

import sh


class LibffiRecipe(Recipe):
    name = "libffi"
    version = "3.4.4"
    url = (
        "https://github.com/libffi/libffi/releases/download/"
        "v{version}/libffi-{version}.tar.gz"
    )
    built_libraries = {"libffi.so": ".libs"}

    def build_arch(self, arch):
        env = self.get_recipe_env(arch)
        build_dir = self.get_build_dir(arch.arch)
        with current_directory(build_dir):
            # Release tarball includes a pre-generated configure script.
            # Never run autogen.sh / autoreconf here.
            if not exists("configure"):
                raise Exception(
                    "libffi release tarball missing ./configure; "
                    "cannot build without autoconf on this runner"
                )
            shprint(
                sh.Command("./configure"),
                "--host=" + arch.command_prefix,
                "--prefix=" + build_dir,
                "--disable-builddir",
                "--enable-shared",
                _env=env,
            )
            shprint(sh.make, "-j", str(cpu_count()), "libffi.la", _env=env)

    def get_include_dirs(self, arch):
        return [join(self.get_build_dir(arch.arch), "include")]


recipe = LibffiRecipe()
