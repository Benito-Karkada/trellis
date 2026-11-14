# Local load testing

These tools exercise disposable synthetic accounts against your own localhost setup. Start the services, seed the demo, and run the host execution worker first. They do not require an external monitoring service.

## Prepare

```sh
python3 -m venv .venv-loadtest
.venv-loadtest/bin/python -m pip install -r requirements-loadtest.txt
.venv-loadtest/bin/python loadtests/prepare.py --run-id local-demo-001 --users 10 --url http://localhost:5173
```

Choose a new run ID for each test. The command creates a separate synthetic course using the local Compose backend. Private test-account credentials are saved under ignored `var/loadtests/<run-id>/fixture.json`. Use your configured frontend port if different.

## Monitor and run

In a separate terminal:

```sh
.venv-loadtest/bin/python loadtests/monitor.py --fixture var/loadtests/local-demo-001/fixture.json --duration 420
```

Then run the bounded test:

```sh
.venv-loadtest/bin/python loadtests/run.py --fixture var/loadtests/local-demo-001/fixture.json --users 10 --minutes 5
```

Add `--dashboard` to open the Locust dashboard on http://localhost:8089. Monitoring records queue delays, completion timing, and Docker container CPU/memory snapshots. Monitor the host worker in its own terminal or your operating system's process monitor.

After the test and monitoring finish:

```sh
.venv-loadtest/bin/python loadtests/report.py --fixture var/loadtests/local-demo-001/fixture.json
```

Open the generated `report.html`. A local HTTP simulation does not measure browser rendering, video playback, or capacity on another machine. Keep these tests small while developing on a laptop. Only disposable local demo data should be used.
