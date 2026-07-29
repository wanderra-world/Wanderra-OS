CREATE ROLE {{RUNTIME_ROLE}} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;

CREATE SCHEMA {{SCHEMA}};

CREATE TABLE {{SCHEMA}}.workspaces (
    id UUID PRIMARY KEY,
    cell_id TEXT NOT NULL
);

CREATE TABLE {{SCHEMA}}.projects (
    workspace_id UUID NOT NULL REFERENCES {{SCHEMA}}.workspaces (id),
    id UUID NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY (workspace_id, id)
);

CREATE TABLE {{SCHEMA}}.tasks (
    workspace_id UUID NOT NULL REFERENCES {{SCHEMA}}.workspaces (id),
    id UUID NOT NULL,
    project_id UUID NOT NULL,
    title TEXT NOT NULL,
    PRIMARY KEY (workspace_id, id),
    CONSTRAINT tasks_project_fk
        FOREIGN KEY (workspace_id, project_id)
        REFERENCES {{SCHEMA}}.projects (workspace_id, id)
);

ALTER TABLE {{SCHEMA}}.projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE {{SCHEMA}}.projects FORCE ROW LEVEL SECURITY;
ALTER TABLE {{SCHEMA}}.tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE {{SCHEMA}}.tasks FORCE ROW LEVEL SECURITY;

CREATE POLICY projects_workspace_isolation ON {{SCHEMA}}.projects
    USING (
        workspace_id = NULLIF(current_setting('atlas.workspace_id', TRUE), '')::UUID
    )
    WITH CHECK (
        workspace_id = NULLIF(current_setting('atlas.workspace_id', TRUE), '')::UUID
    );

CREATE POLICY tasks_workspace_isolation ON {{SCHEMA}}.tasks
    USING (
        workspace_id = NULLIF(current_setting('atlas.workspace_id', TRUE), '')::UUID
    )
    WITH CHECK (
        workspace_id = NULLIF(current_setting('atlas.workspace_id', TRUE), '')::UUID
    );

GRANT USAGE ON SCHEMA {{SCHEMA}} TO {{RUNTIME_ROLE}};
GRANT SELECT, INSERT, UPDATE, DELETE ON
    {{SCHEMA}}.projects,
    {{SCHEMA}}.tasks
TO {{RUNTIME_ROLE}};
