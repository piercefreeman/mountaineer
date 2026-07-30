#[tokio::main]
async fn main() {
    if let Err(error) =
        mountaineer_coordinator::run_from_args(mountaineer_coordinator::RuntimeMode::Development)
            .await
    {
        mountaineer_coordinator::report_error("mountaineer-dev", error.as_ref());
        std::process::exit(1);
    }
}
