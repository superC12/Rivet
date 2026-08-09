# Security policy

Rivet is designed to bind to `127.0.0.1` by default. Do not publish an unauthenticated instance directly to the public internet. Use Tailscale or an authenticated TLS reverse proxy for remote access.

Please report security issues privately through GitHub's **Report a vulnerability** feature rather than opening a public issue. Include the affected version, reproduction steps, and impact. Do not include real API keys, prompts, or conversation data.

The project does not execute model-generated shell commands. Wake-on-LAN and provider destinations must be explicitly configured by the administrator.
