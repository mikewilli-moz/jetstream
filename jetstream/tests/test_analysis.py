import datetime as dt
import json
import logging
import re
from datetime import timedelta
from textwrap import dedent
from unittest import mock
from unittest.mock import MagicMock, Mock

import mozanalysis.segments
import pandas as pd
import pytest
import pytz
import toml

import jetstream.analysis
from jetstream.analysis import Analysis, AnalysisPeriod
from jetstream.config import AnalysisSpec
from jetstream.errors import (
    ExplicitSkipException,
    HighPopulationException,
    NoEnrollmentPeriodException,
)
from jetstream.experimenter import ExperimentV1
from jetstream.logging import LogConfiguration

logger = logging.getLogger("TEST_ANALYSIS")


def test_get_timelimits_if_ready(experiments):
    config = AnalysisSpec().resolve(experiments[0])
    config2 = AnalysisSpec().resolve(experiments[2])

    analysis = Analysis("test", "test", config)
    analysis2 = Analysis("test", "test", config2)

    date = dt.datetime(2019, 12, 1, tzinfo=pytz.utc) + timedelta(0)
    assert analysis._get_timelimits_if_ready(AnalysisPeriod.DAY, date) is None
    assert analysis._get_timelimits_if_ready(AnalysisPeriod.WEEK, date) is None

    date = dt.datetime(2019, 12, 1, tzinfo=pytz.utc) + timedelta(2)
    assert analysis._get_timelimits_if_ready(AnalysisPeriod.DAY, date) is None
    assert analysis._get_timelimits_if_ready(AnalysisPeriod.WEEK, date) is None

    date = dt.datetime(2019, 12, 1, tzinfo=pytz.utc) + timedelta(7)
    assert analysis._get_timelimits_if_ready(AnalysisPeriod.DAY, date)
    assert analysis._get_timelimits_if_ready(AnalysisPeriod.WEEK, date) is None

    date = dt.datetime(2019, 12, 1, tzinfo=pytz.utc) + timedelta(days=13)
    assert analysis._get_timelimits_if_ready(AnalysisPeriod.DAY, date)
    assert analysis._get_timelimits_if_ready(AnalysisPeriod.WEEK, date)

    date = dt.datetime(2020, 2, 29, tzinfo=pytz.utc)
    assert analysis._get_timelimits_if_ready(AnalysisPeriod.OVERALL, date) is None

    date = dt.datetime(2020, 3, 1, tzinfo=pytz.utc)
    assert analysis._get_timelimits_if_ready(AnalysisPeriod.OVERALL, date)
    assert analysis2._get_timelimits_if_ready(AnalysisPeriod.OVERALL, date) is None

    date = dt.datetime(2019, 12, 1, tzinfo=pytz.utc) + timedelta(days=34)
    assert analysis._get_timelimits_if_ready(AnalysisPeriod.DAYS_28, date)


def test_regression_20200320():
    experiment_json = r"""
        {
          "experiment_url": "https://experimenter.services.mozilla.com/experiments/impact-of-level-2-etp-on-a-custom-distribution/",
          "type": "pref",
          "name": "Impact of Level 2 ETP on a Custom Distribution",
          "slug": "impact-of-level-2-etp-on-a-custom-distribution",
          "public_name": "Impact of Level 2 ETP",
          "status": "Live",
          "start_date": 1580169600000,
          "end_date": 1595721600000,
          "proposed_start_date": 1580169600000,
          "proposed_enrollment": null,
          "proposed_duration": 180,
          "normandy_slug": "pref-impact-of-level-2-etp-on-a-custom-distribution-release-72-80-bug-1607493",
          "normandy_id": 906,
          "other_normandy_ids": [],
          "variants": [
            {
              "description": "",
              "is_control": true,
              "name": "treatment",
              "ratio": 100,
              "slug": "treatment",
              "value": "true",
              "addon_release_url": null,
              "preferences": []
            }
          ]
        }
    """  # noqa
    experiment = ExperimentV1.from_dict(json.loads(experiment_json)).to_experiment()
    config = AnalysisSpec().resolve(experiment)
    analysis = Analysis("test", "test", config)
    with pytest.raises(NoEnrollmentPeriodException):
        analysis.run(current_date=dt.datetime(2020, 3, 19, tzinfo=pytz.utc), dry_run=True)


