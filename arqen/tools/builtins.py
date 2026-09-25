from arqen.tools.registry import ToolRegistry
from arqen.tools.current_time import CurrentTimeTool
from arqen.tools.active_window import ActiveWindowTool
from arqen.tools.system_status import SystemStatusTool
from arqen.tools.system_resources import SystemResourcesTool
from arqen.tools.processes import RunningProcessesTool
from arqen.tools.windows import OpenWindowsTool
from arqen.tools.launch import LaunchPathTool
from arqen.tools.programs import LaunchProgramTool
from arqen.tools.installed_programs import InstalledProgramsTool
from arqen.tools.close_program import CloseProgramTool
from arqen.tools.focus_window import FocusWindowTool
from arqen.tools.speech import SpeakTextTool
from arqen.tools.stop_speech import StopSpeechTool
from arqen.tools.weather import WeatherForecastTool
from arqen.tools.workspace_files import (
    WorkspaceFilesTool,
    SearchWorkspaceFilesTool,
    SearchWorkspaceContentTool,
    ReadWorkspaceFileTool,
    WriteWorkspaceFileTool,
    DeleteWorkspaceFileTool,
    MoveWorkspaceFileTool,
    UndoWorkspaceFileTool,
)
from arqen.tools.pdf_documents import ReadPdfTool
from arqen.tools.docx_documents import ReadDocxTool
from arqen.tools.xlsx_documents import ReadXlsxTool
from arqen.tools.web_tools import FetchWebpageTool, OpenWebpageTool, SearchWebTool
from arqen.tools.browser_tools import (
    BrowserNavigateTool, BrowserReadPageTool, BrowserListLinksTool,
    BrowserClickLinkTool, BrowserBackTool, BrowserForwardTool,
)
from arqen.tools.image_generation import GenerateImageTool
from arqen.tools.memory_tools import ProposeMemoryTool


def create_builtin_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(SystemStatusTool())
    registry.register(CurrentTimeTool())
    registry.register(ActiveWindowTool())
    registry.register(SystemResourcesTool())
    registry.register(RunningProcessesTool())
    registry.register(OpenWindowsTool())
    registry.register(LaunchPathTool())
    registry.register(LaunchProgramTool())
    registry.register(InstalledProgramsTool())
    registry.register(CloseProgramTool())
    registry.register(FocusWindowTool())
    registry.register(SpeakTextTool())
    registry.register(StopSpeechTool())
    registry.register(WeatherForecastTool())
    registry.register(WorkspaceFilesTool())
    registry.register(SearchWorkspaceFilesTool())
    registry.register(SearchWorkspaceContentTool())
    registry.register(ReadWorkspaceFileTool())
    registry.register(WriteWorkspaceFileTool())
    registry.register(DeleteWorkspaceFileTool())
    registry.register(MoveWorkspaceFileTool())
    registry.register(UndoWorkspaceFileTool())
    registry.register(ReadPdfTool())
    registry.register(ReadDocxTool())
    registry.register(ReadXlsxTool())
    registry.register(FetchWebpageTool())
    registry.register(OpenWebpageTool())
    registry.register(SearchWebTool())
    registry.register(BrowserNavigateTool())
    registry.register(BrowserReadPageTool())
    registry.register(BrowserListLinksTool())
    registry.register(BrowserClickLinkTool())
    registry.register(BrowserBackTool())
    registry.register(BrowserForwardTool())
    registry.register(GenerateImageTool())
    registry.register(ProposeMemoryTool())
    return registry
