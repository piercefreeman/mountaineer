{% if create_stub_files %}
-- Prefer bootstrapping application schema through Iceaxe with `uv run createdb`.
-- This Docker init file is only here so first-time local development has
-- starter data immediately after `docker compose up`.
CREATE TABLE IF NOT EXISTS detailitem (
    id SERIAL PRIMARY KEY,
    description VARCHAR NOT NULL
);

INSERT INTO detailitem (id, description)
VALUES
    (1, 'Explore the generated Mountaineer app'),
    (2, 'Edit this item from the detail page'),
    (3, 'Add a new item from the home page')
ON CONFLICT (id) DO NOTHING;

SELECT setval(
    pg_get_serial_sequence('detailitem', 'id'),
    (SELECT MAX(id) FROM detailitem)
);
{% else %}
-- No bootstrap data is needed without generated stub MVC files.
{% endif %}
