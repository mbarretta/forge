"""
Plugin architecture for Gauge CLI commands.

Provides base classes for creating plugins that can contribute
one or more CLI commands to Gauge.
"""

from abc import ABC, abstractmethod
from argparse import ArgumentParser, Namespace
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class CommandDefinition:
    """Defines a CLI command provided by a plugin.

    Attributes:
        name: Command name as used on CLI (e.g., 'scan', 'match')
        description: Help text shown in CLI help output
        configure_parser: Function that adds arguments to the command's parser
        execute: Function that runs the command and returns exit code
    """

    name: str
    description: str
    configure_parser: Callable[[ArgumentParser], None]
    execute: Callable[[Namespace], int]


class GaugePlugin(ABC):
    """Base class for Gauge plugins.

    A plugin can provide one or more CLI commands that share
    code and resources within the plugin module.

    Example:
        class MyPlugin(GaugePlugin):
            @property
            def name(self) -> str:
                return "my-plugin"

            @property
            def version(self) -> str:
                return "1.0.0"

            @property
            def description(self) -> str:
                return "My custom plugin"

            def get_commands(self) -> list[CommandDefinition]:
                return [
                    CommandDefinition(
                        name="mycommand",
                        description="Does something useful",
                        configure_parser=configure_my_parser,
                        execute=execute_my_command,
                    ),
                ]
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Plugin name (e.g., 'gauge-core', 'dhi-compete')."""
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        """Plugin version string."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable plugin description."""
        ...

    @abstractmethod
    def get_commands(self) -> list[CommandDefinition]:
        """Return list of commands this plugin provides.

        Returns:
            List of CommandDefinition objects for each command
            the plugin contributes to the CLI.
        """
        ...

    def is_available(self) -> bool:
        """Check if plugin dependencies are available.

        Override this method to check for required external
        dependencies (binaries, Python packages, etc.).

        Returns:
            True if all dependencies are available, False otherwise.
        """
        return True
