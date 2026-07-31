use crate::cli::{
    invalid,
    output::{status, Tone},
    Result,
};
use std::{
    net::{Ipv4Addr, SocketAddr},
    sync::Arc,
    time::Duration,
};
use tokio::{
    io::{copy_bidirectional, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    sync::RwLock,
    time::{sleep, Instant},
};

pub(super) async fn wait_until_ready(address: SocketAddr, wait: Duration) -> Result<()> {
    let deadline = Instant::now() + wait;
    loop {
        if TcpStream::connect(address).await.is_ok() {
            return Ok(());
        }
        if Instant::now() >= deadline {
            return Err(invalid(format!(
                "timed out waiting for backend at {address}"
            )));
        }
        sleep(Duration::from_millis(50)).await;
    }
}

pub(super) async fn serve_proxy(
    listener: TcpListener,
    active_target: Arc<RwLock<Option<SocketAddr>>>,
) -> Result<()> {
    loop {
        let (mut inbound, _) = listener.accept().await?;
        let target = *active_target.read().await;
        tokio::spawn(async move {
            let Some(target) = target else {
                let _ = inbound
                    .write_all(
                        b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 23\r\n\r\nBackend is starting up.",
                    )
                    .await;
                return;
            };
            match TcpStream::connect(target).await {
                Ok(mut outbound) => {
                    let _ = copy_bidirectional(&mut inbound, &mut outbound).await;
                }
                Err(error) => status(
                    Tone::Warning,
                    "Warning",
                    format!("backend proxy connection failed: {error}"),
                ),
            }
        });
    }
}

pub(super) fn reserve_loopback_port() -> Result<u16> {
    // ponytail: a short bind/drop race is acceptable; pass an open socket to
    // Python if real-world collisions make this observable.
    Ok(std::net::TcpListener::bind((Ipv4Addr::LOCALHOST, 0))?
        .local_addr()?
        .port())
}
