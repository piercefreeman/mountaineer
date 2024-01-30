use ssr_rs::Ssr;
use std::fs::read_to_string;

fn main() {
    let source = read_to_string("../my_website/my_website/views/_ssr/home_controller.js").unwrap();

    let html = Ssr::render_to_string(&source, "SSR", None);

    assert_eq!(html, "<!doctype html><html>...</html>".to_string());
}
