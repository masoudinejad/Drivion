# Code versions and deployment records

Git commits identify development history. Tag releases with `vMAJOR.MINOR.PATCH`,
such as `v0.1.0`: increment MAJOR for incompatible changes, MINOR for compatible
features, and PATCH for fixes. Tags are created explicitly when a release is
ready; syncing does not create commits or tags.

Every successful car sync publishes `car/system/version.toml` on the Pi, with a
matching local copy. It is generated metadata and ignored by Git. User settings
remain in `car/config.toml`.

```toml
[code]
version = "v0.1.0"
commit = "full Git commit hash"
dirty = false
checksum_sha256 = "SHA-256 of the deployed car snapshot"
deployed_at = "2026-10-08T15:30:00+00:00"
```

`version` uses the nearest matching Git release tag, with commit distance and
short hash when ahead of that tag. Before the first release tag, it is a short
commit hash. `dirty` indicates uncommitted changes anywhere in the repository,
including non-ignored untracked files. The checksum identifies the actual car
snapshot even when changes have not been committed.

Sync first freezes the deployable car files in a local temporary directory.
The checksum includes sorted relative file paths, contents, executable bits,
and symlink targets. Environments, caches, secrets, and the version record itself
are excluded. Rsync checks file contents and transfers that frozen snapshot.
The record is atomically published after a successful transfer. Dry runs and
SSH key setup do not update it. The Pi needs Python 3 for publishing the record.

File transfer itself is not atomic: an interrupted transfer can leave partially
updated code, while the previous version record remains. A successful record
describes the last completed sync; edits made later on the Pi are not reflected.

Check the record on the Pi:

```sh
cat ~/car/system/version.toml
```

Python consumers can read it with the standard `tomllib` module on Python 3.11+.
