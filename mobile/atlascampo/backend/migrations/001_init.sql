CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS app_users (
  id UUID PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS projects (
  id UUID PRIMARY KEY,
  owner_id UUID NOT NULL REFERENCES app_users(id),
  name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS project_members (
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('owner', 'editor', 'viewer')),
  PRIMARY KEY (project_id, user_id)
);

CREATE TABLE IF NOT EXISTS maps (
  id UUID PRIMARY KEY,
  project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
  owner_id UUID NOT NULL REFERENCES app_users(id),
  name TEXT NOT NULL,
  source_format TEXT NOT NULL,
  object_key TEXT NOT NULL,
  manifest JSONB NOT NULL DEFAULT '{}',
  ingest_state TEXT NOT NULL CHECK (ingest_state IN ('queued', 'processing', 'ready', 'failed')),
  checksum_sha256 TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS layers (
  id UUID PRIMARY KEY,
  project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
  map_id UUID REFERENCES maps(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  style JSONB NOT NULL DEFAULT '{}',
  revision BIGINT NOT NULL DEFAULT 1,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS features (
  id UUID PRIMARY KEY,
  layer_id UUID NOT NULL REFERENCES layers(id) ON DELETE CASCADE,
  project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
  geometry geometry(Geometry, 4326) NOT NULL,
  properties JSONB NOT NULL DEFAULT '{}',
  revision BIGINT NOT NULL DEFAULT 1,
  updated_by UUID NOT NULL REFERENCES app_users(id),
  deleted_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS features_geometry_gix ON features USING GIST (geometry);
CREATE INDEX IF NOT EXISTS features_project_revision_idx ON features(project_id, revision);

CREATE TABLE IF NOT EXISTS sync_operations (
  operation_id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES app_users(id),
  entity TEXT NOT NULL,
  entity_id UUID NOT NULL,
  applied_revision BIGINT NOT NULL,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sync_changes (
  sequence BIGSERIAL PRIMARY KEY,
  entity TEXT NOT NULL,
  entity_id UUID NOT NULL,
  revision BIGINT NOT NULL,
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
