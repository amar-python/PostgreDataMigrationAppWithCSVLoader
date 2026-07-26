# =============================================================================
# schema/influxdb/te_seed_data.lp — InfluxDB Line Protocol Seed Data
#
# InfluxDB is a time-series database. Instead of relational tables, data is
# stored as measurements with tags (indexed metadata) and fields (values).
#
# Format: measurement,tag1=val1,tag2=val2 field1=val1,field2=val2 timestamp
#
# Measurements used:
#   te_programs      — test program status and metadata over time
#   te_test_results  — individual test result verdicts (time-series events)
#   te_defects       — defect report lifecycle events
#   te_phase_progress— phase completion percentage over time
# =============================================================================

# ── te_programs — program status snapshots ────────────────────────────────────
te_programs,program_code=CYB9131,env=dev,classification=PROTECTED,status=active program_name="COSPO Cyber OT&E Programme",requirements_count=6i,tc_count=8i,vcrm_coverage=100.0 1735689600000000000
te_programs,program_code=LAND400-P3,env=dev,classification=SECRET,status=active program_name="LAND 400 Phase 3 IFV T&E",requirements_count=2i,tc_count=0i,vcrm_coverage=0.0 1735689600000000000

# ── te_test_results — individual result events ────────────────────────────────
te_test_results,program_code=CYB9131,event_code=CYB9131-OTE-EV01,tc_id=TC-OTE-001,verdict=pass,tc_type=security executed_by="Dr. Anika Sharma",duration_seconds=1.8,notes="TOTP login succeeded" 1739246100000000000
te_test_results,program_code=CYB9131,event_code=CYB9131-OTE-EV01,tc_id=TC-OTE-002,verdict=pass,tc_type=security executed_by="Dr. Anika Sharma",duration_seconds=0.047,notes="Lockout on 5th fail" 1739251800000000000
te_test_results,program_code=CYB9131,event_code=CYB9131-OTE-EV01,tc_id=TC-OTE-003,verdict=pass,tc_type=security executed_by="Marcus Tran",duration_seconds=45.2,notes="AES-256-GCM confirmed" 1739332800000000000
te_test_results,program_code=CYB9131,event_code=CYB9131-OTE-EV01,tc_id=TC-OTE-005,verdict=fail,tc_type=functional executed_by="Marcus Tran",duration_seconds=120.0,notes="28/30 operations logged — archive endpoint missing" 1739350200000000000
te_test_results,program_code=CYB9131,event_code=CYB9131-OTE-EV01,tc_id=TC-OTE-006,verdict=pass,tc_type=functional executed_by="Yasmin El-Khoury",duration_seconds=30.0,notes="All 12 admin endpoints returned 403" 1739436000000000000
te_test_results,program_code=CYB9131,event_code=CYB9131-OTE-EV01,tc_id=TC-OTE-008,verdict=fail,tc_type=security executed_by="Dr. Anika Sharma",duration_seconds=25.0,notes="TLS 1.2 accepted on /api/v1/legacy/export" 1739451600000000000
te_test_results,program_code=CYB9131,event_code=CYB9131-OTE-EV02,tc_id=TC-OTE-004,verdict=inconclusive,tc_type=performance executed_by="Marcus Tran",duration_seconds=86400.0,notes="24hr: 99.9% uptime — 72hr window in progress" 1745650800000000000

# ── te_defects — defect lifecycle events ─────────────────────────────────────
te_defects,program_code=CYB9131,defect_ref=DR-CYB-0001,severity=major,status=in_progress title="Audit Log gap on /api/v2/archive/",raised_by="Marcus Tran",days_open=70i 1739358000000000000
te_defects,program_code=CYB9131,defect_ref=DR-CYB-0002,severity=major,status=open title="TLS 1.2 accepted on legacy endpoint",raised_by="Dr. Anika Sharma",days_open=70i 1739458800000000000
te_defects,program_code=CYB9131,defect_ref=DR-CYB-0003,severity=minor,status=open title="Session timeout not enforced",raised_by="Flt Lt Sam Burgess",days_open=51i 1741082400000000000

# ── te_phase_progress — phase completion over time ────────────────────────────
te_phase_progress,program_code=CYB9131,phase_code=CYB9131-DTE,phase_type=DTE status="completed",tests_run=0i,tests_passed=0i,completion_pct=100.0 1735689600000000000
te_phase_progress,program_code=CYB9131,phase_code=CYB9131-OTE,phase_type=OTE status="active",tests_run=7i,tests_passed=4i,completion_pct=43.75,pass_rate=57.14 1745650800000000000
te_phase_progress,program_code=LAND400-P3,phase_code=L400P3-ATE,phase_type=ATE status="planned",tests_run=0i,tests_passed=0i,completion_pct=0.0 1748332800000000000
