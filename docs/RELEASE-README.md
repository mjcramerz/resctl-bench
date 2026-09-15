# resctl-bench runtime release

This archive was produced by the independent Debian Forky build kit. Verify the
outer tarball checksum before extraction, then run `sha256sum -c SHA256SUMS` or
`python3 install.py --package . --verify` in the extracted directory. Checksums
are integrity records, not a publisher signature.

`bin/` contains resctl-bench, rd-agent, rd-hashd and optionally resctl-demo.
`bin/.debug/` contains matching debug files when split-debug packaging was
selected. `share/resctl-bench/build/` records selected inputs, flags, logs,
original and effective Cargo locks, update evidence, compiler identity and ELF
inspection. Documentation is in `share/doc/resctl-bench/`; licenses and the
third-party inventory are under `share/licenses/resctl-bench/`.

The package is dynamically linked. Install required Debian libraries and runtime
tools separately. Native builds require the build CPU or verified-compatible
hardware. A portable build removes native tuning but does not guarantee support
for another glibc release. Inspect recorded ELF dependencies and host metadata.

Install deliberately as root with:

```sh
python3 install.py --package . --prefix /usr/local
```

Or add --destdir /absolute/staging/root for staged installation. Existing
conflicts are refused unless --force is explicitly supplied. Uninstall through
this installer with --uninstall --prefix /usr/local; locally modified tracked
files are refused, not silently deleted. No daemon or benchmark is started.

Read the packaged runtime guide and upstream job documentation before execution.
`python3 runtime_check.py --path /existing/scratch/directory` is read-only;
`resctl-bench deps` is not the same operation. Never infer benchmark readiness
or safe raw-disk access from a successful build or --help/--version test.
