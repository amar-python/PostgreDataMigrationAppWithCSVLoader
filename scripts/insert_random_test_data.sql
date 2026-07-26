-- Insert one linked random test dataset across every te_dev table.
-- Run this in pgAdmin Query Tool while connected to database: te_mgmt_dev.
--
-- The script creates rows in all 12 tables:
-- organisations, personnel, test_programs, temp_documents, test_phases,
-- requirements, test_cases, vcrm_entries, test_events, test_results,
-- defect_reports, and evidence_artifacts.

BEGIN;

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

DO $$
DECLARE
    token text := lower(substr(replace(uuid_generate_v4()::text, '-', ''), 1, 10));
    org_id uuid;
    person_id uuid;
    program_id uuid;
    temp_id uuid;
    phase_id uuid;
    req_id uuid;
    tc_id uuid;
    vcrm_id uuid;
    event_id uuid;
    result_id uuid;
    defect_id uuid;
    artifact_id uuid;
BEGIN
    INSERT INTO te_dev.organisations (
        name,
        org_type,
        country,
        is_active
    )
    VALUES (
        'Agent Random Organisation ' || token,
        'test_unit',
        'AU',
        true
    )
    RETURNING organisations.org_id INTO org_id;

    INSERT INTO te_dev.personnel (
        org_id,
        full_name,
        email,
        te_role,
        clearance,
        password_hash,
        last_login_at,
        is_active
    )
    VALUES (
        org_id,
        'Agent Random Tester ' || token,
        'agent.tester.' || token || '@example.invalid',
        'test_engineer',
        'NV1',
        'test-only-random-hash-' || token,
        now(),
        true
    )
    RETURNING personnel.person_id INTO person_id;

    INSERT INTO te_dev.test_programs (
        org_id,
        program_director_id,
        program_code,
        program_name,
        capability_area,
        classification,
        status,
        start_date,
        end_date
    )
    VALUES (
        org_id,
        person_id,
        'AGT-' || token,
        'Agent Random Program ' || token,
        'Synthetic validation data',
        'UNCLASSIFIED',
        'active',
        current_date,
        current_date + 30
    )
    RETURNING test_programs.program_id INTO program_id;

    INSERT INTO te_dev.temp_documents (
        program_id,
        author_id,
        version,
        title,
        status,
        approved_by_id,
        approved_at,
        doc_path
    )
    VALUES (
        program_id,
        person_id,
        'v1-' || token,
        'Agent Random TEMP ' || token,
        'approved',
        person_id,
        now(),
        '/synthetic/agent/' || token || '/temp.pdf'
    )
    RETURNING temp_documents.temp_id INTO temp_id;

    INSERT INTO te_dev.test_phases (
        program_id,
        phase_manager_id,
        phase_code,
        phase_type,
        phase_name,
        status,
        planned_start,
        planned_end,
        actual_start,
        actual_end
    )
    VALUES (
        program_id,
        person_id,
        'P-' || upper(substr(token, 1, 6)),
        'DT&E',
        'Agent Random Phase ' || token,
        'completed',
        current_date,
        current_date + 7,
        current_date,
        current_date + 7
    )
    RETURNING test_phases.phase_id INTO phase_id;

    INSERT INTO te_dev.requirements (
        program_id,
        req_identifier,
        title,
        description,
        req_type,
        priority,
        source_document,
        verification_method
    )
    VALUES (
        program_id,
        'REQ-' || upper(token),
        'Agent random requirement ' || token,
        'Synthetic requirement text generated for agent connectivity testing: ' || md5(random()::text),
        'functional',
        1,
        'Agent random source document ' || token,
        'test'
    )
    RETURNING requirements.req_id INTO req_id;

    INSERT INTO te_dev.test_cases (
        phase_id,
        author_id,
        tc_identifier,
        title,
        objective,
        preconditions,
        steps,
        expected_result,
        tc_type,
        status
    )
    VALUES (
        phase_id,
        person_id,
        'TC-' || upper(token),
        'Agent random test case ' || token,
        'Confirm random synthetic data can flow through every table.',
        'Dev database is available and agent SQL script is running.',
        '1. Prepare random payload ' || token || E'\n2. Execute synthetic validation\n3. Record evidence',
        'All linked rows are inserted successfully.',
        'functional',
        'approved'
    )
    RETURNING test_cases.tc_id INTO tc_id;

    INSERT INTO te_dev.vcrm_entries (
        req_id,
        tc_id,
        coverage_type,
        rationale,
        added_by_id
    )
    VALUES (
        req_id,
        tc_id,
        'full',
        'Random agent test maps this generated requirement to its generated test case.',
        person_id
    )
    RETURNING vcrm_entries.vcrm_id INTO vcrm_id;

    INSERT INTO te_dev.test_events (
        phase_id,
        event_lead_id,
        event_code,
        event_name,
        event_type,
        location,
        status,
        planned_start,
        planned_end,
        actual_start,
        actual_end
    )
    VALUES (
        phase_id,
        person_id,
        'EVT-' || upper(token),
        'Agent Random Event ' || token,
        'lab',
        'Synthetic Lab ' || token,
        'completed',
        current_date,
        current_date + 1,
        current_date,
        current_date + 1
    )
    RETURNING test_events.event_id INTO event_id;

    INSERT INTO te_dev.test_results (
        event_id,
        tc_id,
        executed_by_id,
        verdict,
        executed_at,
        actual_result,
        notes,
        evidence_ref
    )
    VALUES (
        event_id,
        tc_id,
        person_id,
        'fail',
        now(),
        'Synthetic random result payload ' || md5(random()::text),
        'Inserted by agent test script using token ' || token,
        '/synthetic/agent/' || token || '/raw-result.log'
    )
    RETURNING test_results.result_id INTO result_id;

    INSERT INTO te_dev.defect_reports (
        result_id,
        program_id,
        raised_by_id,
        assigned_to_id,
        defect_ref,
        title,
        description,
        severity,
        status,
        resolution,
        raised_at,
        resolved_at
    )
    VALUES (
        result_id,
        program_id,
        person_id,
        person_id,
        'DR-AGT-' || upper(token),
        'Agent random defect ' || token,
        'Synthetic defect text for agent insert validation: ' || md5(random()::text),
        'minor',
        'resolved',
        'Synthetic resolution recorded for random agent test.',
        now(),
        now()
    )
    RETURNING defect_reports.defect_id INTO defect_id;

    INSERT INTO te_dev.evidence_artifacts (
        result_id,
        uploaded_by_id,
        artifact_name,
        artifact_type,
        file_path,
        file_size_kb,
        checksum_sha256
    )
    VALUES (
        result_id,
        person_id,
        'agent-random-evidence-' || token || '.log',
        'log',
        '/synthetic/agent/' || token || '/evidence.log',
        42,
        repeat(substr(md5(token), 1, 32), 2)
    )
    RETURNING evidence_artifacts.artifact_id INTO artifact_id;

    RAISE NOTICE 'Inserted random agent dataset token=%', token;
    RAISE NOTICE 'organisation=% personnel=% program=% temp=% phase=% requirement=% test_case=% vcrm=% event=% result=% defect=% artifact=%',
        org_id, person_id, program_id, temp_id, phase_id, req_id, tc_id, vcrm_id, event_id, result_id, defect_id, artifact_id;
