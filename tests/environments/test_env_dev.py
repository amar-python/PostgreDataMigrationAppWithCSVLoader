"""Contract tests for the dev environment."""
import unittest
import pytest
from tests.environments._contract import EnvironmentContract

pytestmark = [pytest.mark.integration, pytest.mark.parity]


class DevEnvironment(EnvironmentContract, unittest.TestCase):
    ENV = "dev"; DB = "te_mgmt_dev"; SCHEMA = "te_dev"
    APP_USER = "te_dev_user"; CONN_LIMIT = 10; SEEDED = True
