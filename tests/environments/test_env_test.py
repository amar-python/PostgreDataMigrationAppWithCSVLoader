"""Contract tests for the test environment."""
import unittest
import pytest
from tests.environments._contract import EnvironmentContract

pytestmark = [pytest.mark.integration, pytest.mark.parity]


class TestEnvironment(EnvironmentContract, unittest.TestCase):
    ENV = "test"; DB = "te_mgmt_test"; SCHEMA = "te_test"
    APP_USER = "te_test_user"; CONN_LIMIT = 15; SEEDED = True