END $$;

COMMIT;

SELECT
    'organisations' AS table_name,
    count(*) AS agent_random_rows
FROM te_dev.organisations
WHERE name LIKE 'Agent Random Organisation%'
UNION ALL
SELECT 'personnel', count(*) FROM te_dev.personnel WHERE email LIKE 'agent.tester.%@example.invalid'
UNION ALL
SELECT 'test_programs', count(*) FROM te_dev.test_programs WHERE program_code LIKE 'AGT-%'
UNION ALL
SELECT 'temp_documents', count(*) FROM te_dev.temp_documents WHERE title LIKE 'Agent Random TEMP%'
UNION ALL
SELECT 'test_phases', count(*) FROM te_dev.test_phases WHERE phase_name LIKE 'Agent Random Phase%'
UNION ALL
SELECT 'requirements', count(*) FROM te_dev.requirements WHERE req_identifier LIKE 'REQ-%'
UNION ALL
SELECT 'test_cases', count(*) FROM te_dev.test_cases WHERE tc_identifier LIKE 'TC-%'
UNION ALL
SELECT 'vcrm_entries', count(*) FROM te_dev.vcrm_entries v JOIN te_dev.requirements r ON r.req_id = v.req_id WHERE r.req_identifier LIKE 'REQ-%'
UNION ALL
SELECT 'test_events', count(*) FROM te_dev.test_events WHERE event_code LIKE 'EVT-%'
UNION ALL
SELECT 'test_results', count(*) FROM te_dev.test_results WHERE notes LIKE 'Inserted by agent test script%'
UNION ALL
SELECT 'defect_reports', count(*) FROM te_dev.defect_reports WHERE defect_ref LIKE 'DR-AGT-%'
UNION ALL
SELECT 'evidence_artifacts', count(*) FROM te_dev.evidence_artifacts WHERE artifact_name LIKE 'agent-random-evidence-%'
ORDER BY table_name;
