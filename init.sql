-- Initialize database extensions and default data
-- This script runs on first database creation

-- Enable PostGIS extension
CREATE EXTENSION IF NOT EXISTS postgis;

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create default camera models
INSERT INTO camera_models (id, name, focal_length, sensor_width, sensor_height, pixel_size, is_custom)
VALUES 
    (uuid_generate_v4(), 'UltraCam Eagle 4.1', 80.0, 53.4, 40.0, 5.2, false),
    (uuid_generate_v4(), 'Leica DMC III', 92.0, 69.12, 45.88, 3.9, false),
    (uuid_generate_v4(), 'Phase One iXU 1000', 80.0, 53.4, 40.0, 5.2, false),
    (uuid_generate_v4(), 'DJI Phantom 4 RTK', 8.8, 13.2, 8.8, 2.41, false),
    (uuid_generate_v4(), 'DJI Mavic 3 Enterprise', 12.3, 17.3, 13.0, 3.3, false),
    (uuid_generate_v4(), 'Sony A7R IV', 35.0, 35.8, 23.9, 3.76, false)
ON CONFLICT DO NOTHING;

-- Create default organization
INSERT INTO organizations (id, name, quota_storage_gb, quota_projects)
VALUES (uuid_generate_v4(), 'Default Organization', 5000, 500)
ON CONFLICT DO NOTHING;
