-- Created by Redgate Data Modeler (https://datamodeler.redgate-platform.com)
-- Last modification date: 2026-09-23 00:08:08.323

-- tables
-- Table: DIM_Class
CREATE TABLE DIM_Class (
    id_class INT,
    code_class INT NOT NULL,
    name_class VARCHAR(100) NOT NULL,
    CONSTRAINT DIM_Class_pk
        PRIMARY KEY (id_class)
);


-- Table: DIM_Degree
CREATE TABLE DIM_Degree (
    id_degree INT,
    code_degree VARCHAR(50) NOT NULL,
    name_degree VARCHAR(100) NOT NULL,

    CONSTRAINT DIM_Degree_pk
        PRIMARY KEY (id_degree)
);


-- Table: DIM_Org
CREATE TABLE DIM_Org (
    id_org INT,
    code_org INT NOT NULL,
    name_org VARCHAR(100) NOT NULL,
    IBGE_code INT NOT NULL,

    CONSTRAINT DIM_Org_pk
        PRIMARY KEY (id_org)
);


-- Table: DIM_Process
CREATE TABLE DIM_Process (
    id_process INT,
    number_process CHAR(20) NOT NULL,
    secrecy_level INT NOT NULL,

    CONSTRAINT DIM_Process_pk
        PRIMARY KEY (id_process)
);


-- Table: DIM_Result
CREATE TABLE DIM_Result (
    id_result INT,
    name_result VARCHAR(20) NOT NULL,

    CONSTRAINT DIM_Result_pk
        PRIMARY KEY (id_result)
);


-- Table: DIM_Subject
CREATE TABLE DIM_Subject (
    id_subject INT,
    code_subject INT NOT NULL,
    name_subject VARCHAR(100) NOT NULL,

    CONSTRAINT DIM_Subject_pk
        PRIMARY KEY (id_subject)
);


-- Table: DIM_Time
CREATE TABLE DIM_Time (
    id_time INT,
    data DATE NOT NULL,
    year INT NOT NULL,
    month INT NOT NULL,
    day INT NOT NULL,
    quarter INT NOT NULL,

    CONSTRAINT DIM_Time_pk
        PRIMARY KEY (id_time)
);


-- ============================================================
-- FACT TABLES
-- ============================================================

-- Table: Fact_Resource
CREATE TABLE Fact_Resource (
    id_resource INT,
    id_class INT,
    id_process INT,
    id_org INT,
    id_degree INT,
    id_time INT,
    id_result INT,
    quant_resource INT NULL,

    CONSTRAINT Fact_Resource_pk
        PRIMARY KEY (
            id_resource,
            id_class,
            id_process,
            id_org,
            id_degree,
            id_time,
            id_result
        )
);


-- Table: Fact_Process_Subject
CREATE TABLE Fact_Process_Subject (
    id_resource INT,
    id_class INT,
    id_process INT,
    id_org INT,
    id_degree INT,
    id_time INT,
    id_result INT,
    id_subject INT,

    CONSTRAINT Fact_Process_Subject_pk
        PRIMARY KEY (
            id_resource,
            id_class,
            id_process,
            id_org,
            id_degree,
            id_time,
            id_result,
            id_subject
        )
);


-- ============================================================
-- FOREIGN KEYS - FACT_RESOURCE
-- ============================================================

-- Fact_Resource -> DIM_Class
ALTER TABLE Fact_Resource
ADD CONSTRAINT Fact_Resource_DIM_Class
    FOREIGN KEY (id_class)
    REFERENCES DIM_Class (id_class)
    NOT DEFERRABLE
    INITIALLY IMMEDIATE;


-- Fact_Resource -> DIM_Degree
ALTER TABLE Fact_Resource
ADD CONSTRAINT Fact_Resource_DIM_Degree
    FOREIGN KEY (id_degree)
    REFERENCES DIM_Degree (id_degree)
    NOT DEFERRABLE
    INITIALLY IMMEDIATE;


-- Fact_Resource -> DIM_Org
ALTER TABLE Fact_Resource
ADD CONSTRAINT Fact_Resource_DIM_Org
    FOREIGN KEY (id_org)
    REFERENCES DIM_Org (id_org)
    NOT DEFERRABLE
    INITIALLY IMMEDIATE;


-- Fact_Resource -> DIM_Process
ALTER TABLE Fact_Resource
ADD CONSTRAINT Fact_Resource_DIM_Process
    FOREIGN KEY (id_process)
    REFERENCES DIM_Process (id_process)
    NOT DEFERRABLE
    INITIALLY IMMEDIATE;


-- Fact_Resource -> DIM_Result
ALTER TABLE Fact_Resource
ADD CONSTRAINT Fact_Resource_DIM_Result
    FOREIGN KEY (id_result)
    REFERENCES DIM_Result (id_result)
    NOT DEFERRABLE
    INITIALLY IMMEDIATE;


-- Fact_Resource -> DIM_Time
ALTER TABLE Fact_Resource
ADD CONSTRAINT Fact_Resource_DIM_Time
    FOREIGN KEY (id_time)
    REFERENCES DIM_Time (id_time)
    NOT DEFERRABLE
    INITIALLY IMMEDIATE;


-- ============================================================
-- FOREIGN KEYS - FACT_PROCESS_SUBJECT
-- ============================================================

-- Fact_Process_Subject -> DIM_Class
ALTER TABLE Fact_Process_Subject
ADD CONSTRAINT Fact_Process_Subject_DIM_Class
    FOREIGN KEY (id_class)
    REFERENCES DIM_Class (id_class)
    NOT DEFERRABLE
    INITIALLY IMMEDIATE;


-- Fact_Process_Subject -> DIM_Degree
ALTER TABLE Fact_Process_Subject
ADD CONSTRAINT Fact_Process_Subject_DIM_Degree
    FOREIGN KEY (id_degree)
    REFERENCES DIM_Degree (id_degree)
    NOT DEFERRABLE
    INITIALLY IMMEDIATE;


-- Fact_Process_Subject -> DIM_Org
ALTER TABLE Fact_Process_Subject
ADD CONSTRAINT Fact_Process_Subject_DIM_Org
    FOREIGN KEY (id_org)
    REFERENCES DIM_Org (id_org)
    NOT DEFERRABLE
    INITIALLY IMMEDIATE;


-- Fact_Process_Subject -> DIM_Process
ALTER TABLE Fact_Process_Subject
ADD CONSTRAINT Fact_Process_Subject_DIM_Process
    FOREIGN KEY (id_process)
    REFERENCES DIM_Process (id_process)
    NOT DEFERRABLE
    INITIALLY IMMEDIATE;


-- Fact_Process_Subject -> DIM_Result
ALTER TABLE Fact_Process_Subject
ADD CONSTRAINT Fact_Process_Subject_DIM_Result
    FOREIGN KEY (id_result)
    REFERENCES DIM_Result (id_result)
    NOT DEFERRABLE
    INITIALLY IMMEDIATE;


-- Fact_Process_Subject -> DIM_Time
ALTER TABLE Fact_Process_Subject
ADD CONSTRAINT Fact_Process_Subject_DIM_Time
    FOREIGN KEY (id_time)
    REFERENCES DIM_Time (id_time)
    NOT DEFERRABLE
    INITIALLY IMMEDIATE;


-- Fact_Process_Subject -> DIM_Subject
ALTER TABLE Fact_Process_Subject
ADD CONSTRAINT Fact_Process_Subject_DIM_Subject
    FOREIGN KEY (id_subject)
    REFERENCES DIM_Subject (id_subject)
    NOT DEFERRABLE
    INITIALLY IMMEDIATE;

-- End of file.