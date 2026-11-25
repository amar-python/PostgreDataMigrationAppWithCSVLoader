"""#347 (CLI-01): every job's CSV and schema path must point at a file that exists.

``config.yaml`` named ``./OneDrive/Desktop/Migration using ai/input_data/...``, a folder that does not exist anywhere
else, so ``python main.py migrate`` loaded nothing. ``auto_migrate.py`` wrote the same wrong path for every new job, and
read ``config.yaml`` from the home folder instead of from the tool's own folder.

What must hold (no database needed):
  * every job in ``config.yaml`` has a CSV and a schema file that exist, inside ``input_data/`` next to ``config.yaml``;
  * ``config.yaml`` names no personal or absolute location;
  * ``auto_migrate`` finds ``config.yaml`` next to itself, not in the home folder;
  * the path ``auto_migrate`` writes for a new file is relative to ``config.yaml`` and, once read back by ``load_jobs``,
    points at that file.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import auto_migrate  # noqa: E402
from src.config import load_jobs  # noqa: E402


def test_every_job_in_config_yaml_points_at_files_that_exist(config_path):
    jobs = load_jobs(config_path)
    assert len(jobs) >= 3, "config.yaml lost its jobs, so this check would pass on nothing"
    missing = []
    for job in jobs:
        for label, path in (("source_csv", job.source_csv), ("schema_file", job.schema_file)):
            if not Path(path).is_file():
                missing.append(f"{job.name}.{label}: {path}")
    assert not missing, "paths that do not exist:\n  " + "\n  ".join(missing)


def test_every_job_path_is_inside_input_data_next_to_config_yaml(config_path):
    input_dir = (config_path.parent / "input_data").resolve()
    outside = [f"{job.name}.{label}: {path}" for job in load_jobs(config_path)
               for label, path in (("source_csv", job.source_csv), ("schema_file", job.schema_file))
               if input_dir not in Path(path).resolve().parents]
    assert not outside, "paths outside input_data/:\n  " + "\n  ".join(outside)


def test_config_yaml_names_no_personal_or_absolute_location(config_path):
    text = config_path.read_text(encoding="utf-8")
    for bad in ("OneDrive", "Desktop", "Migration using ai", "C:\\", "/home/", "/Users/"):
        assert bad not in text, f"config.yaml still mentions {bad!r}"


def test_auto_migrate_reads_config_yaml_from_its_own_folder_not_the_home_folder():
    assert auto_migrate.CONFIG_PATH == ROOT / "config.yaml"
    assert auto_migrate.CONFIG_PATH.is_file()
    assert auto_migrate.REPO_ROOT != Path.home(), "REPO_ROOT guessed the home folder (see also #348)"


def test_the_path_written_for_a_new_file_is_relative_to_config_yaml(tmp_path, monkeypatch):
    (tmp_path / "input_data").mkdir()
    csv = tmp_path / "input_data" / "orders.csv"
    csv.write_text("id\n1\n", encoding="utf-8")
    monkeypatch.setattr(auto_migrate, "CONFIG_PATH", tmp_path / "config.yaml")
    assert auto_migrate.config_relative(csv) == "./input_data/orders.csv"


def test_a_job_written_by_auto_migrate_points_at_its_file_when_read_back(tmp_path, monkeypatch):
    """The last step of auto_migrate used to fail with 'CSV not found' for every new job."""
    (tmp_path / "input_data").mkdir()
    csv = tmp_path / "input_data" / "orders.csv"
    schema = tmp_path / "input_data" / "orders_schema.sql"
    csv.write_text("id,total\n1,5\n", encoding="utf-8")
    schema.write_text("CREATE TABLE orders (id INTEGER PRIMARY KEY, total INTEGER);\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text("jobs:\n", encoding="utf-8")
    monkeypatch.setattr(auto_migrate, "CONFIG_PATH", config)

    columns = [{"csv_name": "id", "db_column": "id", "type": "integer", "nullable": False},
               {"csv_name": "total", "db_column": "total", "type": "integer", "nullable": True}]
    auto_migrate.append_job_to_config("orders", auto_migrate.config_relative(csv), auto_migrate.config_relative(schema),
                                      columns, "id")

    (job,) = load_jobs(config)
    assert job.source_csv == csv.resolve() and job.source_csv.is_file()
    assert job.schema_file == schema.resolve() and job.schema_file.is_file()


def test_a_file_outside_the_config_folder_is_not_given_a_path_that_climbs_out_of_it(tmp_path, monkeypatch):
    """auto_migrate copies such a file into input_data/ first; the helper must refuse anything it did not."""
    monkeypatch.setattr(auto_migrate, "CONFIG_PATH", tmp_path / "config.yaml")
    outside = tmp_path.parent / "elsewhere.csv"
    with pytest.raises(ValueError):
        auto_migrate.config_relative(outside)


def test_a_new_file_dropped_in_input_data_is_found_by_the_real_config_layout(tmp_path):
    """Same layout as the repository: config.yaml, input_data/, and the files the shipped jobs name."""
    shutil.copytree(ROOT / "input_data", tmp_path / "input_data")
    shutil.copy(ROOT / "config.yaml", tmp_path / "config.yaml")
    jobs = load_jobs(tmp_path / "config.yaml")
    assert all(job.source_csv.is_file() and job.schema_file.is_file() for job in jobs)
