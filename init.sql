-- Enable PostGIS extension
CREATE EXTENSION IF NOT EXISTS postgis;

-- Enable UUID extension (for gen_random_uuid in older versions, 
-- though Postgres 13+ builtin is fine)
CREATE EXTENSION IF NOT EXISTS pgcrypto;
