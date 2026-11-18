# Test-only: forces the three System IQ failure statuses. setup.py runs this while
# pip builds iqmismatchtest, after pip has installed the packages in requirements.txt.
#
#   MISSING     uninstalls IQ_MISSING_PKG (default: tabulate)
#   MISMATCH    reinstalls IQ_MISMATCH_PKG at IQ_MISMATCH_VERSION (default: the newest
#               version pip can install that is not the pinned one). Without
#               IQ_MISMATCH_PKG, picks the first package pinned in requirements.txt that
#               is installed at its pinned version and has another version on the index.
#   UNEXPECTED  installs IQ_UNEXPECTED_PKG (default: iqunexpectedtest), a stub that
#               no requirements.txt or base image lists
#
# requirements.txt is read from IQ_REQUIREMENTS (default: /requirements.txt). The
# Python that is changed is IQ_PYTHON (default: the Python running pip). A step that
# cannot do its job only logs why: the install must still succeed so the build reaches IQ.
#
# pip hides build output unless it runs with -v, so every line also goes to IQ_LOG
# (default: /tmp/iqmismatchtest.log).

import json
import os
import re
import subprocess
import sys

REQUIREMENTS = os.environ.get("IQ_REQUIREMENTS") or "/requirements.txt"
LOG = os.environ.get("IQ_LOG") or "/tmp/iqmismatchtest.log"
PYTHON = os.environ.get("IQ_PYTHON") or sys.executable
# Never picked as the MISMATCH target: changing them can break the build itself.
SKIP = {"pip", "setuptools", "wheel", "iqmismatchtest"}


