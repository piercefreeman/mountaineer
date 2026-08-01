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
    io::{copy_bidirectional, AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    sync::RwLock,
    time::{sleep, Instant},
};

pub(super) const VITE_PROXY_PREFIX: &str = "/__mountaineer__/";

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
    vite_target: SocketAddr,
) -> Result<()> {
    loop {
        let (inbound, _) = listener.accept().await?;
        let active_target = active_target.clone();
        tokio::spawn(async move {
            if let Err(error) = proxy_connection(inbound, active_target, vite_target).await {
                status(
                    Tone::Warning,
                    "Warning",
                    format!("development proxy connection failed: {error}"),
                );
            }
        });
    }
}

async fn proxy_connection(
    mut inbound: TcpStream,
    active_target: Arc<RwLock<Option<SocketAddr>>>,
    vite_target: SocketAddr,
) -> std::io::Result<()> {
    let mut request = Vec::with_capacity(1024);
    let mut chunk = [0_u8; 1024];
    while !request.windows(4).any(|window| window == b"\r\n\r\n") && request.len() < 65536 {
        let read = inbound.read(&mut chunk).await?;
        if read == 0 {
            return Ok(());
        }
        request.extend_from_slice(&chunk[..read]);
    }

    let vite_request = is_vite_request(&request);
    let target = if vite_request {
        Some(vite_target)
    } else {
        *active_target.read().await
    };
    let Some(target) = target else {
        inbound
            .write_all(
                b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 23\r\n\r\nBackend is starting up.",
            )
            .await?;
        return Ok(());
    };

    let mut outbound = TcpStream::connect(target).await?;
    if vite_request {
        rewrite_host(&mut request, vite_target);
    }
    if !is_websocket_upgrade(&request) {
        close_after_response(&mut request);
    }
    outbound.write_all(&request).await?;
    copy_bidirectional(&mut inbound, &mut outbound).await?;
    Ok(())
}

fn rewrite_host(request: &mut Vec<u8>, host: SocketAddr) {
    let Some(host_start) = request
        .windows(b"\r\nhost:".len())
        .position(|window| window.eq_ignore_ascii_case(b"\r\nhost:"))
        .map(|position| position + 2)
    else {
        return;
    };
    let Some(host_end) = request[host_start..]
        .windows(2)
        .position(|window| window == b"\r\n")
        .map(|position| host_start + position)
    else {
        return;
    };
    request.splice(host_start..host_end, format!("Host: {host}").bytes());
}

fn is_websocket_upgrade(request: &[u8]) -> bool {
    std::str::from_utf8(request)
        .is_ok_and(|request| request.to_ascii_lowercase().contains("upgrade: websocket"))
}

fn close_after_response(request: &mut Vec<u8>) {
    if let Some(headers_end) = request.windows(4).position(|window| window == b"\r\n\r\n") {
        request.splice(
            headers_end..headers_end,
            b"\r\nConnection: close".iter().copied(),
        );
    }
}

fn is_vite_request(request: &[u8]) -> bool {
    let Some(line_end) = request.iter().position(|byte| *byte == b'\n') else {
        return false;
    };
    let Ok(request_line) = std::str::from_utf8(&request[..line_end]) else {
        return false;
    };
    request_line
        .split_ascii_whitespace()
        .nth(1)
        .is_some_and(|path| path.starts_with(VITE_PROXY_PREFIX))
}

pub(super) fn reserve_loopback_port() -> Result<u16> {
    // ponytail: a short bind/drop race is acceptable; pass an open socket to
    // Python if real-world collisions make this observable.
    Ok(std::net::TcpListener::bind((Ipv4Addr::LOCALHOST, 0))?
        .local_addr()?
        .port())
}
