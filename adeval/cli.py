import typer
import uvicorn
import webbrowser
import os
from .server import app

# Create the Typer app
cli = typer.Typer(help="ADEval - Agent Evaluation System")

@cli.command(name="ui")
def launch_ui(
    port: int = typer.Option(8080, help="Port to run the UI on"),
    host: str = typer.Option("127.0.0.1", help="Host to bind the server to")
):
    """
    Launch the ADEval Web Interface.
    """
    url = f"http://{host}:{port}"
    typer.echo(f"🚀 Starting ADEval UI at {url}")
    typer.echo(f"📂 Data will be stored in: {os.path.join(os.getcwd(), '.adeval')}")
    
    # Auto-open browser
    try:
        webbrowser.open(url)
    except:
        pass
    
    # Run FastAPI
    uvicorn.run(app, host=host, port=port, log_level="info")

@cli.callback()
def main():
    """
    ADEval CLI Tool
    """
    pass

if __name__ == "__main__":
    cli()