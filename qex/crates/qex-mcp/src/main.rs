mod config;
mod server;
mod tools;

use anyhow::Result;
use clap::Parser;
use config::CliArgs;
use rmcp::ServiceExt;
use server::QexServer;
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> Result<()> {
    let args = CliArgs::parse();

    // Initialize logging to stderr (stdout is reserved for MCP JSON-RPC)
    let env_filter = if args.verbose {
        EnvFilter::new("debug")
    } else {
        EnvFilter::from_default_env().add_directive(tracing::Level::INFO.into())
    };

    tracing_subscriber::fmt()
        .with_env_filter(env_filter)
        .with_writer(std::io::stderr)
        .with_ansi(false)
        .init();

    tracing::info!("Starting qex MCP server v{}", env!("CARGO_PKG_VERSION"));

    let service = QexServer::new()
        .serve(rmcp::transport::stdio())
        .await
        .inspect_err(|e| {
            tracing::error!("Server error: {:?}", e);
        })?;

    service.waiting().await?;

    tracing::info!("Server shut down");
    Ok(())
}
