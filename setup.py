"""Builds a platform wheel around the prebuilt native library.

The Python code calls the library through ctypes, so the wheel works on every Python 3 version and is tagged
py3-none-<platform>. The platform tag comes from PDFPECKER_WHEEL_PLATFORM (CI sets it per build, e.g.
manylinux_2_28_x86_64), or from the machine when it is not set. Build the native library first; see "Building from source" in README.md.
"""
import os

from setuptools import setup
from setuptools.dist import Distribution

try:
    from setuptools.command.bdist_wheel import bdist_wheel
except ImportError:  # setuptools < 70.1
    from wheel.bdist_wheel import bdist_wheel


class PlatformWheel(bdist_wheel):
    def finalize_options(self):
        super().finalize_options()
        self.root_is_pure = False

    def get_tag(self):
        _, _, platform = super().get_tag()
        return "py3", "none", os.environ.get("PDFPECKER_WHEEL_PLATFORM") or platform


class BinaryDistribution(Distribution):
    def has_ext_modules(self):
        return True


setup(distclass=BinaryDistribution, cmdclass={"bdist_wheel": PlatformWheel})
