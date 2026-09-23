"""Installed plugin discovery and the initial adapter conformance kit."""

from caddsuite.plugins.registry import (
    AdapterPlugin,
    AdapterRegistration,
    PluginDiscoveryError,
    PluginRegistry,
    PluginSnapshot,
    RegisteredAdapter,
    adapter_conformance_issues,
)

__all__ = [
    "AdapterPlugin",
    "AdapterRegistration",
    "PluginDiscoveryError",
    "PluginRegistry",
    "PluginSnapshot",
    "RegisteredAdapter",
    "adapter_conformance_issues",
]
