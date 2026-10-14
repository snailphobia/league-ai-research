# Repository instructions

Read README.md and docs/*.md before changing the adapter or validation harness.

Keep the input adapter independent of League, model providers, and capture. Reuse maintained input libraries where they satisfy the contract. All host input is behind the Windows backend; importing the public API on another platform must not emit or attempt input.

Verify Windows behavior using an independent receiver and a real Windows desktop. Portable unit tests verify ownership, ordering, cleanup, and validation; they do not establish Windows input delivery. Keep VM disks, ISO files, credentials, and private traces outside this repository. Public test artifacts must contain no account credentials or personal input logs.

Changes are authorized for this repository. Do not modify existing shared inference deployments. Create pull requests only when explicitly requested.
