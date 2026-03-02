import typer
import uvicorn
import webbrowser
import os
import json
from .server import app
from .core import (
    BASE_DIR, list_experiments, get_experiment, run_single_test, 
    delete_experiment_data, EvalRequest, save_experiment_data
)

# Create the Typer app
cli = typer.Typer(
    help="🤖 [bold cyan]ADEval - Agent Evaluation System for Google ADK[/bold cyan]",
    rich_markup_mode="rich"
)

@cli.command(name="ui")
def launch_ui(
    port: int = typer.Option(8080, "--port", "-p", help="Port to run the UI on"),
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host to bind the server to")
):
    """
    🚀 [bold green]Launch the ADEval Web Interface.[/bold green]
    
    Starts a FastAPI server and opens the browser to the evaluation dashboard.
    Default: http://127.0.0.1:8080
    """
    url = f"http://{host}:{port}"
    typer.secho(f"🚀 Starting ADEval UI at {url}", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"📂 Data directory: {os.path.join(BASE_DIR, '.adeval')}")
    
    try:
        webbrowser.open(url)
    except:
        pass
    
    uvicorn.run(app, host=host, port=port, log_level="info")

@cli.command(name="list")
def list_exps():
    """
    📋 [bold blue]List all stored experiments.[/bold blue]
    
    Displays a summary table of all experiments found in local storage.
    """
    exps = list_experiments()
    if not exps:
        typer.echo("No experiments found. Create one via the UI first.")
        return
    
    header = f"{'ID':<20} {'Name':<40} {'Cases':<8}"
    typer.secho(header, fg=typer.colors.MAGENTA, bold=True)
    typer.echo("-" * len(header))
    for exp in exps:
        case_count = len(exp.get('testCases', []))
        typer.echo(f"{exp['id']:<20} {exp['name']:<40} {case_count:<8}")

@cli.command(name="run")
def run_exp(
    exp_id: str = typer.Argument(..., help="The ID of the experiment to run (e.g., exp_xxxxxx)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show full raw response on failure")
):
    """
    ▶️  [bold yellow]Run a specific experiment by ID.[/bold yellow]
    
    Executes all test cases against the Agent API and displays results with a [bold]final summary[/bold].
    """
    exp = get_experiment(exp_id)
    if not exp:
        typer.secho(f"❌ Error: Experiment '{exp_id}' not found.", fg=typer.colors.RED, bold=True)
        raise typer.Exit(code=1)
    
    typer.secho(f"▶️  Running Experiment: {exp.name} ({exp.id})", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"🔗 API URL: {exp.apiUrl}")
    typer.echo("=" * 60)
    
    total = len(exp.testCases)
    passed = 0
    
    for i, case in enumerate(exp.testCases):
        typer.echo(f"[{i+1}/{total}] Q: {case.q}")
        
        req = EvalRequest(
            app_name=case.appName,
            api_url=exp.apiUrl,
            user_id=exp.userId,
            question=case.q,
            state=case.state
        )
        
        result = run_single_test(req)
        
        actual_tools = result.get("tools", "")
        actual_answer = result.get("answer", "")
        
        case.actualTools = actual_tools
        case.actualAnswer = actual_answer
        case.rawResponse = result.get("raw_response")
        
        # Tools comparison
        expected_tools = [t.strip() for t in case.expectedTools.split("\n") if t.strip()]
        actual_tools_list = [t.strip() for t in actual_tools.split("\n") if t.strip()]
        
        tools_match = set(expected_tools) == set(actual_tools_list)
        
        if tools_match:
            typer.secho("  ✅ Tools Match", fg=typer.colors.GREEN)
            passed += 1
        else:
            typer.secho(f"  ❌ Tools Mismatch", fg=typer.colors.RED)
            typer.echo(f"     Expected: {expected_tools}")
            typer.echo(f"     Actual:   {actual_tools_list}")
        
        typer.echo(f"  A: {actual_answer[:100]}..." if len(actual_answer) > 100 else f"  A: {actual_answer}")
        
        if verbose and not tools_match:
             typer.echo(f"     Raw Response: {json.dumps(result.get('raw_response'), indent=2, ensure_ascii=False)}")
             
        typer.echo("-" * 40)
    
    # Save results
    save_experiment_data(exp)
    
    # --- Statistics Summary ---
    typer.echo("\n" + "=" * 60)
    typer.secho("📊 EXPERIMENT SUMMARY", fg=typer.colors.MAGENTA, bold=True)
    typer.echo("-" * 60)
    typer.echo(f"Experiment ID:   {exp.id}")
    typer.echo(f"Total Cases:     {total}")
    
    color = typer.colors.GREEN if passed == total else typer.colors.YELLOW
    if passed == 0: color = typer.colors.RED
    
    typer.secho(f"Passed Cases:    {passed}", fg=color, bold=True)
    typer.secho(f"Failed Cases:    {total - passed}", fg=typer.colors.RED if (total - passed) > 0 else typer.colors.WHITE)
    
    pass_rate = (passed / total) * 100 if total > 0 else 0
    typer.secho(f"Pass Rate:       {pass_rate:.2f}%", fg=color, bold=True, reverse=True)
    typer.echo("=" * 60)
    
    typer.echo("✅ Results saved to local storage.")

@cli.command(name="delete")
def delete_exp(
    exp_id: str = typer.Argument(..., help="The ID of the experiment to delete")
):
    """
    🗑️  [bold red]Delete an experiment.[/bold red]
    
    Permanently removes the experiment JSON file. [red]Action cannot be undone.[/red]
    """
    if delete_experiment_data(exp_id):
        typer.secho(f"🗑️ Deleted experiment: {exp_id}", fg=typer.colors.GREEN)
    else:
        typer.secho(f"❌ Error: Experiment '{exp_id}' not found.", fg=typer.colors.RED)

@cli.callback()
def main():
    """
    🤖 **ADEval CLI Tool** - Agent Evaluation System for Google ADK.
    
    Use this tool to manage and run evaluation experiments for your AI Agents.
    Supports Web UI and direct CLI execution.
    """
    pass

if __name__ == "__main__":
    cli()