def test_regression_20200316(monkeypatch):
    experiment_json = r"""
    {
      "experiment_url": "https://blah/experiments/search-tips-aka-nudges/",
      "type": "addon",
      "name": "Search Tips aka Nudges",
      "slug": "search-tips-aka-nudges",
      "public_name": "Search Tips",
      "public_description": "Search Tips are designed to increase engagement with the QuantumBar.",
      "status": "Live",
      "countries": [],
      "platform": "All Platforms",
      "start_date": 1578960000000,
      "end_date": 1584921600000,
      "population": "2% of Release Firefox 72.0 to 74.0",
      "population_percent": "2.0000",
      "firefox_channel": "Release",
      "firefox_min_version": "72.0",
      "firefox_max_version": "74.0",
      "addon_experiment_id": null,
      "addon_release_url": "https://bugzilla.mozilla.org/attachment.cgi?id=9120542",
      "pref_branch": null,
      "pref_name": null,
      "pref_type": null,
      "proposed_start_date": 1578960000000,
      "proposed_enrollment": 21,
      "proposed_duration": 69,
      "normandy_slug": "addon-search-tips-aka-nudges-release-72-74-bug-1603564",
      "normandy_id": 902,
      "other_normandy_ids": [],
      "variants": [
        {
          "description": "Standard address bar experience",
          "is_control": false,
          "name": "control",
          "ratio": 50,
          "slug": "control",
          "value": null,
          "addon_release_url": null,
          "preferences": []
        },
        {
          "description": "",
          "is_control": true,
          "name": "treatment",
          "ratio": 50,
          "slug": "treatment",
          "value": null,
          "addon_release_url": null,
          "preferences": []
        }
      ]
    }
    """
    experiment = ExperimentV1.from_dict(json.loads(experiment_json)).to_experiment()
    config = AnalysisSpec().resolve(experiment)

    monkeypatch.setattr("jetstream.analysis.Analysis.ensure_enrollments", Mock())
    pre_start_time = dt.datetime.now(tz=pytz.utc)
    analysis = Analysis("test", "test", config)
    analysis.run(current_date=dt.datetime(2020, 3, 16, tzinfo=pytz.utc), dry_run=True)
    assert analysis.start_time is not None
    assert analysis.start_time >= pre_start_time


