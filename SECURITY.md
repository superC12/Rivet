# Security policy

## Supported versions

Security fixes are made on the current release line. Upgrade to the latest
published release before reporting an issue that may already be fixed.

## Reporting a vulnerability

Please report security issues privately through GitHub's **Report a
vulnerability** feature rather than opening a public issue. Include the
affected version, reproduction steps, impact, and a minimal sanitized example.
Do not include real API keys, prompts, conversation data, hostnames, or private
network addresses.

Please allow maintainers time to investigate and prepare a fix before public
disclosure. You will receive acknowledgement through the private advisory.

## Deployment boundary

Rivet is designed to bind to `127.0.0.1` by default. It does not provide
internet-facing user authentication. Do not publish an instance directly to
the public internet. Use Tailscale or an authenticated TLS reverse proxy for
remote access.

The project does not execute model-generated shell commands. Wake-on-LAN,
provider destinations, actions, and remote nodes must be explicitly configured
by the administrator. Treat provider endpoints and action gateways as trusted
infrastructure: conversation content may be sent to a configured destination
when routing policy permits it.
