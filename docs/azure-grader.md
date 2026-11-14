# Azure POC execution worker

The web app queues `ExecutionJob` rows in PostgreSQL. A single controller on
`cs1301-poc-grader-vm` polls the authenticated HTTPS claim endpoint and returns
observations and grading results. Redis/Celery is not required for this path.

The VM is `Standard_B2als_v2` (2 vCPUs, 4 GiB RAM) in South Central US. It processes
up to two attempts concurrently (`RUNNER_CONCURRENCY=2`); this is a small
demonstration deployment, not a capacity
commitment for 700 students. Drain active work before resizing or stopping it.

## Isolation boundaries

- VM has no managed identity, database password, storage credential or Canvas token.
- Dedicated subnet `cs1301-poc-grader-subnet` (`10.0.4.0/27`) in `cs1301-poc-vnet` uses
  `cs1301-poc-grader-nsg`. Priority 100 rules deny all inbound connections and
  outbound traffic to the `VirtualNetwork` service tag. No SSH ports are opened.
- The trusted controller has only `RUNNER_TOKEN`, which authorizes the internal
  queue endpoints. This credential must not be shared with students.
- Each test runs in a new non-root Docker container with networking disabled,
  read-only root filesystem, temporary workspace, all capabilities dropped,
  no-new-privileges, PID/memory/CPU limits, bounded output and a wall-clock timeout.
  The Docker socket and host directories are never mounted in the student container.
- Expected answers and grading rules stay in the controller. The sandbox receives
  student source/files and test inputs only. It returns untrusted observations;
  the controller determines scores. No legacy Vocareum grader scripts are executed.
- Containers are forcibly removed in `finally`, including on timeout/output flood.
  Attempts exceeding the four-minute controller budget fail without recording a zero.
- The worker restarts automatically under systemd after failure or VM reboot.

Docker containers share the VM kernel. This is the POC boundary; stronger sandboxing
and load testing should be evaluated before opening execution to a full class.

## Install and operate

Run from the repository with Azure CLI signed into the project subscription:

```bash
python scripts/azure-grader-vm.py install
python scripts/azure-grader-vm.py connect
python scripts/azure-grader-vm.py status
python scripts/azure-grader-vm.py enable
```

`install` uploads an allowlisted source bundle, installs Docker, builds the Python
image on the VM, and runs the real grading/isolation tests. `connect` stores a
dedicated app secret and delivers it to the VM through managed Run Command's
protected parameters. Existing app secrets and registry authentication are preserved.
It leaves execution disabled until explicitly enabled after verification.

After enabling execution, verify the full HTTPS flow with temporary data:

```bash
python scripts/smoke-azure-grader.py --url https://YOUR-TRELLIS-HOST
python scripts/smoke-azure-preview.py --credentials var/azure-poc/login-details.json --execution-enabled
```

The grader check creates a temporary course/student, tests real VM execution,
points and workspace file replacement, then removes its temporary database rows
and private blobs. Real student work and course grades are not used.

The worker runs `/opt/trellis/runner/service.py` using `/opt/trellis/venv`.
Its root-readable configuration is `/opt/trellis/worker.env` (mode 0600).
Inspect service health through the script's `status` command or Azure Run Command.
Do not print that environment file or copy credentials into Git.

```bash
python scripts/azure-grader-vm.py disable
```

This stops new execution requests at the web app while preserving course browsing,
native questions, submissions and existing results. It does not stop VM billing.
To pause compute charges, stop/deallocate the dedicated grader VM after active work
finishes. Disk and public-IP charges can remain. Never delete the shared resource group.

Changes to `runner/` can be installed by rerunning `install`, followed by `connect`
to restart the worker. Avoid replacing files while it is grading an active attempt.
Local development still uses `scripts/start-worker.sh` with Docker Desktop.
