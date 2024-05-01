{% if editor_config == 'vim' %}
set wildignore+=*/_server/*
set wildignore+=*/_ssr/*
set wildignore+=*/_static/*
set wildignore+=*/_metadata/*
set path-=*/_server/**
set path-=*/_ssr/**
set path-=*/_static/**
set path-=*/_metadata/**
{% endif %}
