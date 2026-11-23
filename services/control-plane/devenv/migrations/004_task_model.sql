-- Which model runs a task: a complexity rating (mapped to a model per provider by the catalogue),
-- or an explicit model and effort, with the reason the controller or person gave.
ALTER TABLE tasks ADD COLUMN complexity TEXT NOT NULL DEFAULT '';
ALTER TABLE tasks ADD COLUMN model TEXT NOT NULL DEFAULT '';
ALTER TABLE tasks ADD COLUMN effort TEXT NOT NULL DEFAULT '';
ALTER TABLE tasks ADD COLUMN model_reason TEXT NOT NULL DEFAULT '';
