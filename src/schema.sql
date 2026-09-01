CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS channels (
    id BIGINT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS indexed_precuts (
    id BIGSERIAL PRIMARY KEY,
    content_hash TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS precut_posts (
    attachment_id BIGINT PRIMARY KEY,
    indexed_precut_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,

    FOREIGN KEY (indexed_precut_id) REFERENCES indexed_precuts(id) ON DELETE CASCADE,
    FOREIGN KEY (channel_id) REFERENCES channels(id)
);

CREATE TABLE IF NOT EXISTS scenes (
    id BIGSERIAL PRIMARY KEY,
    indexed_precut_id BIGINT NOT NULL,
    scene_index INTEGER NOT NULL,
    start_time DOUBLE PRECISION NOT NULL,
    end_time DOUBLE PRECISION NOT NULL,
    preview_path TEXT,

    FOREIGN KEY (indexed_precut_id) REFERENCES indexed_precuts(id) ON DELETE CASCADE,
    UNIQUE (indexed_precut_id, scene_index)
);

CREATE TABLE IF NOT EXISTS frame_embeddings (
    frame_id BIGSERIAL PRIMARY KEY,
    scene_id BIGINT NOT NULL,
    embedding VECTOR(512) NOT NULL,

    FOREIGN KEY (scene_id) REFERENCES scenes(id) ON DELETE CASCADE
);
