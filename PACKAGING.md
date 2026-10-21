# Dealer Management Windows package

Build from the project root with:

```text
pyinstaller --clean --noconfirm "Dealer Management.spec"
```

The result is `dist/Dealer Management/Dealer Management.exe`. The spec bundles
`templates/`, `static/`, Django/app resources, and PDF-export dependencies; it
does not bundle a database. On first launch, the launcher creates a fresh
database at `%LOCALAPPDATA%\Dealer Management\db.sqlite3` (or the directory
specified by `DEALER_MANAGEMENT_DATA_DIR`) by applying the existing migrations.
An existing database is never overwritten or migrated by the launcher.

User uploads are stored in `%LOCALAPPDATA%\Dealer Management\media\` (or the
same configured data directory). An existing legacy `db.sqlite3` or `media/`
next to an older EXE is copied forward only if the persistent target is absent;
no existing database or upload is replaced. The source project continues to
use its normal `db.sqlite3`, `templates/`, `static/`, and `media/` paths when
run with `python manage.py runserver`.

If startup fails, the EXE prints the error in its console and appends it to
`%LOCALAPPDATA%\Dealer Management\logs\launcher.log`. If that data directory
cannot be written, it falls back to `%TEMP%\Dealer Management\logs\launcher.log`.
The launcher checks that the selected data directory and SQLite database are
writable before it starts the server; it never repairs, replaces, flushes, or
migrates an existing database.

Do not run migrations as part of packaging. Keep the packaged folder together
when distributing it, and preserve `%LOCALAPPDATA%\Dealer Management\` across
application updates. Rebuilding or replacing `dist/Dealer Management/` cannot
delete this external data directory.
