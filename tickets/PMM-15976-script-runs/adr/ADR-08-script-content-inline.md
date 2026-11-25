# ADR-08: Script content travels inline; the host fetches nothing

- Status: Proposed
- Date: 2026-11-18
- Tickets: PMM-15976
- Planned in: plan 01; plan 04 for PMM Extensions

## Context

Today a host gets a task's script in one of three ways [V, `app/tasks/db/seed.py` in percona/pmm-extensions]:
- **As a command string** in the job's metadata (`run-command`).
- **Inline**, as a gzipped payload of at most 16 KiB that Nomad writes to a file (`run-python`).
- **By download.** Nomad on the host fetches the artifact from a URL and checks it against a checksum (`exec-artifact`, `exec-python-artifact`).

Inputs reach a script as Nomad metadata, which Nomad turns into environment variables and rendered files. A task's configuration is one of those environment variables.

The prototype carries the download: the caller names any URL, a checksum (MD5 accepted) and an optional switch that skips TLS verification, and pmm-agent fetches it. It does not carry the two kinds without a download; the spike estimated about 70 lines for them [V].

Scripts are small. Every artifact PMM Extensions' own apps send comes from its own store, behind an address it signs (`app/extensions/apps/framework/script_helpers.py:132-175` in percona/pmm-extensions) [V].

pmm-agent accepts messages of up to 4 MiB from the server, gRPC's default, which nothing in `agent/` raises [I].

## Options

1. **The host downloads by URL and checksum** (today, and the prototype). Rejected: the host needs a route and a credential to the artifact store, and the download is a second network path to secure on every host.
2. **Content inline in the request, through the agent stream.**
3. **Both.** Rejected: two paths to secure and test, for artifacts that fit in one.

## Decision

Option 2.

- A request carries `files`: a name, the content and a mode for each. pmm-agent writes them into the run directory before the start, and starts the process there. A name has no path in it, and a mode sets owner bits only.
- Content is text. The content of all files of one request is at most 1 MiB, and so is `stdin`.
- pmm-managed records each file's name, size and SHA-256, and never its content (ADR-05).
- A run's command is a list: the program and its arguments. pmm-agent does not pass it through a shell. The program must resolve on the host, or the run ends as `prepare_failed`.
- Inputs that are secret travel as `stdin` or as a file of mode 0600, never in the environment.
- PMM Extensions fetches an artifact itself, from the address it gives Nomad today, and sends it. It accepts only its own artifact addresses for this. Its four kinds become one shape: files, a command, inputs.

## Consequences

- A database host no longer downloads anything to run a task. The download and its settings go away.
- The two task kinds the prototype did not carry need no separate mechanism.
- Everything a script needs must fit in 1 MiB of text or already be on the host. A task that needs a large or binary file fetches it itself, in its script, with its own credentials. PMM Extensions refuses a task that exceeds the limit before sending anything, and plan 04 checks every shipped task against it.
- Python dependencies are still installed on the host with `pip`, from the network the host has. That is unchanged and outside this decision.
- The content passes through pmm-managed's memory and the agent stream. Both are already trusted with database credentials.
- The run path measured in the spike used the download. The inline path is not built; test T16 measures it for all four kinds.