@mock.patch("jetstream.analysis.BigQueryClient")
@mock.patch("google.cloud.storage.Client")
def test_export_errors(mock_storage_client, mock_bq_client):
    experiment_json = r"""
    {
      "experiment_url": "https://blah/experiments/search-tips-aka-nudges/",
      "type": "addon",
      "name": "Search Tips aka Nudges",
      "slug": "search-tips-aka-nudges",
      "public_name": "Search Tips",
      "public_description": "Search Tips are designed to increase engagement with the QuantumBar.",
      "status": "Live",
      "countries": [],
      "platform": "All Platforms",
      "start_date": 1578960000000,
      "end_date": 1584921600000,
      "population": "2% of Release Firefox 72.0 to 74.0",
      "population_percent": "2.0000",
      "firefox_channel": "Release",
      "firefox_min_version": "72.0",
      "firefox_max_version": "74.0",
      "addon_experiment_id": null,
      "addon_release_url": "https://bugzilla.mozilla.org/attachment.cgi?id=9120542",
      "pref_branch": null,
      "pref_name": null,
      "pref_type": null,
      "proposed_start_date": 1578960000000,
      "proposed_enrollment": 21,
      "proposed_duration": 69,
      "normandy_slug": "addon-search-tips-aka-nudges-release-72-74-bug-1603564",
      "normandy_id": 902,
      "other_normandy_ids": [],
      "variants": [
        {
          "description": "Standard address bar experience",
          "is_control": false,
          "name": "control",
          "ratio": 50,
          "slug": "control",
          "value": null,
          "addon_release_url": null,
          "preferences": []
        },
        {
          "description": "",
          "is_control": true,
          "name": "treatment",
          "ratio": 50,
          "slug": "treatment",
          "value": null,
          "addon_release_url": null,
          "preferences": []
        }
      ]
    }
    """
    experiment = ExperimentV1.from_dict(json.loads(experiment_json)).to_experiment()
    config = AnalysisSpec().resolve(experiment)

    mock_client = MagicMock()
    mock_storage_client.return_value = mock_client
    mock_bucket = MagicMock()
    mock_client.get_bucket.return_value = mock_bucket
    mock_blob = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    mock_blob.upload_from_string.return_value = ""

    test_errors = json.loads(
        """
        [
            {
                "timestamp": "2022-07-26 05:37:27",
                "experiment": "test-default-as-first-screen-100-roll-out",
                "metric": null,
                "statistic": null,
                "log_level": "WARNING",
                "exception_type": null,
                "message": "Skipping test-default-as-first-screen-100-roll-out; skip=true in config"
            },
            {
                "timestamp": "2022-07-26 05:03:24",
                "experiment": "test-pref-search-experiment",
                "metric": null,
                "statistic": null,
                "log_level": "ERROR",
                "exception_type": "NoEnrollmentPeriodException",
                "message": "test-pref-search-experiment -> Experiment has no enrollment period"
            },
            {
                "timestamp": "2022-07-26 04:39:49",
                "experiment": "addon-search-tips-aka-nudges-release-72-74-bug-1603564",
                "metric": "merino_latency",
                "statistic": "bootstrap_mean",
                "log_level": "WARNING",
                "exception_type": "StatisticComputationException",
                "message": "Error statistic bootstrap_mean metric merino_latency: null values"
            },
            {
                "timestamp": "2022-07-26 04:41:49",
                "experiment": "addon-search-tips-aka-nudges-release-72-74-bug-1603564",
                "metric": "remote_settings_latency",
                "statistic": "bootstrap_mean",
                "log_level": "ERROR",
                "exception_type": "StatisticComputationException",
                "message": "Error statistic bootstrap_mean metric remote_settings_latency: null"
            },
            {
                "timestamp": "2022-07-26 04:42:49",
                "experiment": "addon-search-tips-aka-nudges-release-72-74-bug-1603564",
                "metric": "remote_settings_latency",
                "statistic": "bootstrap_mean",
                "log_level": "CRITICAL",
                "exception_type": "CriticalStatisticComputationException",
                "message": "Error statistic bootstrap_mean metric remote_settings_latency: null"
            }
        ]
        """
    )
    mock_bqc = MagicMock()
    mock_bq_client.return_value = mock_bqc
    mock_bqc.table_to_dataframe.return_value = pd.DataFrame.from_dict(test_errors)

    log_config = LogConfiguration(
        log_project_id="test_logs_project",
        log_dataset_id="test_logs_dataset",
        log_table_id="test_logs_table",
        task_profiling_log_table_id="task_profiling_log_table_id",
        task_monitoring_log_table_id="task_monitoring_log_table_id",
        log_to_bigquery=True,
    )
    analysis = Analysis("test_project", "test_dataset", config, log_config=log_config)
    analysis.export_errors("test_errors")

    mock_client.get_bucket.assert_called_once()
    mock_bucket.blob.assert_called_once()

    expected = json.loads(
        """
            [{
                "timestamp": "2022-07-26 04:41:49",
                "experiment": "addon-search-tips-aka-nudges-release-72-74-bug-1603564",
                "metric": "remote_settings_latency",
                "statistic": "bootstrap_mean",
                "log_level": "ERROR",
                "exception_type": "StatisticComputationException",
                "message": "Error statistic bootstrap_mean metric remote_settings_latency: null"
            },
            {
                "timestamp": "2022-07-26 04:42:49",
                "experiment": "addon-search-tips-aka-nudges-release-72-74-bug-1603564",
                "metric": "remote_settings_latency",
                "statistic": "bootstrap_mean",
                "log_level": "CRITICAL",
                "exception_type": "CriticalStatisticComputationException",
                "message": "Error statistic bootstrap_mean metric remote_settings_latency: null"
            }]
        """
    )

    mock_blob.upload_from_string.assert_called_once_with(
        data=pd.DataFrame.from_dict(expected)
        .set_index("experiment")
        .to_json(orient="records", date_format="iso", indent=4),
        content_type="application/json",
    )


