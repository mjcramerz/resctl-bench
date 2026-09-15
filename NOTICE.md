# Ownership and distribution boundaries

This independent build kit is not an official Meta/Facebook release. Its own
scripts and documentation are provided under the MIT license in LICENSE.

The upstream project is https://github.com/facebookexperimental/resctl-demo.
Upstream identifies its project license as Apache-2.0; copyright and license
notices remain with the fetched code. Rust dependencies have their own licenses.
No upstream authorship or ownership is claimed by this build kit.

The initial downloadable kit contains no upstream implementation or dependency
source snapshots. `make source-dist` creates the populated source distribution
on your network-enabled build host. Runtime distributions copy upstream's
LICENSE and collect license files available in the resolved dependency source
directories. Check THIRD-PARTY.json and the actual licenses before redistribution;
this inventory is neither license clearance nor a certified SBOM.

The test fixtures are tiny synthetic programs and Git repositories. They are
not resctl-bench binaries and are never included in runtime release packages.
