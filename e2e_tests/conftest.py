import os
import subprocess
import time

import pytest
import requests


@pytest.fixture(scope="session", autouse=True)
def django_server():
    # Start containers
    path = os.path.dirname(os.path.abspath(__file__))
    # pylint: disable-next=consider-using-with
    server_process = subprocess.Popen([os.path.join(path, "run_servers.sh")], stdin=subprocess.PIPE)

    # Wait 2 minutes for the server to be ready
    max_retries = 120
    for _ in range(max_retries):
        try:
            response = requests.get("http://localhost:8000/") # pylint: disable=missing-timeout
            if response.status_code == 200:
                # Wait a bit more to let the server settle (tests may fail otherwise)
                time.sleep(10)
                break
        except requests.ConnectionError:
            pass

        time.sleep(1)

    # Run tests
    yield

    # Stop containers and remove data
    server_process.communicate(input=b'q')
