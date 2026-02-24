use crate::ClawdbotCommands;
use anyhow::{bail, Context, Result};
use std::process::Command;

fn script_path() -> std::path::PathBuf {
    std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join(".clawdbot")
        .join("scripts")
        .join("clawdbot")
}

pub fn handle_command(command: ClawdbotCommands) -> Result<()> {
    let script = script_path();
    if !script.exists() {
        bail!(
            "clawdbot script not found at {}. Ensure .clawdbot/scripts/clawdbot exists.",
            script.display()
        );
    }

    let mut args: Vec<String> = Vec::new();
    match command {
        ClawdbotCommands::Create {
            task_id,
            description,
            agent,
        } => {
            args.push("create".into());
            args.push(task_id);
            args.push(description);
            if let Some(agent) = agent {
                args.push(agent);
            }
        }
        ClawdbotCommands::Kickoff {
            task_id,
            brief_file,
            agent,
        } => {
            args.push("kickoff".into());
            args.push(task_id);
            args.push(brief_file);
            if let Some(agent) = agent {
                args.push(agent);
            }
        }
        ClawdbotCommands::Spawn { task_id } => {
            args.push("spawn".into());
            args.push(task_id);
        }
        ClawdbotCommands::Check => args.push("check".into()),
        ClawdbotCommands::Status { task_id } => {
            args.push("status".into());
            if let Some(task_id) = task_id {
                args.push(task_id);
            }
        }
        ClawdbotCommands::Validate => args.push("validate".into()),
    }

    let status = Command::new(&script)
        .args(args)
        .status()
        .with_context(|| format!("failed to run {}", script.display()))?;

    if !status.success() {
        bail!("clawdbot command failed with status: {status}");
    }

    Ok(())
}
