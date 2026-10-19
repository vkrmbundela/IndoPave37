# Security policy

IndoPave-37 is a static site. The solver runs in the visitor's browser
(Pyodide in a Web Worker); there is no server, database, login or
upload endpoint behind https://vkrmbundela.github.io/IndoPave37/. Project
files and settings stay in the browser's local storage and are never sent
anywhere.

## Reporting a vulnerability

Please report security problems privately through GitHub:
**Security → Report a vulnerability** on this repository. Do not open a
public issue for them.

Include what you found, the steps to reproduce it and the browser you used.

## What is in place

- A Content-Security-Policy on the built page: scripts and workers only from
  the site itself, data requests (fetch) only to the site itself, fonts and
  their stylesheet from Google Fonts, no plugins, and no foreign form targets
  or base URLs. The solver worker loads the Pyodide runtime from jsDelivr at a
  pinned version (0.27.4).
- The deploy installs exactly the versions pinned in `package-lock.json`
  (`npm ci`); the dependencies are checked with `npm audit`.
- The deploy workflow runs only on pushes to `main` and has read-only access
  to the repository contents.

## Out of scope

- The optional FastAPI backend (`mep_opt/web/main.py`). It binds to
  `127.0.0.1` for local development and is not deployed.
- Engineering results. A wrong number is a bug, not a vulnerability; please
  open a normal issue with the inputs that produce it.
