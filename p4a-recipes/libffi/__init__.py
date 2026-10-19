"""Local ``libffi`` recipe for python-for-android.

Why this recipe exists
----------------------
python-for-android's ``python3`` recipe declares ``libffi`` as a *hard*
dependency (it provides the ``_ctypes`` module), so every Kivy build compiles
it.  Upstream's libffi recipe builds from the **GitHub source archive**, which
ships no ``configure`` script, so it has to bootstrap autotools first::

    ./autogen.sh
    autoreconf -vif

On current Ubuntu runners that step is fragile.  The classic failure is::

    configure.ac:...: error: possibly undefined macro: LT_SYS_SYMBOL_USCORE

because ``LT_SYS_SYMBOL_USCORE`` lives in the system autotools m4 files
(``libltdl-dev``).  When the macro is missing, ``autoreconf`` rewrites
``configure`` without it and the build dies later with ``set_writable`` /
``unknown symbol`` errors.

What this recipe does differently
---------------------------------
1. It downloads the official **release tarball** instead of the source
   archive.  A release tarball is a ``make dist`` artefact: it already ships a
   generated ``configure``, ``Makefile.in`` and ``aclocal.m4``, so no
   autotools bootstrapping is required at all.  The ``autogen.sh``/
   ``autoreconf`` path is kept only as a fallback for source snapshots.

2. It reproduces upstream's ``remove-version-info.patch`` **without** re-running
   ``automake``.  That patch changes ``libffi_la_LDFLAGS`` to add
   ``-avoid-version``, which makes libtool emit a plain ``libffi.so`` whose
   ``DT_SONAME`` is also ``libffi.so``.  That matters: p4a bundles
   ``.libs/libffi.so`` into ``lib/<abi>/``, and ``_ctypes.so`` records whatever
   soname libffi had when it was linked.  Because the patch normally edits
   ``Makefile.am`` (and therefore needs ``automake``), we instead pass the same
   flags as a **make command-line override**, which GNU make applies on top of
   the ``Makefile`` regardless of how it was generated.  ``$(LTLDFLAGS)`` and
   ``$(AM_LTLDFLAGS)`` are still expanded by make, so nothing else is lost.

The recipe deliberately sets no ``patches``: the base :class:`Recipe` is
subclassed directly, so upstream's ``Makefile.am`` patch is neither fetched nor
applied (it would be a no-op without ``automake``).
"""

from multiprocessing import cpu_count
from os.path import exists, join

import sh
from pythonforandroid.logger import shprint
from pythonforandroid.recipe import Recipe
from pythonforandroid.util import current_directory


class LibffiRecipe(Recipe):
    name = "libffi"
    version = "3.4.4"

    #: ``{version}`` is substituted by p4a.  The release tarball (as opposed to
    #: ``/archive/{version}.tar.gz``) is the key detail: it ships ./configure.
    url = (
        "https://github.com/libffi/libffi/releases/download/"
        "v{version}/libffi-{version}.tar.gz"
    )

    built_libraries = {"libffi.so": ".libs"}

    #: Equivalent to upstream's ``remove-version-info.patch``, applied at make
    #: time so that ``automake`` never has to run.
    ldflags_override = (
        "libffi_la_LDFLAGS=-no-undefined -avoid-version"
        " $(LTLDFLAGS) $(AM_LTLDFLAGS)"
    )

    def build_arch(self, arch):
        env = self.get_recipe_env(arch)

        # Newer NDK clang (r28c / clang 19+) promotes
        # -Wimplicit-function-declaration to a hard error by default.  libffi
        # 3.4.4's src/tramp.c calls open_temp_exec_file() -- a non-static
        # helper defined in src/closures.c -- without a visible prototype, so
        # that single call stops the compile on modern toolchains even though
        # the symbol resolves fine at link time.  Downgrade just that one
        # diagnostic back to a warning so the stock release tarball builds
        # unmodified (consistent with the ldflags_override approach below).
        cflags = env.get("CFLAGS", "")
        env["CFLAGS"] = (
            cflags + " -Wno-error=implicit-function-declaration"
        ).strip()

        build_dir = self.get_build_dir(arch.arch)

        with current_directory(build_dir):
            if not exists("configure"):
                # Only reachable for source snapshots (no ./configure shipped).
                shprint(sh.Command("./autogen.sh"), _env=env)
                shprint(sh.Command("autoreconf"), "-vif", _env=env)

            shprint(
                sh.Command("./configure"),
                "--host=" + arch.command_prefix,
                "--prefix=" + build_dir,
                "--disable-builddir",
                "--enable-shared",
                _env=env,
            )

            shprint(
                sh.make,
                "-j",
                str(cpu_count()),
                "libffi.la",
                self.ldflags_override,
                _env=env,
            )

    def get_include_dirs(self, arch):
        return [join(self.get_build_dir(arch), "include")]


recipe = LibffiRecipe()
