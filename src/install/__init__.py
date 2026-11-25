"""What task-os adds to the vendored installer (``setup.bat`` → ``src/installer.py``).

The vendored installer creates the ``.venv``, installs the requirements, creates
each missing config from its committed sample and ends with the checklist. It
tops up a settings file with every key the sample has, which this app must not
do: absence carries meaning here (no ``mirror`` block means no mirror), and the
sample's values are the author's own. So ``.fleet.toml [install]`` declares
``config/config.json`` as a registry (never rewritten by that pass) and hands the
top-up, the opener, the sign-in start and the personal checks to this package.
Every step keeps what the PC already has, and a second run is unchanged.

    config_merge.py   ignored configs from their samples: create, add the keys that change nothing, back up
    machine.py        the per-user registrations (the folder opener, the sign-in start)
    checklist.py      the personal checks, one exit code each (0 ok, 1 missing, 2 unknown)
    __main__.py       ``apply`` · ``startup`` · ``check`` — the commands ``.fleet.toml [install]`` runs
"""
