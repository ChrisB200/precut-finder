CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS channels (
    id BIGINT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS precuts (
    id BIGINT PRIMARY KEY,
    message_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,

    FOREIGN KEY (channel_id) REFERENCES channels(id)
);

CREATE TABLE IF NOT EXISTS scenes (
    id BIGSERIAL PRIMARY KEY,
    precut_id BIGINT NOT NULL,
    scene_index INTEGER NOT NULL,
    start_time DOUBLE PRECISION NOT NULL,
    end_time DOUBLE PRECISION NOT NULL,

    FOREIGN KEY (precut_id) REFERENCES precuts(id) ON DELETE CASCADE,
    UNIQUE (precut_id, scene_index)
);

CREATE TABLE IF NOT EXISTS frame_embeddings (
    frame_id BIGSERIAL PRIMARY KEY,
    scene_id BIGINT NOT NULL,
    embedding VECTOR(512) NOT NULL,

    FOREIGN KEY (scene_id) REFERENCES scenes(id) ON DELETE CASCADE
);
