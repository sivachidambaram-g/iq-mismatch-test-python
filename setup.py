# Test-only: pip runs this while it builds iqmismatchtest. The build_py step runs
# tools/iq_test.py once, which makes System IQ report one package each as MISSING,
# MISMATCH and UNEXPECTED. See tools/iq_test.py for the IQ_* overrides.
import os
import subprocess
import sys

from setuptools import setup
from setuptools.command.build_py import build_py

HERE = os.path.dirname(os.path.abspath(__file__))


class build_py_with_iq_test(build_py):
    def run(self):
        try:
            subprocess.run([sys.executable, os.path.join(HERE, "tools", "iq_test.py")], check=False)
        except Exception as e:  # the install must still succeed
            print(f"iqmismatchtest: could not run tools/iq_test.py: {e}", file=sys.stderr)
        super().run()


setup(cmdclass={"build_py": build_py_with_iq_test})
