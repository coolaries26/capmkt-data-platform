CREATE ROLE capmkt WITH LOGIN PASSWORD 'change_me';
CREATE DATABASE capmkt       OWNER capmkt;
CREATE DATABASE airflow_meta OWNER capmkt;   -- Airflow's own metadata DB
