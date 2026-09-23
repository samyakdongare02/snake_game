"""Local libffi recipe: official release tarball ships ./configure.

Skips ./autogen.sh so Ubuntu 24.04 CI does not die on
LT_SYS_SYMBOL_USCORE / autoconf failures.
"""

from pythonforandroid.logger import shprint
from pythonforandroid.recipe import Recipe
from pythonforandroid.util import current_directory

import sh


class LibffiRecipe(Recipe):
    version = "3.4.4"
    url = (
        "https://github.com/libffi/libffi/releases/download/"
        "v{version}/libffi-{version}.tar.gz"
    )
    built_libraries = {"libffi.so*": ".libs"}

    def build_arch(self, arch, **kwargs):
        env = self.get_build_env(arch)
        build_dir = self.get_build_dir(arch.arch)

        with current_directory(build_dir):
            shprint(
                sh.Command("./configure"),
                "--host={}".format(arch.command_prefix),
                "--prefix={}".format(build_dir),
                "--disable-docs",
                "--disable-multi-os-directory",
                _env=env,
            )
            try:
                import multiprocessing

                jobs = str(max(1, multiprocessing.cpu_count()))
            except Exception:
                jobs = "2"
            shprint(sh.make, "-j" + jobs, _env=env)
