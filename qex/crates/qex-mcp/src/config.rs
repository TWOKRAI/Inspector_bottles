use clap::Parser;

/// qex: Lightweight semantic code search MCP server
#[derive(Parser, Debug)]
#[command(version, about, long_about = None)]
pub struct CliArgs {
    /// Enable verbose debug logging
    #[arg(short, long)]
    pub verbose: bool,
}
