# Security and private material

The Dashboard is a local read-only service. Keep its default loopback binding. It does not provide a network authentication service, tenancy or remote sharing. Project documents and logs are untrusted input; they must be displayed as text and accessed within the workspace boundary.

The CLI executes project Python only when the user requests the run workflow. It is not a sandbox for untrusted source code. Review a downloaded example before executing it. Credentials, private paths, contest identities and unreleased problem material belong outside a public patch or issue.

For a suspected vulnerability, preserve a minimal reproduction using synthetic data. Do not publish an exploit containing actual workspaces or keys. No security contact address or private advisory endpoint is confirmed for this local candidate; contact the owner through the existing private delivery channel. A future public maintainer must provide a real private reporting channel before release.

This document does not claim a security audit, identity authentication, continuous maintenance or a response-time commitment. See [support and limitations](docs/SUPPORT_MATRIX.md) and [release scope](LICENSE_SCOPE.md).
