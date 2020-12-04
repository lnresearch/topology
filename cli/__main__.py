import click
from cli.timemachine import timemachine


@click.group()
def cli():
    pass


cli.add_command(timemachine)

if __name__ == "__main__":
    cli()
