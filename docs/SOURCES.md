# Source provenance and coverage

This release is based on the user's resctl-bench.zip, not an independently chosen
replacement repository. Its upstream HEAD and lock identify:

```text
bef3b59c01ec79f3601ae6cf43ed2e34ad8fc45b
Cargo.lock SHA-256:
fff9f4c6aed12b24be9533907308943b06027e534f8e9466dccd2904831d23a7
```

The ZIP carried the original 163-entry working-file manifest and upstream Git
objects, but only three upstream working files were present. All other 160 were
restored from that same HEAD with recorded modes and checked against the original
manifest before changes. `source-preservation.json` records archive identity,
counts, original lock and the actual changed paths. `patches/base-source-manifest.json`
retains all original file hashes. The patched source manifest covers all 163
working files; nothing is replaced by a stub implementation.

The workspace includes rd-agent, rd-hashd, resctl-bench, resctl-demo, their
interface and utility crates, Cargo files, job documentation, tests/assets and
licenses. `patches/0001-embedded-runtime-compat.patch` contains the complete
native delta. Native benchmark/protection/coefficient algorithms and result
schema are not changed. The helper C measurement body is separately hashed in
compat/runtime-contract.json and is identical to the supplied original.

A minimal genuine upstream .git object store, index and HEAD are included so
build-time version reporting refers to the real supplied commit. Local source
changes remain truthfully dirty. User Git config, hooks, reflogs, local build
caches, prior compiler paths, private output logs and uploaded binary archives
are not included. Root build-kit .git data is not distributed. No SHA/version
impersonation or synthetic clean commit is used.

The build-kit version is 2.3.0. The patched upstream package version remains
2.2.6. These are deliberately different version scopes. Old changelog entries
are historical documentation, not proof of current compilation.

This is a complete **project source** snapshot, not an offline mirror of crates.io.
The uploaded ZIP did not contain all third-party Cargo crate sources; they have
not been invented or represented as vendored here. Use a populated host Cargo
cache or normal access to the locked dependency sources. `make vendor`/
`make source-dist` can populate a relocatable offline dependency bundle on the
build host. Dependencies retain their individual licenses and resolved metadata.

The build kit remains independent of Meta/Facebook and BCC. Original copyright
and license notices are retained. See NOTICE.md and upstream/LICENSE. Source
hashes detect accidental or unreviewed changes; they are not digital signatures.

External interface references used in this repair:

- BCC kernel compiler options: https://raw.githubusercontent.com/iovisor/bcc/master/src/cc/frontends/clang/kbuild_helper.cc
- findmnt JSON, explicit target and nofsroot: https://man7.org/linux/man-pages/man8/findmnt.8.html
- Cargo build script/source rebuild behavior: https://doc.rust-lang.org/cargo/reference/build-scripts.html

Runtime evidence is drawn from the supplied output archive. The redistribution
includes a redacted analytic description, not the user's private archive or
verbatim journals with host identifiers.