def test_validate_doesnt_explode(experiments, monkeypatch):
    m = Mock()
    monkeypatch.setattr(jetstream.analysis, "dry_run_query", m)
    x = experiments[0]
    config = AnalysisSpec.default_for_experiment(x).resolve(x)
    Analysis("spam", "eggs", config).validate()
    assert m.call_count == 2


def test_analysis_doesnt_choke_on_segments(experiments, monkeypatch):
    conf = dedent(
        """
        [experiment]
        segments = ["regular_users_v3"]
        """
    )
    spec = AnalysisSpec.from_dict(toml.loads(conf))
    configured = spec.resolve(experiments[0])
    assert isinstance(configured.experiment.segments[0], mozanalysis.segments.Segment)
    monkeypatch.setattr("jetstream.analysis.Analysis.ensure_enrollments", Mock())
    Analysis("test", "test", configured).run(
        current_date=dt.datetime(2020, 1, 1, tzinfo=pytz.utc), dry_run=True
    )


def test_is_high_population_check(experiments):
    x = experiments[3]
    config = AnalysisSpec.default_for_experiment(x).resolve(x)

    with pytest.raises(HighPopulationException):
        Analysis("spam", "eggs", config).check_runnable()


def test_skip_works(experiments):
    conf = dedent(
        """
        [experiment]
        skip = true
        """
    )
    spec = AnalysisSpec.from_dict(toml.loads(conf))
    configured = spec.resolve(experiments[0])
    with pytest.raises(ExplicitSkipException):
        Analysis("test", "test", configured).run(
            current_date=dt.datetime(2020, 1, 1, tzinfo=pytz.utc), dry_run=True
        )


def test_fenix_experiments_use_right_datasets(fenix_experiments, monkeypatch):
    for experiment in fenix_experiments:
        called = 0

        def dry_run_query(query):
            nonlocal called
            called = called + 1
            dataset = re.sub(r"[^A-Za-z0-9_]", "_", experiment.app_id)
            assert dataset in query
            assert query.count(dataset) == query.count("org_mozilla")

        monkeypatch.setattr("jetstream.analysis.dry_run_query", dry_run_query)
        config = AnalysisSpec.default_for_experiment(experiment).resolve(experiment)
        Analysis("spam", "eggs", config).validate()
        assert called == 2


def test_firefox_ios_experiments_use_right_datasets(firefox_ios_experiments, monkeypatch):
    for experiment in firefox_ios_experiments:
        called = 0

        def dry_run_query(query):
            nonlocal called
            called = called + 1
            dataset = re.sub(r"[^A-Za-z0-9_]", "_", experiment.app_id).lower()
            assert dataset in query
            assert query.count(dataset) == query.count("org_mozilla_ios")

        monkeypatch.setattr("jetstream.analysis.dry_run_query", dry_run_query)
        config = AnalysisSpec.default_for_experiment(experiment).resolve(experiment)
        Analysis("spam", "eggs", config).validate()
        assert called == 2


def test_focus_android_experiments_use_right_datasets(focus_android_experiments, monkeypatch):
    for experiment in focus_android_experiments:
        called = 0

        def dry_run_query(query):
            nonlocal called
            called = called + 1
            dataset = re.sub(r"[^A-Za-z0-9_]", "_", experiment.app_id).lower()
            assert dataset in query
            assert query.count(dataset) == query.count("org_mozilla_focus")

        monkeypatch.setattr("jetstream.analysis.dry_run_query", dry_run_query)
        config = AnalysisSpec.default_for_experiment(experiment).resolve(experiment)
        Analysis("spam", "eggs", config).validate()
        assert called == 2


def test_klar_android_experiments_use_right_datasets(klar_android_experiments, monkeypatch):
    for experiment in klar_android_experiments:
        called = 0

        def dry_run_query(query):
            nonlocal called
            called = called + 1
            dataset = re.sub(r"[^A-Za-z0-9_]", "_", experiment.app_id).lower()
            assert dataset in query
            assert query.count(dataset) == query.count("org_mozilla_klar")

        monkeypatch.setattr("jetstream.analysis.dry_run_query", dry_run_query)
        config = AnalysisSpec.default_for_experiment(experiment).resolve(experiment)
        Analysis("spam", "eggs", config).validate()
        assert called == 2
