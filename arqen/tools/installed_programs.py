from typing import Any

from arqen.tools.base import Tool


class InstalledProgramsTool(Tool):
    name = "installed_programs"
    description = "Lists installed Windows programs from the standard uninstall registry keys."
    requires_confirmation = False

    def run(self, arguments: dict[str, Any]) -> str:
        try:
            import winreg
        except ImportError as exc:
            raise RuntimeError("Installed program listing is supported on Windows only") from exc

        locations = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]
        programs: set[str] = set()
        for hive, path in locations:
            try:
                with winreg.OpenKey(hive, path) as root:
                    for index in range(winreg.QueryInfoKey(root)[0]):
                        try:
                            subkey_name = winreg.EnumKey(root, index)
                            with winreg.OpenKey(root, subkey_name) as subkey:
                                name = winreg.QueryValueEx(subkey, "DisplayName")[0]
                                version = ""
                                try:
                                    version = winreg.QueryValueEx(subkey, "DisplayVersion")[0]
                                except OSError:
                                    pass
                                if name:
                                    programs.add(f"{name} {version}".strip())
                        except OSError:
                            continue
            except OSError:
                continue

        entries = sorted(programs, key=str.casefold)
        query = str(arguments.get("query", "")).strip().casefold()
        if query:
            entries = [entry for entry in entries if query in entry.casefold()]
        if not entries:
            return f"No installed programs found for: {query}" if query else "No installed programs found."
        return "Installed programs:\n" + "\n".join(entries[:100])
