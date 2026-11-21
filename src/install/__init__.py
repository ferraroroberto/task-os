"""The per-PC install: ``install.bat`` → ``python -m src.install``.

Every step keeps what the PC already has. A config file is created from its
committed ``*.sample.json`` only when missing; an existing one only gains the
keys it lacks, after a timestamped backup, and only when adding them changes
nothing the app would run with; a machine registration that is already there
is reported ``kept``. A second run therefore reports ``unchanged`` everywhere,
and ``-WhatIf`` lists the same steps without making any of them.

    config_merge.py   ignored configs from their samples: create, add missing keys, back up
    machine.py        the per-user registrations (the folder opener, the sign-in start)
    requirements.py   requirements.txt into the running .venv, only what is missing
    checklist.py      what works on this PC and what still needs the owner
    __main__.py       the command line and the printed report
"""
