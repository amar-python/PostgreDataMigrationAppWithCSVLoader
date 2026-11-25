CREATE TABLE ndis_participants (
    participant_id          INTEGER       PRIMARY KEY,
    first_name              VARCHAR(100)  NOT NULL,
    last_name               VARCHAR(100)  NOT NULL,
    plan_status             VARCHAR(20)   NOT NULL,
    primary_disability      VARCHAR(100)  NOT NULL,
    support_budget_core     NUMERIC(12,2) NOT NULL,
    support_budget_capacity NUMERIC(12,2) NOT NULL,
    support_budget_capital  NUMERIC(12,2) NOT NULL,
    plan_start_date         DATE          NOT NULL,
    plan_end_date           DATE          NOT NULL,
    lga_code                INTEGER       NOT NULL,
    state                   VARCHAR(3)    NOT NULL,
    created_at              TIMESTAMP     NOT NULL
);