def say(*parts):
    line = "iqmismatchtest: " + "".join(str(p) for p in parts)
    print(line, file=sys.stderr, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def setting(name, default=None):
    value = os.environ.get(name, "").strip()
    return value or default


def normalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def target_env():
    # pip builds this package in an isolated environment: PYTHONPATH points at the
    # build-only site dir and hides the real site-packages. Drop that so the commands
    # below see and change the environment that IQ scans.
    env = dict(os.environ)
    for key in ("PYTHONPATH", "PYTHONNOUSERSITE", "PIP_BUILD_TRACKER", "PIP_REQ_TRACKER"):
        env.pop(key, None)
    return env


def run_python(*args):
    return subprocess.run([PYTHON, *args], env=target_env(), capture_output=True, text=True)


def pip(*args):
    result = run_python("-m", "pip", *args, "--no-input", "--disable-pip-version-check")
    return result.returncode == 0, (result.stdout + result.stderr).strip()


INSPECT = r"""
import importlib.metadata as md, json, os, sysconfig
dists = {}
for d in md.distributions():
    name = d.metadata["Name"]
    if name and name not in dists:
        dists[name] = {"version": d.version}
print(json.dumps({"dists": dists, "purelib": sysconfig.get_paths()["purelib"]}))
"""


def inspect_target():
    result = run_python("-c", INSPECT)
    if result.returncode != 0:
        say("cannot inspect ", PYTHON, ": ", result.stderr.strip())
        return {}, None
    data = json.loads(result.stdout)
    installed = {normalize(k): v for k, v in data["dists"].items()}
    return installed, data["purelib"]


def pinned_versions():
    if not os.path.isfile(REQUIREMENTS):
        say("no requirements file at ", REQUIREMENTS, ", set IQ_REQUIREMENTS")
        return {}
    pins = {}
    with open(REQUIREMENTS, encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].split(";", 1)[0].strip()
            match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*==\s*([^\s,]+)$", line)
            if match:
                pins[normalize(match.group(1))] = match.group(3)
    return pins


def installed_version(pkg):
    installed, _ = inspect_target()
    entry = installed.get(normalize(pkg))
    return entry["version"] if entry else None


def reinstall_other_version(pkg, current, version):
    spec = f"{pkg}=={version}" if version else f"{pkg}!={current}"
    ok, output = pip("install", "--no-deps", spec)
    after = installed_version(pkg)
    if ok and after and after != current:
        return after
    say("MISMATCH: pip install --no-deps ", spec, " did not change ", pkg, ": ",
        output.splitlines()[-1] if output else "no output")
    return None


def force_mismatch(pkg, version, missing_pkg, installed):
    pins = pinned_versions()
    if pkg:
        candidates = [normalize(pkg)]
    else:
        candidates = sorted(
            name for name, pin in pins.items()
            if name not in SKIP and name != normalize(missing_pkg)
            and installed.get(name, {}).get("version") == pin
        )
        if not candidates:
            return say("MISMATCH: no package pinned in ", REQUIREMENTS,
                       " is installed at its pinned version, set IQ_MISMATCH_PKG")
    for name in candidates:
        if name == normalize(missing_pkg):
            return say("MISMATCH: ", name, " is the MISSING target, pick a different IQ_MISMATCH_PKG")
        current = installed.get(name, {}).get("version")
        if not current:
            say("MISMATCH: ", name, " is not installed, nothing to change")
            continue
        changed = reinstall_other_version(name, current, version)
        if changed:
            return say("MISMATCH: changed ", name, " from ", current, " to ", changed)
    say("MISMATCH: no candidate could be reinstalled at another version, set IQ_MISMATCH_PKG / IQ_MISMATCH_VERSION")


def force_missing(pkg, installed):
    if normalize(pkg) not in installed:
        return say("MISSING: ", pkg, " is not installed, nothing to remove")
    ok, output = pip("uninstall", "-y", pkg)
    if ok and installed_version(pkg) is None:
        return say("MISSING: removed ", pkg)
    say("MISSING: could not remove ", pkg, ": ", output.splitlines()[-1] if output else "no output")


def force_unexpected(pkg, purelib):
    # A bare .dist-info is all importlib.metadata, pip list and pip freeze need to
    # report a package. No network, and pip uninstall can remove it via RECORD.
    if not purelib:
        return say("UNEXPECTED: cannot find site-packages of ", PYTHON)
    folder = re.sub(r"[-_.]+", "_", pkg) + "-0.0.1.dist-info"
    path = os.path.join(purelib, folder)
    files = {
        "METADATA": f"Metadata-Version: 2.1\nName: {pkg}\nVersion: 0.0.1\n"
                    "Summary: Throwaway package installed by iqmismatchtest so System IQ reports UNEXPECTED\n",
        "INSTALLER": "iqmismatchtest\n",
    }
    try:
        os.makedirs(path, exist_ok=True)
        for name, text in files.items():
            with open(os.path.join(path, name), "w", encoding="utf-8") as f:
                f.write(text)
        record = [f"{folder}/{name},," for name in files] + [f"{folder}/RECORD,,"]
        with open(os.path.join(path, "RECORD"), "w", encoding="utf-8") as f:
            f.write("\n".join(record) + "\n")
    except OSError as e:
        return say("UNEXPECTED: could not install ", pkg, " into ", purelib, ": ", e)
    if installed_version(pkg) == "0.0.1":
        return say("UNEXPECTED: installed ", pkg, " 0.0.1 into ", purelib)
    say("UNEXPECTED: wrote ", path, " but ", PYTHON, " does not list ", pkg)


def main():
    say("changing ", PYTHON, ", requirements from ", REQUIREMENTS)
    missing_pkg = setting("IQ_MISSING_PKG", "tabulate")
    installed, purelib = inspect_target()
    force_mismatch(setting("IQ_MISMATCH_PKG"), setting("IQ_MISMATCH_VERSION"), missing_pkg, installed)
    installed, purelib = inspect_target()
    force_missing(missing_pkg, installed)
    force_unexpected(setting("IQ_UNEXPECTED_PKG", "iqunexpectedtest"), purelib)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # the install must still succeed
        say("unexpected error, skipping the rest: ", type(e).__name__, ": ", e)
    sys.exit(0)
