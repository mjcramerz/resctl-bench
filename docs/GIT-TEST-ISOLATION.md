# Git recovery test isolation - buildkit 2.4.1

## Reproduced failure

The old test copied ROOT recursively without excluding its outer `.git`. When
run from a committed checkout, the temporary fixture therefore inherited HEAD,
index, branch, remotes and hooks. `git init` reinitialized that existing checkout;
`git add .` staged no changes, and the assumed first `git commit` failed with:

    On branch mcr/main
    nothing to commit, working tree clean

This was reproduced from the prior release's exact test against a clean committed
fixture. It is not a Cargo compilation error or evidence that a native benchmark
failed. The prior archive-only run missed the problem because that archive had
no outer Git checkout metadata.

## Repair

`copy_fixture_repository()` excludes `.git` ONLY at the copied repository root.
It handles an ordinary directory, linked-worktree `.git` file and `.git` symlink
without following private metadata. `upstream/.git` remains present because it is
part of the locked native source identity and recovery tests. Build caches and
recovery backups remain excluded as before.

`execute()` filters inherited GIT_* routing/configuration variables and gives its
subprocess tree an explicit offline Git environment: user/system configuration,
commit signing, hooks and init templates cannot contaminate the test. Author and
committer identities are test-only values. No user's Git files/configuration are
changed. No --allow-empty workaround or skipped commit masks the assertion: the
fixture still makes a first non-empty source distribution commit, verifies the
tracked recovery asset, clones locally without hardlinks, and restores missing
upstream source offline from the pinned archive.

Five additional regression cases cover committed clean checkouts, real linked
worktrees, outer .git symlinks, inherited Git routing/index/object environment,
and user hooks/templates/signing. The reported test itself remains enabled.
Both an ordinary user and root can run the same test command:

    ./BUILD.sh lint test

Tests are SOFTWARE checks. Several existing pipeline cases intentionally use
labelled Cargo/C doubles and do not compile the actual Rust workspace. Run the
separate real native-validate gate before installing unvalidated binaries.

## Native compatibility

Buildkit version changes from 2.4.0 to 2.4.1; IOCost Lab changes to 2.6.0. The native
package stays 2.2.6, contract resctl-iocost-lab-v3. This revision changes NO native
Rust files, collector/generator/balloon helper bytes, Cargo.lock, source lock,
reviewed native patch, source manifest or pinned upstream recovery archive.
A successfully built and validated v3 trio remains compatible; a prior absence
of actual native compilation is not converted into a claimed native pass.

## Ambient offline-mode isolation

Final archive validation was also run with inherited `OFFLINE=1`. That exposed
four older Make pipeline fixtures that need to clone their new temporary LOCAL
source repository before building. They unintentionally inherited the caller's
offline mode and failed before exercising their assertions. The fixture setup
now explicitly selects `OFFLINE=0` for that local-only default; dedicated offline
cases still set `Config.offline=True` or command-line `OFFLINE=1`.

This is test-environment isolation only. Production `OFFLINE=1` remains enforced,
no network source is added, and no compiler/package installation is enabled.
The complete 266-test suite is rechecked with inherited `OFFLINE=1` as root and
an ordinary user. The initial failure log is retained as regression evidence.
