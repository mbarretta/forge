"""
Plugin registry for discovering and managing Gauge plugins.

Handles plugin discovery from the plugins/ directory and external
plugins from ~/.gauge/plugins/, providing command routing to the
appropriate plugin handlers.
"""

import importlib
import importlib.util
import logging
import pkgutil
import sys
from pathlib import Path
from typing import Optional

from forge_gauge.core.command_plugin import CommandDefinition, GaugePlugin

logger = logging.getLogger(__name__)

# External plugins directory
EXTERNAL_PLUGINS_DIR = Path.home() / ".gauge" / "plugins"


class PluginRegistry:
    """Discovers and manages plugins and their commands.

    The registry handles:
    - Auto-discovery of plugins from the plugins/ directory
    - Registration of plugins and their commands
    - Command lookup and routing
    """

    def __init__(self) -> None:
        self._plugins: dict[str, GaugePlugin] = {}
        self._commands: dict[str, tuple[GaugePlugin, CommandDefinition]] = {}

    def register(self, plugin: GaugePlugin) -> None:
        """Register a plugin and all its commands.

        Args:
            plugin: The plugin instance to register

        Raises:
            ValueError: If plugin name or command names conflict with existing registrations
        """
        if plugin.name in self._plugins:
            raise ValueError(f"Plugin '{plugin.name}' is already registered")

        if not plugin.is_available():
            logger.warning(f"Plugin '{plugin.name}' is not available (missing dependencies)")
            return

        self._plugins[plugin.name] = plugin

        for cmd in plugin.get_commands():
            if cmd.name in self._commands:
                existing_plugin = self._commands[cmd.name][0]
                raise ValueError(
                    f"Command '{cmd.name}' from plugin '{plugin.name}' "
                    f"conflicts with existing command from plugin '{existing_plugin.name}'"
                )
            self._commands[cmd.name] = (plugin, cmd)
            logger.debug(f"Registered command '{cmd.name}' from plugin '{plugin.name}'")

        logger.debug(f"Registered plugin '{plugin.name}' v{plugin.version}")

    def get_command(self, name: str) -> Optional[CommandDefinition]:
        """Get command definition by name.

        Args:
            name: The command name to look up

        Returns:
            CommandDefinition if found, None otherwise
        """
        if name in self._commands:
            return self._commands[name][1]
        return None

    def get_plugin_for_command(self, name: str) -> Optional[GaugePlugin]:
        """Get the plugin that provides a command.

        Args:
            name: The command name to look up

        Returns:
            GaugePlugin that provides the command, None if not found
        """
        if name in self._commands:
            return self._commands[name][0]
        return None

    def list_commands(self) -> list[str]:
        """List all available command names.

        Returns:
            Sorted list of registered command names
        """
        return sorted(self._commands.keys())

    def list_plugins(self) -> list[str]:
        """List all registered plugin names.

        Returns:
            Sorted list of registered plugin names
        """
        return sorted(self._plugins.keys())

    def get_plugin(self, name: str) -> Optional[GaugePlugin]:
        """Get a plugin by name.

        Args:
            name: The plugin name to look up

        Returns:
            GaugePlugin if found, None otherwise
        """
        return self._plugins.get(name)

    def get_all_commands(self) -> list[tuple[str, CommandDefinition, GaugePlugin]]:
        """Get all registered commands with their plugins.

        Returns:
            List of tuples (command_name, command_definition, plugin)
        """
        return [
            (name, cmd, plugin)
            for name, (plugin, cmd) in sorted(self._commands.items())
        ]

    def discover_plugins(self) -> None:
        """Auto-discover and register plugins from the plugins/ directory.

        Searches for Python packages in src/plugins/ that export a
        GaugePlugin subclass via their __init__.py or plugin.py module.
        """
        plugin_names = self._discover_plugin_names()

        for modname in plugin_names:
            try:
                plugin_module = importlib.import_module(f"plugins.{modname}")

                plugin_instance = None

                if hasattr(plugin_module, "get_plugin"):
                    plugin_instance = plugin_module.get_plugin()
                elif hasattr(plugin_module, "Plugin"):
                    plugin_instance = plugin_module.Plugin()

                if plugin_instance is not None and isinstance(plugin_instance, GaugePlugin):
                    self.register(plugin_instance)
                else:
                    logger.debug(
                        f"Plugin package '{modname}' does not export a GaugePlugin "
                        "(missing get_plugin() or Plugin class)"
                    )

            except Exception as e:
                logger.warning(f"Failed to load plugin '{modname}': {e}")

    def _discover_plugin_names(self) -> list[str]:
        """Discover plugin package names from the filesystem (non-frozen only)."""
        plugins_dir = Path(__file__).parent.parent / "plugins"

        if not plugins_dir.exists():
            logger.debug(f"Plugins directory does not exist: {plugins_dir}")
            return []

        logger.debug(f"Discovering plugins from: {plugins_dir}")

        try:
            import plugins
        except ImportError:
            logger.debug("Could not import plugins package")
            return []

        return [
            modname
            for _importer, modname, ispkg in pkgutil.iter_modules(plugins.__path__)
            if ispkg
        ]

    def discover_external_plugins(self) -> None:
        """Discover and register plugins from ~/.gauge/plugins/ directory.

        External plugins are installed by users from GitHub repositories
        using 'gauge plugin install'. Each plugin may have its own
        virtualenv with isolated dependencies.
        """
        if not EXTERNAL_PLUGINS_DIR.exists():
            logger.debug(f"External plugins directory does not exist: {EXTERNAL_PLUGINS_DIR}")
            return

        logger.debug(f"Discovering external plugins from: {EXTERNAL_PLUGINS_DIR}")

        for plugin_dir in EXTERNAL_PLUGINS_DIR.iterdir():
            if not plugin_dir.is_dir():
                continue

            # Skip hidden directories and __pycache__
            if plugin_dir.name.startswith(".") or plugin_dir.name == "__pycache__":
                continue

            try:
                self._load_external_plugin(plugin_dir)
            except Exception as e:
                logger.warning(f"Failed to load external plugin '{plugin_dir.name}': {e}")

    def _load_external_plugin(self, plugin_dir: Path) -> None:
        """Load a single external plugin from its directory.

        Args:
            plugin_dir: Path to the plugin directory
        """
        plugin_name = plugin_dir.name

        # Add plugin's venv site-packages to sys.path if it exists
        venv_site_packages = self._get_venv_site_packages(plugin_dir)
        if venv_site_packages and venv_site_packages.exists():
            if str(venv_site_packages) not in sys.path:
                sys.path.insert(0, str(venv_site_packages))
                logger.debug(f"Added venv site-packages to path: {venv_site_packages}")

        # Add plugin directory to sys.path
        if str(plugin_dir) not in sys.path:
            sys.path.insert(0, str(plugin_dir))

        # Try to load the plugin module
        init_file = plugin_dir / "__init__.py"
        plugin_file = plugin_dir / "plugin.py"

        module = None
        module_name = f"external_plugin_{plugin_name.replace('-', '_')}"

        if init_file.exists():
            # Load via __init__.py
            spec = importlib.util.spec_from_file_location(module_name, init_file)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
        elif plugin_file.exists():
            # Load via plugin.py directly
            spec = importlib.util.spec_from_file_location(module_name, plugin_file)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)

        if not module:
            logger.warning(
                f"External plugin '{plugin_name}' has no __init__.py or plugin.py"
            )
            return

        # Get plugin instance
        plugin_instance = None

        if hasattr(module, "get_plugin"):
            plugin_instance = module.get_plugin()
        elif hasattr(module, "Plugin"):
            plugin_instance = module.Plugin()

        if plugin_instance is not None and isinstance(plugin_instance, GaugePlugin):
            self.register(plugin_instance)
            logger.info(f"Loaded external plugin: {plugin_instance.name} v{plugin_instance.version}")
        else:
            logger.warning(
                f"External plugin '{plugin_name}' does not export a valid "
                "GaugePlugin (missing get_plugin() or Plugin class)"
            )

    def _get_venv_site_packages(self, plugin_dir: Path) -> Optional[Path]:
        """Get the site-packages path for a plugin's virtualenv."""
        venv_path = plugin_dir / ".venv"
        if not venv_path.exists():
            return None

        # Handle platform differences
        if sys.platform == "win32":
            site_packages = venv_path / "Lib" / "site-packages"
            if site_packages.exists():
                return site_packages
        else:
            # Unix-like: look for python* directory
            lib_path = venv_path / "lib"
            if lib_path.exists():
                for py_dir in lib_path.iterdir():
                    if py_dir.name.startswith("python"):
                        site_packages = py_dir / "site-packages"
                        if site_packages.exists():
                            return site_packages

        return None
