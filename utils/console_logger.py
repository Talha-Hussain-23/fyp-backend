"""
Professional Console Logger for SmartHiring Backend
Uses Rich library for beautiful, colorful terminal output
Works alongside structlog for dual-output (JSON + Console)
"""

import os
import sys
from datetime import datetime
from typing import Optional, Dict, Any, List
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

# Detect Unicode Support
try:
    "✓".encode(sys.stdout.encoding or 'ascii')
    UNICODE_SUPPORT = True
except (UnicodeEncodeError, TypeError):
    UNICODE_SUPPORT = False

class ConsoleLogger:
    """Beautiful console logger with Rich formatting"""
    
    @property
    def console(self):
        """Lazy initialization of console"""
        if self._console is None and self.enabled:
            self._console = Console()
        return self._console

    def __init__(self, enabled: bool = True):
        self.enabled = enabled and os.getenv("RICH_CONSOLE", "true").lower() != "false"
        self._console = None
    
    def _safe_emoji(self, emoji: str, fallback: str = "") -> str:
        return emoji if UNICODE_SUPPORT else fallback

    def print_banner(self, title: str, subtitle: Optional[str] = None, info: Optional[Dict[str, str]] = None, emoji: str = "🚀"):
        if not self.console: return
        safe_emoji = self._safe_emoji(emoji, "[START]")
        content = f"[bold cyan]{safe_emoji} {title}[/bold cyan]"
        if subtitle: content += f"\n[dim]{subtitle}[/dim]"
        if info:
            content += "\n"
            for key, value in info.items():
                content += f"\n[bold]{key}:[/bold] {value}"
        panel = Panel(content, box=box.DOUBLE, border_style="cyan", padding=(1, 2))
        self.console.print()
        self.console.print(panel)
        self.console.print()
    
    def print_status(self, message: str, status: str = "success", details: Optional[List[str]] = None):
        if not self.enabled: return
        
        symbols = {
            "success": ("✓" if UNICODE_SUPPORT else "[OK]", "green"),
            "error": ("✗" if UNICODE_SUPPORT else "[X]", "red"),
            "warning": ("⚠" if UNICODE_SUPPORT else "[!]", "yellow"),
            "info": ("ℹ" if UNICODE_SUPPORT else "[i]", "blue"),
        }
        symbol, color = symbols.get(status, ("•", "white"))
        self.console.print(f"[{color}]{symbol} {message}[/{color}]")
        if details:
            for detail in details:
                self.console.print(f"    [dim]└─ {detail}[/dim]")

    def print_section(self, title: str, emoji: str = "🔧"):
        if not self.enabled: return
        safe_emoji = self._safe_emoji(emoji, ">>")
        panel = Panel(f"[bold white]{safe_emoji} {title}[/bold white]", box=box.ROUNDED, border_style="blue", padding=(0, 2))
        self.console.print(panel)

    def print_ready(self, urls: Dict[str, str]):
        if not self.enabled: return
        safe_emoji = self._safe_emoji("🎯", "[READY]")
        content = f"[bold green]{safe_emoji} Server Ready![/bold green]\n\n"
        for service, url in urls.items():
            content += f"[bold]{service}:[/bold] [link={url}]{url}[/link]\n"
        panel = Panel(content, box=box.DOUBLE, border_style="green", padding=(1, 2))
        self.console.print(panel)
        self.console.print()
        self.console.print("[dim]Listening for requests...[/dim]")
        self.console.print()

    # Other methods simplified for brevity or kept if needed
    def print_table(self, title: str, columns: List[str], rows: List[List[str]], show_header: bool = True):
        if not self.enabled: return
        table = Table(title=f"[bold]{title}[/bold]", box=box.ROUNDED, show_header=show_header, header_style="bold cyan")
        for col in columns: table.add_column(col)
        for row in rows: table.add_row(*row)
        self.console.print(table)
        self.console.print()

    def print_error(self, error_type: str, message: str, context: Optional[Dict[str, Any]] = None, stack_trace: Optional[str] = None):
        if not self.enabled: return
        safe_emoji = self._safe_emoji("❌", "[ERROR]")
        content = f"[bold red]Error Type:[/bold red] {error_type}\n[bold red]Message:[/bold red]    {message}\n"
        if context:
            content += "\n[bold]Context:[/bold]\n"
            for key, value in context.items(): content += f"  [dim]{key}:[/dim] {value}\n"
        if stack_trace: content += f"\n[dim]{stack_trace[:500]}...[/dim]"
        panel = Panel(content, title=f"[bold red]{safe_emoji} ERROR[/bold red]", box=box.HEAVY, border_style="red", padding=(1, 2))
        self.console.print()
        self.console.print(panel)
        self.console.print()

# Global instance
rich_logger = ConsoleLogger()
