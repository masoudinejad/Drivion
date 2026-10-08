# LiteRT dependency metadata repair

LiteRT 2.3.0 requires `backports.strenum` unconditionally, but that package declares
Python below 3.11. LiteRT's vendor target modules already select native
`enum.StrEnum` on Python 3.11 and later.

This local build backend downloads the official Python 3.13 ARM64 wheel and
verifies its pinned SHA-256 before changing the dependency to
`backports.strenum; python_version < "3.11"`. It regenerates wheel RECORD hashes;
all runtime code and compiled binaries retain their upstream contents. No wheel
binary is stored in Git. Building requires network access to files.pythonhosted.org.

The dependency list in this directory matches the upstream base dependencies
with the corrected marker. Optional NPU SDK extras are outside this car setup.
This workaround is specific to LiteRT 2.3.0 on the current Pi platform. When
updating LiteRT, check upstream metadata and remove this source override once
an upstream release fixes the dependency marker.
