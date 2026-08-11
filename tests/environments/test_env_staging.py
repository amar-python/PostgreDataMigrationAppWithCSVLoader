"""Contract tests for the staging environment."""
import unittest
import pytest
from tests.environments._contract import EnvironmentContract

pytestmark = [pytest.mark.integration, pytest.mark.parity]


class StagingEnvironment(EnvironmentContract, unittest.TestCase):
    ENV = "staging"; DB = "te_mgmt_staging"; SCHEMA = "te_staging"
    APP_USER = "te_stg_user"; CONN_LIMIT = 25; SEEDED = False
