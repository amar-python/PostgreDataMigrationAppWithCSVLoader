CREATE TABLE users (
    id             INTEGER       PRIMARY KEY,
    email          VARCHAR(255)  NOT NULL UNIQUE,
    full_name      VARCHAR(200)  NOT NULL,
    signup_date    DATE          NOT NULL,
    country        VARCHAR(2),
    lifetime_value NUMERIC(12,2)
);
