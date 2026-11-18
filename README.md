# iq-mismatch-test-python

Test-only Python package for DSW QA. One install forces a **MISSING**, a **MISMATCH** and an
**UNEXPECTED** package in **System IQ** on a non-PDV Python exec config, so a single build shows
all three in the test results. Python counterpart of `iq-mismatch-test-r`.

| Status | What the build step does | Default target | Override |
| --- | --- | --- | --- |
| `MISSING` | `pip uninstall -y` | `tabulate` | `IQ_MISSING_PKG` |
| `MISMATCH` | `pip install --no-deps` at another version | first package pinned (`==`) in `/requirements.txt` that is installed at its pin and has another version on the index | `IQ_MISMATCH_PKG`, `IQ_MISMATCH_VERSION` (default: newest installable version that is not the pinned one) |
| `UNEXPECTED` | writes a stub `.dist-info` that no requirements file lists | `iqunexpectedtest` | `IQ_UNEXPECTED_PKG` |

## Use

1. In the exec config's `requirements.txt`, pin `tabulate` at `0.9.0` **and** at least one more
   package that has other versions on PyPI (for example `toolz==0.12.1`).
2. Add `sivachidambaram-g/iq-mismatch-test-python` as a GitHub package on the exec config
   (pip installs it as `git+https://github.com/sivachidambaram-g/iq-mismatch-test-python`).
3. Build. System IQ reports, for example:
   - `tabulate` (expected 0.9.0, installed none) as `MISSING`
   - `toolz` (expected 0.12.1, installed 1.2.0) as `MISMATCH`
   - `iqunexpectedtest` (installed 0.0.1) as `UNEXPECTED`

   The build shows **Tests Failed** because of the MISSING and MISMATCH packages. UNEXPECTED
   alone only fails PDV builds. `iqmismatchtest` also shows as `UNEXPECTED`, because it is not
   in `requirements.txt`.

## How it works

pip has to build a GitHub package from source, so it runs `setup.py`. The custom `build_py`
step runs `tools/iq_test.py`, which changes the environment pip is installing into. pip builds
in an isolated environment, so the script drops `PYTHONPATH` / `PYTHONNOUSERSITE` before
it calls pip. That way it sees and changes the real site-packages.

## Notes

- The package must be installed **after** the packages it changes. That holds when
  `requirements.txt` is installed before the GitHub package. Packages installed after it
  (for example from the custom package list) are not seen.
- `requirements.txt` is read from `/requirements.txt`. Set `IQ_REQUIREMENTS=<path>` if it is
  elsewhere. Only `name==version` pins are used to pick the MISMATCH target.
- The Python that is changed is the one running pip. Set `IQ_PYTHON=<path>` to target another one.
- Pick packages that are **not** in the base-image whitelist (`py-base_packages.txt`), or IQ
  reports `WHITELISTED_MISMATCH` instead of `MISMATCH`.
- pip hides build output unless it runs with `-v`. Every step therefore also logs an
  `iqmismatchtest:` line to `/tmp/iqmismatchtest.log` (`IQ_LOG` to change it). A step that
  cannot run (target not installed, no other version, no network) logs why, and the install
  still succeeds.
- pip only reuses a cached wheel for a pinned commit (`@<sha>`). In that case the build step
  doesn't run again on the same machine, but a fresh Docker build is not affected.
