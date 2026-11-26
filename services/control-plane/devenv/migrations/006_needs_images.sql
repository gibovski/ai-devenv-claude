-- Tasks that need generated images run only on OpenAI Codex agents (Claude agents cannot generate images).
ALTER TABLE tasks ADD COLUMN needs_images INTEGER NOT NULL DEFAULT 0;
