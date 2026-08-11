"""Contract tests for the prod environment."""
import unittest
import pytest
from tests.environments._contract import EnvironmentContract

pytestmark = [pytest.mark.integration, pytest.mark.parity]


class ProdEnvironment(EnvironmentContract, unittest.TestCase):
    ENV = "prod"; DB = "te_mgmt_prod"; SCHEMA = "te_prod"
    APP_USER = "te_prod_user"; CONN_LIMIT = 50; SEEDED = False
