{% if create_stub_files %}
-- Application schema and starter rows are created by the generated `createdb`
-- command. Keep Docker init empty so Postgres startup does not race Iceaxe
-- schema creation.
{% else %}
-- No bootstrap data is needed without generated stub MVC files.
{% endif %}
